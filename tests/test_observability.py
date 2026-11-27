"""Coerência do provisionamento do Grafana com o compose e o Alloy (sem Docker)."""

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE = (RAIZ / "docker-compose.yaml").read_text(encoding="utf-8")
PROVISIONAMENTO = RAIZ / "grafana" / "provisioning"


def _servicos() -> dict[str, str]:
    """Nome do serviço -> bloco de texto dele no docker-compose.yaml."""
    corpo = COMPOSE.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    partes = re.split(r"^  ([a-z0-9-]+):\n", corpo, flags=re.M)
    return dict(zip(partes[1::2], partes[2::2], strict=True))


def test_todo_servico_rotula_os_logs_para_o_loki():
    # Sem o rótulo, os logs do serviço chegam ao Loki sem o label "service"
    servicos = _servicos()
    assert "grafana" in servicos
    sem_logging = [nome for nome, bloco in servicos.items() if "logging: *logging" not in bloco]
    assert not sem_logging
    assert "labels: com.docker.compose.service" in COMPOSE
    assert "com.docker.compose.service" in (RAIZ / "grafana/alloy/config.alloy").read_text(encoding="utf-8")


def test_pyroscope_saiu_da_stack():
    assert "pyroscope" not in COMPOSE.lower()


def test_alertas_usam_so_datasources_provisionadas():
    uids = set()
    for arquivo in (PROVISIONAMENTO / "datasources").glob("*.yaml"):
        texto = arquivo.read_text(encoding="utf-8")
        uids |= set(re.findall(r"^\s+uid: (\S+)", texto, flags=re.M))
        # Nunca o superusuário do banco
        assert not re.search(r"^\s+user: (postgres|\$\{POSTGRES_USER)", texto, flags=re.M)
    assert {"timescaledb", "loki"} <= uids

    alertas = (PROVISIONAMENTO / "alerting" / "elex20.yaml").read_text(encoding="utf-8")
    usados = set(re.findall(r"datasourceUid: (\S+)", alertas))
    assert usados - {"__expr__"} <= uids
    assert {"timescaledb", "loki"} <= usados


def test_painel_de_sensores_le_a_view_concedida_ao_grafana_ro():
    painel = json.loads((PROVISIONAMENTO / "dashboards" / "urban_sound.json").read_text(encoding="utf-8"))
    sqls = [t["rawSql"] for p in painel["panels"] for t in p.get("targets", []) if "rawSql" in t]
    assert any("device_last_status" in sql for sql in sqls)
    grants = (RAIZ / "timescaledb" / "db-init.sql").read_text(encoding="utf-8")
    assert re.search(r"GRANT SELECT ON [^;]*device_last_status[^;]* TO grafana_ro", grants)


def test_ultimos_eventos_mostram_a_direcao():
    """Marco 3: a direção estimada pelo ESP32 (8 setores) aparece no painel."""
    painel = json.loads((PROVISIONAMENTO / "dashboards" / "urban_sound.json").read_text(encoding="utf-8"))
    tabela = next(p for p in painel["panels"] if p.get("title") == "Últimos eventos")
    sql = tabela["targets"][0]["rawSql"]
    for coluna in ("sector", "direction_deg", "doa_confidence", "urgency"):
        assert coluna in sql
