"""Injeta as credenciais do firmware como build_flags (extra_script do PlatformIO).

Ordem de busca: variável de ambiente (CI, direnv) e depois firmware/.env.
O build falha se alguma estiver vazia, em vez de gerar um firmware com -DWIFI_SSID="".
"""

import os
import sys
from pathlib import Path

Import("env")  # noqa: F821  (fornecido pelo SCons/PlatformIO)

OBRIGATORIAS = ("WIFI_SSID", "WIFI_PASS", "MQTT_HOST", "MQTT_USER", "MQTT_PASS")


def ler_dotenv(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not caminho.is_file():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip().strip("\"'")
    return valores


dotenv = ler_dotenv(Path(env["PROJECT_DIR"]) / ".env")  # noqa: F821
valores = {nome: os.environ.get(nome) or dotenv.get(nome, "") for nome in OBRIGATORIAS}

faltando = [nome for nome, valor in valores.items() if not valor]
if faltando:
    sys.stderr.write(
        "\nErro: variáveis vazias ou ausentes: " + ", ".join(faltando) + "\n"
        "Defina-as no ambiente ou em firmware/.env (modelo: firmware/.env.example).\n"
    )
    env.Exit(1)  # noqa: F821

# String entre aspas escapadas, como o antigo -DWIFI_SSID=\"...\" do platformio.ini
env.Append(CPPDEFINES=[(nome, env.StringifyMacro(valor)) for nome, valor in valores.items()])  # noqa: F821
