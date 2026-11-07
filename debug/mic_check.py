"""Teste de qualidade dos microfones do ELEX20, com o firmware de bancada (debug/firmware).

Grave o firmware de bancada e rode, com a placa na USB:

    uv run --group debug python debug/mic_check.py report --port /dev/ttyUSB0 [--quiet-room]
    uv run --group debug python debug/mic_check.py tap --port /dev/ttyUSB0
    uv run --group debug python debug/mic_check.py record saida.wav --port /dev/ttyUSB0 --seconds 10
    uv run --group debug python debug/mic_check.py analyze saida.wav [--quiet-room]
    uv run --group debug python debug/mic_check.py motors --port /dev/ttyUSB0

report  mostra, a cada segundo, nível, ruído, saturação, DC e zumbido de cada canal, com veredito.
tap     pede para bater em cada microfone e confere se o canal certo responde (ordem e L/R).
record  grava os 4 canais (ou a mistura que vai para o modelo, com --channels 1) num WAV.
analyze faz a mesma análise do report num WAV gravado (pela bancada ou outro gravador).
motors  aciona os quatro motores em sequência.

A escala é a do firmware: 0 dBFS é o limite do int16 depois do ganho de 4x (>>14).
Nela, um INMP441 em sala silenciosa fica perto de -75 a -65 dBFS.
"""

from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CANAIS = ("front", "right", "back", "left")
NOMES_PT = {"front": "frente", "right": "direita", "back": "trás", "left": "esquerda"}
TAXA = 16000
BAUD = 2_000_000

# Limites do veredito, na escala do firmware (ver docstring)
MORTO_RMS_DBFS = -100.0  # abaixo disso não há sinal nem ruído: canal desligado
MORTO_ZERO_PCT = 90.0
SALA_SILENCIOSA_MAX_DBFS = -50.0  # com --quiet-room, acima disso há interferência
SATURACAO_MAX_PCT = 0.1
DC_MAX = 500.0
ZUMBIDO_MAX_DB = -10.0  # 50/60 Hz e harmônicos com mais de 10% da energia
DESVIO_MAX_DB = 6.0  # diferença de ganho entre canais com o mesmo som
TOQUE_MIN_PICO_DBFS = -30.0
TOQUE_MARGEM_DB = 8.0

MAGICO = b"ELXA"
FREQS_ZUMBIDO = (50.0, 60.0, 100.0, 120.0, 150.0, 180.0)


# ── Análise (sem hardware; testada em tests/test_debug_tools.py) ─────────────


def para_dbfs(amplitude: float) -> float:
    if amplitude <= 0:
        return -120.0
    return max(-120.0, 20 * float(np.log10(amplitude / 32768.0)))


