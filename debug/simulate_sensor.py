"""Simula sensores ELEX20 no MQTT, para testar n8n, banco, Grafana, alertas e Hermes sem a placa.

    uv run python debug/simulate_sensor.py --devices 2 --duration 60
    uv run python debug/simulate_sensor.py --invalid           # também manda payloads inválidos
    uv run python debug/simulate_sensor.py --listen-commands   # mostra os comandos do Hermes/n8n
    uv run python debug/simulate_sensor.py --cleanup           # apaga do banco o que os sim-* gravaram

Cada sensor simulado publica o heartbeat em sound/status/<id> a cada 5 s (com as métricas de
desempenho do firmware) e detecções em sound/inference/<id>, como o firmware de verdade.
Os ids começam com "sim-" para não se misturarem aos sensores reais.

A senha do usuário "device" vem de --password, de MQTT_DEVICE_PASS ou do container mosquitto
(docker exec; os nomes dos containers são fixos). Use o Docker da stack (DOCKER_HOST do .envrc).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess  # noqa: S404 (lê a senha e limpa o banco pelo docker exec)
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PREFIXO = "sim-"
SETORES = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")


# ── Payloads (sem rede; testados em tests/test_debug_tools.py) ───────────────


def carregar_rotulos(caminho: Path = RAIZ / "classes" / "sound_classes.json") -> dict[str, int]:
    """Rótulo -> urgência, das categorias ativas."""
    categorias = json.loads(caminho.read_text(encoding="utf-8"))["categorias"]
    return {c["rotulo"]: c["urgencia"] for c in categorias if c.get("ativa", True)}


def ids_dos_sensores(quantidade: int) -> list[str]:
    return [f"{PREFIXO}{i:02d}" for i in range(1, quantidade + 1)]


def status(rng: random.Random, device: str, uptime_s: int, conexoes: tuple[int, int] = (1, 1)) -> dict:
    """Heartbeat com os mesmos campos de publishStatus() em firmware/src/main.cpp."""
    janela = rng.uniform(250, 600)
    return {
        "uptime_s": uptime_s,
        "heap": rng.randint(140_000, 160_000),
        "rssi": rng.randint(-75, -45),
        "device": device,
        "dropped": 0,
        "offline_dropped": 0,
        "threshold": 0.6,
        "doa_enabled": True,
        "motor_enabled": True,
        "port1_skew": 0.0,
        "win_ms_avg": round(janela, 1),
        "win_ms_max": round(janela * rng.uniform(1.05, 1.4), 1),
        "dsp_ms": round(janela * 0.3, 1),
        "nn_ms": round(janela * 0.6, 1),
        "heap_min": rng.randint(110_000, 130_000),
        "psram_free": rng.randint(7_000_000, 7_500_000),
        "stack_min": rng.randint(900, 2500),
        "stack_task": "net",
        "wifi_connects": conexoes[0],
        "mqtt_connects": conexoes[1],
        "temp_c": round(rng.uniform(38, 55), 1),
    }


def inferencia(rng: random.Random, device: str, rotulos: dict[str, int], ts_ms: int) -> dict:
    """Detecção como publishInference(); com urgência > 0 leva a direção, como o firmware."""
    rotulo = rng.choice(sorted(rotulos))
    payload = {"label": rotulo, "confidence": round(rng.uniform(0.6, 0.99), 3), "ts": ts_ms, "device": device}
    if rotulos[rotulo] > 0:
        setor = rng.randrange(8)
        payload |= {
            "direction_deg": (setor * 45 + rng.randint(-15, 15)) % 360,
            "sector": SETORES[setor],
            "doa_confidence": round(rng.uniform(0.4, 0.95), 2),
        }
    return payload


def payloads_invalidos() -> list[tuple[str, str]]:
    """(tópico relativo, mensagem) que o n8n precisa descartar, ou gravar sem os campos ruins (NULL)."""
    return [
        ("inference", "isto não é json"),
        ("inference", json.dumps([1, 2, 3])),
        ("inference", json.dumps({"label": "siren", "confidence": 1.5})),
        ("inference", json.dumps({"label": "a b;--", "confidence": 0.9})),
        ("inference", json.dumps({"label": "siren", "confidence": 0.9, "sector": "X", "direction_deg": 999})),
        ("inference", json.dumps({"label": "siren", "confidence": 0.9, "mock": True})),
        ("status", json.dumps({"uptime_s": -1, "rssi": 20, "temp_c": 999, "win_ms_avg": "rápido"})),
    ]


# ── MQTT e Docker ─────────────────────────────────────────────────────────────


def senha_do_dispositivo(senha: str | None) -> str:
    if senha:
        return senha
    if os.environ.get("MQTT_DEVICE_PASS"):
        return os.environ["MQTT_DEVICE_PASS"]
    try:
        saida = subprocess.run(  # noqa: S603
            ["docker", "exec", "mosquitto", "cat", "/run/secrets/mqtt_device/value"],  # noqa: S607
            cwd=RAIZ,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as erro:
        sys.exit(f"Não consegui ler a senha do MQTT pelo Docker ({erro}). Use --password ou MQTT_DEVICE_PASS.")
    return saida.stdout.strip()


def host_publicado(saida_docker_port: str) -> str | None:
    """Endereço da saída de `docker port mosquitto 1883` (ex.: "192.168.0.10:1883")."""
    for linha in saida_docker_port.splitlines():
        host, _, porta = linha.strip().rpartition(":")
        if porta == "1883" and host and host not in ("0.0.0.0", "[::]"):  # noqa: S104 (só compara)
            return host.strip("[]")
    return None


def host_padrao() -> str:
    """Onde o broker escuta: a porta publicada do container, o MQTT_BIND do .env ou o loopback."""
    try:
        saida = subprocess.run(
            ["docker", "port", "mosquitto", "1883"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        if host := host_publicado(saida):
            return host
    except (OSError, subprocess.SubprocessError):
        pass
    env = RAIZ / ".env"
    if env.is_file():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.startswith("MQTT_BIND="):
                valor = linha.partition("=")[2].strip().strip("\"'")
                if valor and valor != "0.0.0.0":  # noqa: S104 (só compara)
                    return valor
    return "127.0.0.1"


# Pela entrada padrão: o psql roda cada comando à parte, e o CALL não pode ficar numa transação
SQL_LIMPEZA = """
DELETE FROM sound_events WHERE device_id LIKE 'sim-%';
DELETE FROM device_status WHERE device_id LIKE 'sim-%';
DELETE FROM devices WHERE device_id LIKE 'sim-%';
CALL refresh_continuous_aggregate('sound_events_hourly', NULL, NULL);
"""


def limpar_banco() -> int:
    psql = 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
    resultado = subprocess.run(  # noqa: S603
        ["docker", "exec", "-i", "timescaledb", "sh", "-c", psql],  # noqa: S607
        cwd=RAIZ,
        input=SQL_LIMPEZA,
        text=True,
        check=False,
    )
    if resultado.returncode == 0:
        print(f"Dados dos sensores {PREFIXO}* apagados.")
    return resultado.returncode


def conectar(host: str, porta: int, senha: str, client_id: str):
    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415
    except ImportError:
        sys.exit("Falta o paho-mqtt: rode com `uv run python debug/simulate_sensor.py`")
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    cliente.username_pw_set("device", senha)
    try:
        cliente.connect(host, porta, keepalive=30)
    except OSError as erro:
        sys.exit(f"Sem conexão com o broker em {host}:{porta} ({erro}). Confira --host e se o mosquitto está no ar.")
    cliente.loop_start()
    return cliente


def simular(args) -> int:
    rng = random.Random(args.seed)  # noqa: S311 (dados de teste, não segurança)
    rotulos = carregar_rotulos()
    senha = senha_do_dispositivo(args.password)
    host = args.host or host_padrao()
    sensores = ids_dos_sensores(args.devices)
    # Client id = id do sensor: a ACL só entrega sound/cmd/<id> ao cliente com esse id
    clientes = {d: conectar(host, args.port, senha, d) for d in sensores}
    if args.listen_commands:
        for d, cliente in clientes.items():
            cliente.on_message = lambda _c, _u, msg: print(f"[cmd] {msg.topic}: {msg.payload.decode(errors='replace')}")
            cliente.subscribe(f"sound/cmd/{d}", qos=1)
    print(f"Simulando {', '.join(sensores)} em {host}:{args.port} por {args.duration} s (Ctrl+C para parar).")

    inicio = time.monotonic()
    proximo_status = inicio
    enviados = {"status": 0, "inference": 0, "invalid": 0}
    try:
        while time.monotonic() - inicio < args.duration:
            agora = time.monotonic()
            uptime = int(agora - inicio) + 60
            if agora >= proximo_status:
                for d, cliente in clientes.items():
                    cliente.publish(f"sound/status/{d}", json.dumps(status(rng, d, uptime)), qos=0, retain=True)
                    enviados["status"] += 1
                proximo_status = agora + 5
            for d, cliente in clientes.items():
                if rng.random() < args.events_per_minute / 60:
                    payload = inferencia(rng, d, rotulos, int(agora * 1000))
                    cliente.publish(f"sound/inference/{d}", json.dumps(payload))
                    enviados["inference"] += 1
                    print(f"[{d}] {payload['label']} {payload['confidence']:.2f} {payload.get('sector', '')}")
                if args.invalid and rng.random() < 0.1:
                    tipo, mensagem = rng.choice(payloads_invalidos())
                    cliente.publish(f"sound/{tipo}/{d}", mensagem)
                    enviados["invalid"] += 1
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for cliente in clientes.values():
            cliente.loop_stop()
            cliente.disconnect()
    print(
        f"Enviados: {enviados['status']} status, {enviados['inference']} detecções, {enviados['invalid']} inválidos. "
        "Confira no Grafana ou com debug/sensor_health.py; apague com --cleanup."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simula sensores ELEX20 no MQTT.")
    parser.add_argument("--host", help="broker (padrão: MQTT_BIND do .env ou 127.0.0.1)")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--password", help="senha do usuário device (padrão: lida do container)")
    parser.add_argument("--devices", type=int, default=1, help="quantos sensores simular")
    parser.add_argument("--duration", type=int, default=60, help="segundos de simulação")
    parser.add_argument("--events-per-minute", type=float, default=6.0)
    parser.add_argument("--invalid", action="store_true", help="manda também payloads inválidos")
    parser.add_argument("--listen-commands", action="store_true", help="mostra o que chegar em sound/cmd/<id>")
    parser.add_argument("--seed", type=int, help="semente, para repetir a mesma sequência")
    parser.add_argument("--cleanup", action="store_true", help="apaga do banco os dados dos sensores sim-*")
    args = parser.parse_args(argv)
    if args.cleanup:
        return limpar_banco()
    if not 1 <= args.devices <= 50:
        parser.error("--devices vai de 1 a 50")
    return simular(args)


if __name__ == "__main__":
    sys.exit(main())
