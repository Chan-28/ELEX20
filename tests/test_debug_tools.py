"""Ferramentas de debug (debug/): análise dos microfones, simulador e saúde dos sensores, sem hardware."""

import json
import random
import re
import shutil
import struct
import subprocess
from pathlib import Path

import mic_check
import numpy as np
import pytest
import sensor_health
import simulate_sensor

RAIZ = Path(__file__).resolve().parent.parent
TAXA = 16000


def seno(freq, amplitude, segundos=1.0, dc=0.0):
    t = np.arange(int(TAXA * segundos)) / TAXA
    return np.round(dc + amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def canal(nome, **valores):
    base = {"name": nome, "rms": -70.0, "peak": -50.0, "dc": 0.0, "clip": 0.0, "zero": 0.0, "hum": -40.0}
    return base | valores


# ── Microfones ────────────────────────────────────────────────────────────────


def test_estatistica_do_canal_igual_a_do_firmware():
    """Os mesmos valores que firmware/test/test_core confere em mic_stats.cpp."""
    r = mic_check.estatistica_canal(seno(1000, 16384, dc=100))
    assert r["dc"] == pytest.approx(100, abs=1)
    assert r["rms"] == pytest.approx(-9.03, abs=0.2)
    assert r["peak"] == pytest.approx(-6.0, abs=0.2)
    assert r["clip"] == 0
    assert r["hum"] < -40
    assert mic_check.estatistica_canal(seno(60, 3000))["hum"] > -1
    morto = mic_check.estatistica_canal(np.zeros(TAXA, dtype=np.int16))
    assert morto["zero"] == 100
    assert morto["rms"] == -120


def test_veredito_aponta_canal_morto_saturado_zumbido_e_desvio():
    canais = [
        canal("front"),
        canal("right", zero=100.0, rms=-120.0),
        canal("back", clip=2.0, hum=-3.0),
        canal("left", rms=-55.0),
    ]
    achados = {(a.canal, a.nivel) for a in mic_check.avaliar(canais)}
    assert ("right", "erro") in achados
    assert ("back", "aviso") in achados
    assert ("left", "aviso") in achados  # 15 dB acima da mediana dos vivos
    assert ("front", "aviso") not in achados and ("front", "erro") not in achados


def test_sala_silenciosa_so_avisa_quando_pedido():
    barulho = [canal(n, rms=-40.0) for n in mic_check.CANAIS]
    assert mic_check.avaliar(barulho) == []
    assert len(mic_check.avaliar(barulho, sala_silenciosa=True)) == 4


def test_toque_identifica_o_canal_que_se_destaca():
    canais = [canal(n, peak=-40.0) for n in mic_check.CANAIS]
    assert mic_check.canal_do_toque(canais) is None
    canais[2] = canal("back", peak=-8.0)
    assert mic_check.canal_do_toque(canais) == "back"
    canais[0] = canal("front", peak=-12.0)  # dois canais altos: ambíguo
    assert mic_check.canal_do_toque(canais) is None


def quadro(amostras: np.ndarray, soma_errada=False) -> bytes:
    dados = amostras.astype("<i2").tobytes()
    soma = (sum(dados) + (1 if soma_errada else 0)) & 0xFFFF
    return b"ELXA" + struct.pack("<BBH", amostras.shape[1], 0, amostras.shape[0]) + dados + struct.pack("<H", soma)


def test_leitor_de_quadros_aguenta_texto_corte_e_corrupcao():
    a = np.arange(40, dtype=np.int16).reshape(10, 4)
    b = -np.arange(40, dtype=np.int16).reshape(10, 4)
    fluxo = b"# rec 4\n" + quadro(a) + quadro(b, soma_errada=True) + quadro(b) + b"\n# stop overflow=0\n"
    leitor = mic_check.LeitorDeQuadros()
    recebidos = []
    for i in range(0, len(fluxo), 7):  # chega aos pedaços, como pela serial
        recebidos += leitor.alimentar(fluxo[i : i + 7])
    assert [c for c, _ in recebidos] == [4, 4]
    assert np.array_equal(recebidos[0][1], a)
    assert np.array_equal(recebidos[1][1], b)
    assert leitor.corrompidos == 1


def test_wav_ida_e_volta_e_analyze(tmp_path):
    quatro = np.stack([seno(440, 3000), seno(440, 3000), seno(440, 3000), np.zeros(TAXA, np.int16)], axis=1)
    arquivo = tmp_path / "bancada.wav"
    mic_check.gravar_wav(arquivo, quatro)
    taxa, lido = mic_check.ler_wav(arquivo)
    assert taxa == TAXA
    assert np.array_equal(lido, quatro)
    assert mic_check.main(["analyze", str(arquivo)]) == 1  # canal "left" morto


def test_relatorio_do_firmware_e_lido():
    """Formato de printReport() em debug/firmware/src/main.cpp."""
    linha = (
        '{"t":"mic","short_reads":0,"ch":[{"name":"front","n":16000,"dc":1.0,"rms":-70.1,"peak":-50.2,'
        '"clip":0.000,"zero":0.0,"hum":-30.5}]}'
    )
    assert mic_check.ler_relatorio(linha)["ch"][0]["rms"] == -70.1
    assert mic_check.ler_relatorio("# ELEX20 bancada") is None
    assert mic_check.ler_relatorio("{quebrado") is None
    fonte = (RAIZ / "debug" / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")
    for chave in ("dc", "rms", "peak", "clip", "zero", "hum", "short_reads"):
        assert f'\\"{chave}\\"' in fonte
    assert "'E', 'L', 'X', 'A'" in fonte


def test_bancada_usa_os_mesmos_pinos_do_firmware():
    def pinos(caminho):
        texto = (RAIZ / caminho).read_text(encoding="utf-8")
        return dict(re.findall(r"-D((?:I2S\w*|MOTOR)_\w*PIN\w*)=(\d+)", texto))

    principal = pinos("firmware/platformio.ini")
    assert len(principal) == 8
    assert pinos("debug/firmware/platformio.ini") == principal


# ── Simulador ─────────────────────────────────────────────────────────────────


def test_status_simulado_traz_tudo_o_que_o_n8n_grava():
    workflow = json.loads((RAIZ / "n8n" / "workflows" / "mqtt-ingest.json").read_text(encoding="utf-8"))
    consulta = next(n for n in workflow["nodes"] if n["name"] == "Gravar device_status")["parameters"]["query"]
    colunas = re.search(r"INSERT INTO device_status \((.*?)\)", consulta, re.S).group(1)
    gravadas = {c.strip() for c in colunas.split(",")} - {"device_id", "raw_json"}
    assert gravadas <= set(simulate_sensor.status(random.Random(1), "sim-01", 60))  # noqa: S311


def test_inferencia_simulada_usa_rotulos_em_ingles_e_direcao_so_com_urgencia():
    rotulos = simulate_sensor.carregar_rotulos()
    assert "siren" in rotulos and "silence" not in rotulos  # silence está inativa
    rng = random.Random(3)  # noqa: S311 (dados de teste)
    for _ in range(50):
        p = simulate_sensor.inferencia(rng, "sim-01", rotulos, 0)
        assert ("sector" in p) == (rotulos[p["label"]] > 0)
        assert 0 <= p["confidence"] <= 1


def test_ids_e_host_publicado():
    assert simulate_sensor.ids_dos_sensores(2) == ["sim-01", "sim-02"]
    assert simulate_sensor.host_publicado("192.168.0.10:1883\n") == "192.168.0.10"
    assert simulate_sensor.host_publicado("0.0.0.0:1883\n[::]:1883\n") is None


@pytest.mark.skipif(shutil.which("node") is None, reason="sem Node.js")
def test_payloads_invalidos_sao_descartados_pelo_n8n():
    workflow = json.loads((RAIZ / "n8n" / "workflows" / "mqtt-ingest.json").read_text(encoding="utf-8"))
    codigo = next(n for n in workflow["nodes"] if n["name"] == "Validar mensagem")["parameters"]["jsCode"]
    itens = [
        {"json": {"topic": f"sound/{tipo}/sim-01", "message": mensagem}}
        for tipo, mensagem in simulate_sensor.payloads_invalidos()
    ]
    script = f"const ITENS = {json.dumps(itens)};\nconst $input = {{ all: () => ITENS }};\n"
    script += f"console.log(JSON.stringify((function () {{\n{codigo}\n}})()));"
    saida = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=30)  # noqa: S603, S607
    aceitos = [item["json"] for item in json.loads(saida.stdout)]
    # Rótulo e confiança válidos passam com os campos opcionais ruins em NULL; o resto é descartado
    assert [a["kind"] for a in aceitos] == ["inference", "status"]
    deteccao, status = aceitos
    assert deteccao["sector"] is None and deteccao["direction_deg"] is None
    assert status["rssi"] is None and status["temp_c"] is None and status["win_ms_avg"] is None


# ── Saúde dos sensores ────────────────────────────────────────────────────────


def serie(horas=2.0, passo=5.0, inicio=1_000_000.0, **extra):
    linhas, uptime = [], 100
    for i in range(int(horas * 3600 / passo)):
        dados = {"uptime_s": uptime, "win_ms_avg": 400.0, "win_ms_max": 500.0, "heap_min": 120000, "stack_min": 1500,
                 "wifi_connects": 1, "mqtt_connects": 1, "dropped": 0, "offline_dropped": 0, "temp_c": 45.0,
                 "rssi": -60, "stack_task": "net"}  # fmt: skip
        linhas.append((inicio + i * passo, dados | {k: f(i) for k, f in extra.items()}))
        uptime += int(passo)
    return linhas


def test_sensor_saudavel_nao_tem_problemas():
    linhas = serie()
    resumo = sensor_health.analisar_sensor(linhas, agora=linhas[-1][0] + 2)
    assert resumo["reinicios"] == 0
    assert resumo["janela_ms_p50"] == 400.0
    assert sensor_health.problemas(resumo) == []


def test_sensor_com_reinicio_vazamento_lentidao_e_rede_instavel():
    linhas = serie(
        heap_min=lambda i: 120000 - i * 10,  # cai 7200 bytes/h
        win_ms_max=lambda i: 1200.0 if i == 50 else 500.0,
        mqtt_connects=lambda i: 1 + i // 100,  # ~14 reconexões em 2 h
    )
    # Reinício no meio: uptime volta e os contadores recomeçam
    meio = len(linhas) // 2
    depois = linhas[meio:]
    for k, (t, d) in enumerate(depois):
        linhas[meio + k] = (t, d | {"uptime_s": 5 + 5 * k, "dropped": k // 10})
    descartadas = (len(depois) - 1) // 10
    del linhas[100:110]  # 50 s sem heartbeat
    resumo = sensor_health.analisar_sensor(linhas, agora=linhas[-1][0] + 2)
    assert resumo["reinicios"] == 1
    assert resumo["fora_do_ar"] == 1
    assert resumo["janela_ms_max"] == 1200.0
    assert resumo["heap_min_bytes_por_hora"] == pytest.approx(-7200, rel=0.05)
    assert resumo["janelas_descartadas"] == descartadas
    texto = " ".join(sensor_health.problemas(resumo))
    for trecho in ("reiniciou", "sem heartbeat", "975 ms", "vazamento", "reconexões"):
        assert trecho in texto


def test_saida_do_psql_e_agrupada_por_sensor():
    csv = 'a|10.5|{"uptime_s":1}\nb|11|{"uptime_s":2}\na|12|não é json\nlinha ruim\na|13|{"uptime_s":3}\n'
    por_sensor = sensor_health.ler_linhas(csv)
    assert [t for t, _ in por_sensor["a"]] == [10.5, 13.0]
    assert len(por_sensor["b"]) == 1