def estatistica_canal(x: np.ndarray, taxa: int = TAXA) -> dict:
    """Mesma conta de firmware/lib/elex_core/mic_stats.cpp, para um canal int16."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n == 0:
        return {"n": 0, "dc": 0.0, "rms": -120.0, "peak": -120.0, "clip": 0.0, "zero": 0.0, "hum": -120.0}
    dc = float(x.mean())
    rms = float(np.sqrt(max(float((x * x).mean()) - dc * dc, 0.0)))
    bloco = taxa // 10
    blocos = x[: (n // bloco) * bloco].reshape(-1, bloco)
    zumbido = -120.0
    if len(blocos) and rms > 0:
        t = np.arange(bloco) / taxa
        potencia = 0.0
        for f in FREQS_ZUMBIDO:
            amp = 2 * np.abs(blocos @ np.exp(-2j * np.pi * f * t)) / bloco
            potencia += float((amp**2 / 2).mean())
        if potencia > 0:
            zumbido = max(-120.0, 10 * float(np.log10(potencia / rms**2)))
    return {
        "n": n,
        "dc": dc,
        "rms": para_dbfs(rms),
        "peak": para_dbfs(float(np.abs(x).max())),
        "clip": 100.0 * float(((x >= 32767) | (x <= -32768)).mean()),
        "zero": 100.0 * float((x == 0).mean()),
        "hum": zumbido,
    }


def ler_relatorio(linha: str) -> dict | None:
    """Linha JSON do firmware de bancada ({"t":"mic",...}); None para qualquer outra coisa."""
    linha = linha.strip()
    if not linha.startswith("{"):
        return None
    try:
        dados = json.loads(linha)
    except json.JSONDecodeError:
        return None
    if dados.get("t") != "mic" or not isinstance(dados.get("ch"), list):
        return None
    return dados


@dataclass
class Achado:
    canal: str
    nivel: str  # "erro" ou "aviso"
    texto: str


def avaliar(canais: list[dict], sala_silenciosa: bool = False) -> list[Achado]:
    """Veredito por canal. canais: dicts com name, rms, peak, dc, clip, zero, hum."""
    achados: list[Achado] = []
    vivos = []
    for c in canais:
        nome = c["name"]
        if c["zero"] >= MORTO_ZERO_PCT or c["rms"] <= MORTO_RMS_DBFS:
            achados.append(Achado(nome, "erro", "canal morto: confira solda, pino SD, L/R e alimentação"))
            continue
        vivos.append(c)
        if c["clip"] > SATURACAO_MAX_PCT:
            achados.append(Achado(nome, "aviso", f"saturando ({c['clip']:.2f}% no limite): som alto ou ganho alto"))
        if abs(c["dc"]) > DC_MAX:
            achados.append(
                Achado(nome, "aviso", f"offset DC alto ({c['dc']:.0f}): o INMP441 normalmente fica perto de 0")
            )
        if c["hum"] > ZUMBIDO_MAX_DB:
            achados.append(
                Achado(nome, "aviso", f"zumbido de 50/60 Hz forte ({c['hum']:.1f} dB): fonte ou aterramento")
            )
        if sala_silenciosa and c["rms"] > SALA_SILENCIOSA_MAX_DBFS:
            achados.append(
                Achado(nome, "aviso", f"ruído alto em silêncio ({c['rms']:.1f} dBFS): interferência ou microfone ruim")
            )
    if len(vivos) >= 3:
        mediana = statistics.median(c["rms"] for c in vivos)
        for c in vivos:
            desvio = c["rms"] - mediana
            if abs(desvio) > DESVIO_MAX_DB:
                achados.append(
                    Achado(
                        c["name"],
                        "aviso",
                        f"nível {desvio:+.1f} dB longe dos outros: com o mesmo som chegando a todos, "
                        "indica microfone fraco, furo tampado ou ganho diferente",
                    )
                )
    return achados


def canal_do_toque(canais: list[dict]) -> str | None:
    """Canal que se destaca no pico (um toque perto de um microfone), ou None."""
    ordenados = sorted(canais, key=lambda c: c["peak"], reverse=True)
    if len(ordenados) < 2 or ordenados[0]["peak"] < TOQUE_MIN_PICO_DBFS:
        return None
    if ordenados[0]["peak"] - ordenados[1]["peak"] < TOQUE_MARGEM_DB:
        return None
    return ordenados[0]["name"]


@dataclass
class LeitorDeQuadros:
    """Separa os quadros binários "ELXA" do que mais vier pela serial."""

    buffer: bytearray = field(default_factory=bytearray)
    corrompidos: int = 0

    def alimentar(self, dados: bytes) -> list[tuple[int, np.ndarray]]:
        self.buffer += dados
        quadros = []
        while True:
            inicio = self.buffer.find(MAGICO)
            if inicio < 0:
                del self.buffer[: max(0, len(self.buffer) - len(MAGICO) + 1)]
                return quadros
            if len(self.buffer) - inicio < 8:
                del self.buffer[:inicio]
                return quadros
            canais, _, n = struct.unpack_from("<BBH", self.buffer, inicio + 4)
            tamanho = n * canais * 2
            fim = inicio + 8 + tamanho + 2
            if canais not in (1, 4) or n == 0:
                del self.buffer[: inicio + 1]  # cabeçalho falso: procura o próximo
                continue
            if len(self.buffer) < fim:
                del self.buffer[:inicio]
                return quadros
            amostras = bytes(self.buffer[inicio + 8 : inicio + 8 + tamanho])
            (soma,) = struct.unpack_from("<H", self.buffer, inicio + 8 + tamanho)
            if sum(amostras) & 0xFFFF == soma:
                quadros.append((canais, np.frombuffer(amostras, dtype="<i2").reshape(n, canais)))
                del self.buffer[:fim]
            else:
                self.corrompidos += 1
                del self.buffer[: inicio + 1]


def gravar_wav(caminho: Path, amostras: np.ndarray, taxa: int = TAXA) -> None:
    amostras = np.asarray(amostras, dtype="<i2")
    if amostras.ndim == 1:
        amostras = amostras[:, None]
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(amostras.shape[1])
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(amostras.tobytes())


def ler_wav(caminho: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(caminho), "rb") as arquivo:
        if arquivo.getsampwidth() != 2:
            raise ValueError("só WAV de 16 bits")
        dados = np.frombuffer(arquivo.readframes(arquivo.getnframes()), dtype="<i2")
        return arquivo.getframerate(), dados.reshape(-1, arquivo.getnchannels())


def nomes_dos_canais(quantidade: int) -> tuple[str, ...]:
    if quantidade == 4:
        return CANAIS
    if quantidade == 1:
        return ("mono",)
    return tuple(f"ch{i}" for i in range(quantidade))


# ── Saída no terminal ─────────────────────────────────────────────────────────


def imprimir_tabela(canais: list[dict], achados: list[Achado]) -> None:
    print(f"{'canal':<9}{'RMS dBFS':>9}{'pico':>8}{'DC':>8}{'satur.%':>9}{'zeros%':>8}{'zumbido':>9}  veredito")
    for c in canais:
        dele = [a for a in achados if a.canal == c["name"]]
        veredito = "ERRO" if any(a.nivel == "erro" for a in dele) else "aviso" if dele else "ok"
        nome = NOMES_PT.get(c["name"], c["name"])
        print(
            f"{nome:<9}{c['rms']:>9.1f}{c['peak']:>8.1f}{c['dc']:>8.0f}{c['clip']:>9.3f}{c['zero']:>8.1f}"
            f"{c['hum']:>9.1f}  {veredito}"
        )
    for a in achados:
        print(f"  [{a.nivel}] {NOMES_PT.get(a.canal, a.canal)}: {a.texto}")


# ── Serial (precisa da placa) ─────────────────────────────────────────────────


def abrir_porta(porta: str, baud: int):
    try:
        import serial  # noqa: PLC0415 (só quem usa a placa precisa do pyserial)
    except ImportError:
        sys.exit("Falta o pyserial: rode com `uv run --group debug python debug/mic_check.py ...`")
    conexao = serial.Serial(porta, baud, timeout=0.2)
    conexao.reset_input_buffer()
    return conexao


def comando(conexao, texto: str) -> None:
    conexao.write((texto + "\n").encode())
    conexao.flush()


def relatorios(conexao):
    """Gera os relatórios do firmware de bancada, um por segundo."""
    while True:
        linha = conexao.readline().decode("utf-8", errors="replace")
        dados = ler_relatorio(linha)
        if dados:
            yield dados


def cmd_report(args) -> int:
    conexao = abrir_porta(args.port, args.baud)
    comando(conexao, "stop")
    leituras_curtas = None
    try:
        for dados in relatorios(conexao):
            print(f"\n── {time.strftime('%H:%M:%S')} ──")
            achados = avaliar(dados["ch"], args.quiet_room)
            imprimir_tabela(dados["ch"], achados)
            if leituras_curtas is not None and dados["short_reads"] > leituras_curtas:
                print("  [aviso] as duas portas I2S entregaram blocos de tamanhos diferentes: confira BCLK/WS")
            leituras_curtas = dados["short_reads"]
    except KeyboardInterrupt:
        return 0


def cmd_tap(args) -> int:
    conexao = abrir_porta(args.port, args.baud)
    comando(conexao, "stop")
    fonte = relatorios(conexao)
    erros = 0
    print("Fique em silêncio e bata de leve com o dedo em cada microfone quando pedir.")
    for esperado in CANAIS:
        print(f"\n→ Bata no microfone da {NOMES_PT[esperado].upper()} (até 6 s)...")
        prazo = time.monotonic() + 6
        achado = None
        while time.monotonic() < prazo and achado is None:
            achado = canal_do_toque(next(fonte)["ch"])
        if achado is None:
            print(f"  [erro] nenhum canal se destacou: o microfone da {NOMES_PT[esperado]} pode estar morto")
            erros += 1
        elif achado != esperado:
            print(
                f"  [erro] o toque apareceu no canal {NOMES_PT[achado]}: canais trocados "
                "(pino L/R do INMP441 ou portas I2S invertidas); a direção vai vibrar o motor errado"
            )
            erros += 1
        else:
            print("  ok")
        time.sleep(1.0)  # deixa o relatório do toque passar
    print("\nOrdem dos canais correta." if erros == 0 else f"\n{erros} problema(s) na ordem dos canais.")
    return 1 if erros else 0


def cmd_record(args) -> int:
    conexao = abrir_porta(args.port, args.baud)
    leitor = LeitorDeQuadros()
    comando(conexao, "stop")
    time.sleep(0.3)
    conexao.reset_input_buffer()
    comando(conexao, f"rec {args.channels}")
    blocos = []
    total = args.seconds * TAXA
    obtidos = 0
    prazo = time.monotonic() + args.seconds + 5
    while obtidos < total and time.monotonic() < prazo:
        for canais, quadro in leitor.alimentar(conexao.read(8192)):
            if canais == args.channels:
                blocos.append(quadro)
                obtidos += len(quadro)
    comando(conexao, "stop")
    if not blocos:
        print("Nenhum áudio recebido: confira a porta, o baud e se o firmware de bancada está gravado.")
        return 1
    amostras = np.concatenate(blocos)[:total]
    gravar_wav(Path(args.output), amostras)
    print(f"{len(amostras) / TAXA:.1f} s gravados em {args.output} ({args.channels} canal(is)).")
    if leitor.corrompidos:
        print(f"[aviso] {leitor.corrompidos} quadro(s) corrompido(s) na serial: baixe o baud ou use --channels 1")
    if obtidos < total:
        print("[aviso] gravação incompleta: a serial não acompanhou")
    analisar(amostras, args.quiet_room)
    return 0


def analisar(amostras: np.ndarray, sala_silenciosa: bool, taxa: int = TAXA) -> list[Achado]:
    nomes = nomes_dos_canais(amostras.shape[1])
    canais = [{"name": nome, **estatistica_canal(amostras[:, i], taxa)} for i, nome in enumerate(nomes)]
    achados = avaliar(canais, sala_silenciosa)
    imprimir_tabela(canais, achados)
    return achados


def cmd_analyze(args) -> int:
    taxa, amostras = ler_wav(Path(args.wav))
    if taxa != TAXA:
        print(f"[aviso] o WAV está a {taxa} Hz; o modelo usa {TAXA} Hz")
    achados = analisar(amostras, args.quiet_room, taxa)
    return 1 if any(a.nivel == "erro" for a in achados) else 0


def cmd_motors(args) -> int:
    conexao = abrir_porta(args.port, args.baud)
    comando(conexao, "stop")
    comando(conexao, "motors")
    prazo = time.monotonic() + 4
    while time.monotonic() < prazo:
        linha = conexao.readline().decode("utf-8", errors="replace").strip()
        if linha.startswith("# motor"):
            print(linha[2:])
    print("Confira se cada motor vibrou na ordem frente, direita, trás, esquerda.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Teste de qualidade dos microfones (firmware de bancada).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def com_porta(p):
        p.add_argument("--port", required=True, help="porta serial, ex.: /dev/ttyUSB0 ou COM3")
        p.add_argument("--baud", type=int, default=BAUD)
        return p

    p = com_porta(sub.add_parser("report", help="qualidade de cada canal, a cada segundo"))
    p.add_argument("--quiet-room", action="store_true", help="avisa se o ruído de fundo estiver alto")
    p.set_defaults(func=cmd_report)
    com_porta(sub.add_parser("tap", help="confere a ordem dos canais batendo em cada microfone")).set_defaults(
        func=cmd_tap
    )
    p = com_porta(sub.add_parser("record", help="grava um WAV"))
    p.add_argument("output")
    p.add_argument("--seconds", type=int, default=10)
    p.add_argument("--channels", type=int, choices=(1, 4), default=4, help="4 canais ou a mistura mono do modelo")
    p.add_argument("--quiet-room", action="store_true")
    p.set_defaults(func=cmd_record)
    p = sub.add_parser("analyze", help="analisa um WAV")
    p.add_argument("wav")
    p.add_argument("--quiet-room", action="store_true")
    p.set_defaults(func=cmd_analyze)
    com_porta(sub.add_parser("motors", help="aciona os quatro motores em sequência")).set_defaults(func=cmd_motors)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
