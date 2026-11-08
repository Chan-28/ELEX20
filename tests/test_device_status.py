"""Métricas de desempenho do sensor: firmware, n8n e banco precisam usar os mesmos campos."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOW = json.loads((RAIZ / "n8n" / "workflows" / "mqtt-ingest.json").read_text(encoding="utf-8"))
NOS = {n["name"]: n["parameters"] for n in WORKFLOW["nodes"]}
BANCO = (RAIZ / "timescaledb" / "db-init.sql").read_text(encoding="utf-8")
FIRMWARE = (RAIZ / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")


def colunas_do_insert() -> list[str]:
    consulta = NOS["Gravar device_status"]["query"]
    return [c.strip() for c in re.search(r"INSERT INTO device_status \((.*?)\)", consulta, re.S).group(1).split(",")]


def test_insert_tem_um_parametro_por_coluna():
    consulta = NOS["Gravar device_status"]["query"]
    insert = consulta[consulta.index("INSERT INTO device_status") :]
    valores = re.search(r"VALUES \((.*?)\);", insert, re.S).group(1)
    parametros = re.findall(r"\$(\d+)", valores)
    assert parametros == [str(i) for i in range(1, len(colunas_do_insert()) + 1)]
    lista = NOS["Gravar device_status"]["options"]["queryReplacement"]
    campos = re.findall(r"\$json\.(\w+)", lista)
    assert campos == colunas_do_insert()


def test_toda_coluna_gravada_existe_no_banco():
    criadas = set(re.findall(r"ADD COLUMN IF NOT EXISTS (\w+)", BANCO))
    tabela = re.search(r"CREATE TABLE IF NOT EXISTS device_status \((.*?)\n\);", BANCO, re.S).group(1)
    criadas |= set(re.findall(r"^\s+(\w+)\s+[A-Z]", tabela, re.M))
    assert set(colunas_do_insert()) <= criadas


def test_firmware_publica_toda_metrica_que_o_banco_grava():
    publicadas = set(re.findall(r'doc\["(\w+)"\]', FIRMWARE))
    for media, maximo in re.findall(r'putPerf\(doc, "(\w+)", (?:"(\w+)"|nullptr)', FIRMWARE):
        publicadas |= {media, maximo} - {""}
    gravadas = set(colunas_do_insert()) - {"device_id", "raw_json"}
    assert gravadas <= publicadas


def test_view_traz_as_metricas():
    view = re.search(r"CREATE OR REPLACE VIEW device_last_status AS(.*?);", BANCO, re.S).group(1)
    for coluna in ("win_ms_avg", "nn_ms", "heap_min", "stack_min", "temp_c"):
        assert coluna in view


@pytest.mark.skipif(shutil.which("node") is None, reason="sem Node.js")
def test_validador_do_n8n_aceita_metricas_e_descarta_o_que_esta_fora_da_faixa():
    status = {
        "uptime_s": 60, "heap": 150000, "rssi": -60, "win_ms_avg": 412.34, "win_ms_max": 980,
        "dsp_ms": 120, "nn_ms": 250.06, "heap_min": 90000, "psram_free": 7000000, "stack_min": 1800,
        "wifi_connects": 2, "mqtt_connects": 3, "dropped": 4, "offline_dropped": 0,
        "temp_c": 999, "stack_task": "net",
    }  # fmt: skip
    script = (
        "const $input = { all: () => ITENS };\n"
        f"const resultado = (function () {{\n{NOS['Validar mensagem']['jsCode']}\n}})();\n"
        "console.log(JSON.stringify(resultado));\n"
    )
    itens = [
        {"json": {"topic": "sound/status/esp32-01", "message": json.dumps(status)}},
        {"json": {"topic": "sound/status/esp32-01", "message": json.dumps({"uptime_s": 1, "win_ms_avg": -3})}},
        # o firmware apaga o status retido com um payload vazio: não é heartbeat
        {"json": {"topic": "sound/status/esp32-01", "message": ""}},
    ]
    saida = subprocess.run(  # noqa: S603 (script gerado pelo teste)
        ["node", "-e", f"const ITENS = {json.dumps(itens)};\n{script}"],  # noqa: S607
        capture_output=True, text=True, check=True, timeout=30,
    )  # fmt: skip
    completo, antigo = (item["json"] for item in json.loads(saida.stdout))
    assert completo["win_ms_avg"] == 412.3
    assert completo["nn_ms"] == 250.1
    assert completo["stack_min"] == 1800
    assert completo["mqtt_connects"] == 3
    assert completo["temp_c"] is None  # fora de -40..150
    # Firmware antigo, sem as métricas: tudo NULL, sem quebrar a gravação
    assert antigo["uptime_s"] == 1
    assert antigo["win_ms_avg"] is None
    assert antigo["heap_min"] is None


def test_firmware_nao_retem_o_status():
    """Um status retido seria reentregue a cada reconexão do n8n e gravado como heartbeat novo."""
    publicacoes = re.findall(r"mqtt\.publish\(TOPIC_STATUS,\s*(\w+|\"\"),\s*(true|false)\)", FIRMWARE)
    assert ("payload", "false") in publicacoes
    # o único publish retido é o vazio, que apaga o status retido por firmwares antigos
    assert [p for p in publicacoes if p[1] == "true"] == [('""', "true")]
