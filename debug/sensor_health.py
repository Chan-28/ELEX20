"""Saúde de cada sensor a partir dos heartbeats gravados em device_status.

    uv run python debug/sensor_health.py                 # últimas 24 h, todos os sensores
    uv run python debug/sensor_health.py --hours 72 --device esp32s3-sound-01
    uv run python debug/sensor_health.py --json

Serve para o teste de longa duração: deixe o sensor ligado um ou mais dias e rode este
script. Ele aponta reinícios, quedas de rede, janelas que não acompanham o áudio (mais de
975 ms), vazamento de memória (menor heap livre caindo), pouca folga de pilha e calor.

Lê do raw_json, então funciona também com bancos antigos, sem as colunas de desempenho.
O banco não expõe porta: a consulta vai pelo container (docker exec timescaledb), com o
Docker da stack (DOCKER_HOST do .envrc).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # noqa: S404 (consulta pelo docker exec)
import sys
import time

import numpy as np

JANELA_MS = 975.0  # duração da janela de áudio (AUDIO_WINDOW_MS)
INTERVALO_STATUS_S = 5.0
LACUNA_S = 30.0  # sem heartbeat por mais que isso = sensor fora do ar
VAZAMENTO_BYTES_POR_HORA = -1024.0
PILHA_MIN_BYTES = 512
TEMPERATURA_MAX_C = 80.0
RECONEXOES_POR_HORA_MAX = 2.0
RSSI_FRACO_DBM = -80

# Variáveis psql (-v) em vez de texto montado: o filtro de dispositivo vem da linha de comando
CONSULTA = """
SELECT device_id, extract(epoch FROM time), raw_json::text
FROM device_status
WHERE time > now() - make_interval(hours => :horas)
  AND (:'dispositivo' = '' OR device_id = :'dispositivo')
  AND raw_json IS NOT NULL
ORDER BY device_id, time;
"""


# ── Análise (sem banco; testada em tests/test_debug_tools.py) ────────────────


def _numeros(linhas: list[tuple[float, dict]], campo: str) -> np.ndarray:
    valores = [d.get(campo) for _, d in linhas]
    return np.array([v for v in valores if isinstance(v, int | float) and not isinstance(v, bool)], dtype=float)


def _segmentos(linhas: list[tuple[float, dict]]) -> list[list[tuple[float, dict]]]:
    """Corta a série a cada reinício (uptime voltando para trás)."""
    segmentos: list[list[tuple[float, dict]]] = []
    anterior = None
    for linha in linhas:
        uptime = linha[1].get("uptime_s")
        if not segmentos or (isinstance(uptime, int | float) and anterior is not None and uptime < anterior):
            segmentos.append([])
        segmentos[-1].append(linha)
        if isinstance(uptime, int | float):
            anterior = uptime
    return segmentos


def _crescimento(segmentos: list[list[tuple[float, dict]]], campo: str) -> float:
    """Quanto um contador cumulativo (desde o boot) cresceu, somando os trechos entre reinícios."""
    total = 0.0
    for segmento in segmentos:
        valores = _numeros(segmento, campo)
        if len(valores) >= 2:
            total += max(0.0, float(valores[-1] - valores[0]))
    return total


def _tendencia_por_hora(segmento: list[tuple[float, dict]], campo: str) -> float | None:
    pontos = [(t, d[campo]) for t, d in segmento if isinstance(d.get(campo), int | float)]
    if len(pontos) < 10 or pontos[-1][0] - pontos[0][0] < 1800:
        return None  # pouco tempo para falar em tendência
    t, v = np.array(pontos, dtype=float).T
    return float(np.polyfit((t - t[0]) / 3600.0, v, 1)[0])


def analisar_sensor(linhas: list[tuple[float, dict]], agora: float | None = None) -> dict:
    """Resumo de um sensor; linhas = (epoch, raw_json) em ordem de tempo."""
    agora = time.time() if agora is None else agora
    tempos = np.array([t for t, _ in linhas], dtype=float)
    horas = max((tempos[-1] - tempos[0]) / 3600.0, 1e-9) if len(tempos) > 1 else 0.0
    segmentos = _segmentos(linhas)
    lacunas = np.diff(tempos) if len(tempos) > 1 else np.array([])
    janela_media = _numeros(linhas, "win_ms_avg")
    janela_max = _numeros(linhas, "win_ms_max")
    rssi = _numeros(linhas, "rssi")
    heap_min = _numeros(linhas, "heap_min")
    pilha = _numeros(linhas, "stack_min")
    temperatura = _numeros(linhas, "temp_c")
    reconexoes = _crescimento(segmentos, "wifi_connects") + _crescimento(segmentos, "mqtt_connects")

    def pct(valores: np.ndarray, q: float) -> float | None:
        return round(float(np.percentile(valores, q)), 1) if len(valores) else None

    return {
        "amostras": len(linhas),
        "horas": round(horas, 2),
        "ultimo_sinal_s": round(agora - float(tempos[-1]), 1) if len(tempos) else None,
        "reinicios": len(segmentos) - 1,
        "fora_do_ar": int((lacunas > LACUNA_S).sum()),
        "maior_lacuna_s": round(float(lacunas.max()), 1) if len(lacunas) else None,
        "janela_ms_p50": pct(janela_media, 50),
        "janela_ms_p95": pct(janela_media, 95),
        "janela_ms_max": round(float(janela_max.max()), 1) if len(janela_max) else None,
        "dsp_ms_p50": pct(_numeros(linhas, "dsp_ms"), 50),
        "nn_ms_p50": pct(_numeros(linhas, "nn_ms"), 50),
        "heap_min": int(heap_min.min()) if len(heap_min) else None,
        "heap_min_bytes_por_hora": _tendencia_por_hora(segmentos[-1], "heap_min") if segmentos else None,
        "pilha_min": int(pilha.min()) if len(pilha) else None,
        "pilha_tarefa": next((d.get("stack_task") for _, d in reversed(linhas) if d.get("stack_task")), None),
        "reconexoes": int(reconexoes),
        "reconexoes_por_hora": round(reconexoes / horas, 2) if horas else None,
        "janelas_descartadas": int(_crescimento(segmentos, "dropped")),
        "deteccoes_sem_rede": int(_crescimento(segmentos, "offline_dropped")),
        "temperatura_max": round(float(temperatura.max()), 1) if len(temperatura) else None,
        "rssi_mediana": int(np.median(rssi)) if len(rssi) else None,
    }


def problemas(resumo: dict) -> list[str]:
    achados = []
    if resumo["ultimo_sinal_s"] is not None and resumo["ultimo_sinal_s"] > LACUNA_S:
        achados.append(f"sem heartbeat há {resumo['ultimo_sinal_s']:.0f} s: sensor fora do ar ou ingestão parada")
    if resumo["reinicios"]:
        achados.append(f"reiniciou {resumo['reinicios']} vez(es): falta de memória, estouro de pilha ou alimentação")
    if resumo["fora_do_ar"]:
        achados.append(f"{resumo['fora_do_ar']} período(s) sem heartbeat (maior: {resumo['maior_lacuna_s']:.0f} s)")
    if resumo["janela_ms_max"] is not None and resumo["janela_ms_max"] > JANELA_MS:
        achados.append(
            f"pior janela levou {resumo['janela_ms_max']:.0f} ms, mais que os {JANELA_MS:.0f} ms de áudio: "
            "a placa não acompanha e descarta janelas"
        )
    if resumo["janelas_descartadas"]:
        achados.append(f"{resumo['janelas_descartadas']} janela(s) de áudio descartada(s)")
    tendencia = resumo["heap_min_bytes_por_hora"]
    if tendencia is not None and tendencia < VAZAMENTO_BYTES_POR_HORA:
        achados.append(f"menor heap livre caindo {-tendencia:.0f} bytes/h: possível vazamento de memória")
    if resumo["pilha_min"] is not None and resumo["pilha_min"] < PILHA_MIN_BYTES:
        achados.append(f"só {resumo['pilha_min']} bytes de pilha livres na tarefa {resumo['pilha_tarefa']}")
    if resumo["reconexoes_por_hora"] is not None and resumo["reconexoes_por_hora"] > RECONEXOES_POR_HORA_MAX:
        achados.append(f"{resumo['reconexoes_por_hora']:.1f} reconexões por hora: rede instável")
    if resumo["rssi_mediana"] is not None and resumo["rssi_mediana"] < RSSI_FRACO_DBM:
        achados.append(f"Wi-Fi fraco (mediana {resumo['rssi_mediana']} dBm)")
    if resumo["deteccoes_sem_rede"]:
        achados.append(f"{resumo['deteccoes_sem_rede']} detecção(ões) perdida(s) sem rede")
    if resumo["temperatura_max"] is not None and resumo["temperatura_max"] > TEMPERATURA_MAX_C:
        achados.append(f"chegou a {resumo['temperatura_max']:.0f} °C: ventilação da caixa")
    return achados


def ler_linhas(csv: str) -> dict[str, list[tuple[float, dict]]]:
    """Saída do psql (-At -F '|') agrupada por sensor; linhas com JSON inválido são puladas."""
    por_sensor: dict[str, list[tuple[float, dict]]] = {}
    for linha in csv.splitlines():
        partes = linha.split("|", 2)
        if len(partes) != 3:
            continue
        try:
            dados = json.loads(partes[2])
            instante = float(partes[1])
        except ValueError:
            continue
        if isinstance(dados, dict):
            por_sensor.setdefault(partes[0], []).append((instante, dados))
    return por_sensor


# ── Banco e saída ─────────────────────────────────────────────────────────────


def consultar(horas: int, dispositivo: str) -> str:
    psql = (
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -v ON_ERROR_STOP=1 '
        f'-v horas={horas} -v dispositivo="$ELEX_DEVICE"'
    )
    try:
        resultado = subprocess.run(  # noqa: S603
            ["docker", "exec", "-i", "-e", f"ELEX_DEVICE={dispositivo}", "timescaledb", "sh", "-c", psql],  # noqa: S607
            input=CONSULTA,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as erro:
        detalhe = getattr(erro, "stderr", "") or erro
        sys.exit(f"Falha ao consultar o banco pelo container timescaledb: {detalhe}")
    return resultado.stdout


def imprimir(sensor: str, resumo: dict, achados: list[str]) -> None:
    def v(chave: str, sufixo: str = "") -> str:
        valor = resumo[chave]
        return "—" if valor is None else f"{valor}{sufixo}"

    print(f"\n■ {sensor}  ({resumo['amostras']} heartbeats em {resumo['horas']} h)")
    print(
        f"  janela: p50 {v('janela_ms_p50', ' ms')}, p95 {v('janela_ms_p95', ' ms')}, pior {v('janela_ms_max', ' ms')}"
    )
    print(f"  modelo: DSP {v('dsp_ms_p50', ' ms')}, classificação {v('nn_ms_p50', ' ms')} (medianas)")
    print(f"  memória: menor heap {v('heap_min', ' B')}, pilha mínima {v('pilha_min', ' B')} ({v('pilha_tarefa')})")
    print(f"  rede: {v('reconexoes')} reconexões, RSSI mediano {v('rssi_mediana', ' dBm')}")
    print(f"  temperatura máxima: {v('temperatura_max', ' °C')}")
    if achados:
        for achado in achados:
            print(f"  [!] {achado}")
    else:
        print("  ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Saúde dos sensores a partir de device_status.")
    parser.add_argument("--hours", type=int, default=24, help="janela de análise, em horas (1 a 720)")
    parser.add_argument("--device", default="", help="só este sensor")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args(argv)
    if not 1 <= args.hours <= 720:
        parser.error("--hours vai de 1 a 720")
    if args.device and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.device):
        parser.error("--device inválido")

    por_sensor = ler_linhas(consultar(args.hours, args.device))
    if not por_sensor:
        print(f"Nenhum heartbeat nas últimas {args.hours} h.")
        return 1
    resultado = {s: analisar_sensor(linhas) for s, linhas in por_sensor.items()}
    if args.json:
        print(
            json.dumps(
                {s: {**r, "problemas": problemas(r)} for s, r in resultado.items()}, ensure_ascii=False, indent=2
            )
        )
    else:
        for sensor, resumo in resultado.items():
            imprimir(sensor, resumo, problemas(resumo))
    return 1 if any(problemas(r) for r in resultado.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
