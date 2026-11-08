"""Injeta as credenciais do firmware como build_flags (extra_script do PlatformIO).

Ordem de busca: variável de ambiente (CI, direnv) e depois firmware/.env.
O build falha se alguma estiver vazia, em vez de gerar um firmware com -DWIFI_SSID="".

Wi-Fi institucional (WPA2-Enterprise, como o eduroam): basta definir WIFI_EAP_USER.
WIFI_PASS passa a ser a senha desse usuário. Opcionais: WIFI_EAP_IDENTITY (identidade
externa, ex.: anonymous@universidade.br), WIFI_EAP_METHOD (PEAP ou TTLS) e
WIFI_EAP_CA_FILE (certificado da autoridade do servidor RADIUS, em PEM).
"""

import os
import sys
from pathlib import Path

Import("env")  # noqa: F821  (fornecido pelo SCons/PlatformIO)

OBRIGATORIAS = ("WIFI_SSID", "WIFI_PASS", "MQTT_HOST", "MQTT_USER", "MQTT_PASS")
OPCIONAIS_EAP = ("WIFI_EAP_USER", "WIFI_EAP_IDENTITY", "WIFI_EAP_METHOD", "WIFI_EAP_CA_FILE")
METODOS_EAP = {"PEAP": "WPA2_AUTH_PEAP", "TTLS": "WPA2_AUTH_TTLS"}
LIMITE_EAP = 64  # tamanho máximo aceito pelo Wi-Fi do ESP32 em identidade, usuário e senha


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


def falhar(mensagem: str) -> None:
    sys.stderr.write("\nErro: " + mensagem + "\n")
    env.Exit(1)  # noqa: F821


projeto = Path(env["PROJECT_DIR"])  # noqa: F821
dotenv = ler_dotenv(projeto / ".env")


def valor(nome: str) -> str:
    return os.environ.get(nome) or dotenv.get(nome, "")


valores = {nome: valor(nome) for nome in OBRIGATORIAS}

faltando = [nome for nome, v in valores.items() if not v]
if faltando:
    falhar(
        "variáveis vazias ou ausentes: " + ", ".join(faltando) + "\n"
        "Defina-as no ambiente ou em firmware/.env (modelo: firmware/.env.example)."
    )

eap = {nome: valor(nome) for nome in OPCIONAIS_EAP}
definicoes = list(valores.items())

if eap["WIFI_EAP_USER"]:
    metodo = (eap["WIFI_EAP_METHOD"] or "PEAP").upper()
    if metodo not in METODOS_EAP:
        falhar(f"WIFI_EAP_METHOD={eap['WIFI_EAP_METHOD']} não é suportado; use PEAP ou TTLS.")
    identidade = eap["WIFI_EAP_IDENTITY"] or eap["WIFI_EAP_USER"]
    campos = {"WIFI_EAP_USER": eap["WIFI_EAP_USER"], "WIFI_EAP_IDENTITY": identidade, "WIFI_PASS": valores["WIFI_PASS"]}
    longos = [nome for nome, v in campos.items() if len(v.encode("utf-8")) > LIMITE_EAP]
    if longos:
        falhar(", ".join(longos) + f" passa(m) de {LIMITE_EAP} bytes, o limite do Wi-Fi do ESP32.")
    definicoes += [("WIFI_EAP_USER", eap["WIFI_EAP_USER"]), ("WIFI_EAP_IDENTITY", identidade)]
    env.Append(CPPDEFINES=[("WIFI_EAP_METHOD", METODOS_EAP[metodo])])  # noqa: F821

    # O PEM tem várias linhas e não cabe num -D; vira um cabeçalho gerado na pasta do build
    gerados = Path(env.subst("$BUILD_DIR")) / "generated"  # noqa: F821
    gerados.mkdir(parents=True, exist_ok=True)
    if eap["WIFI_EAP_CA_FILE"]:
        ca = Path(eap["WIFI_EAP_CA_FILE"])
        ca = ca if ca.is_absolute() else projeto / ca
        if not ca.is_file():
            falhar(f"WIFI_EAP_CA_FILE aponta para {ca}, que não existe.")
        pem = ca.read_text(encoding="utf-8").strip()
        if "-----BEGIN CERTIFICATE-----" not in pem or ')PEM"' in pem:
            falhar(f"{ca} não parece um certificado PEM.")
        (gerados / "wifi_eap_ca.h").write_text(
            "// Gerado por load_env.py a partir de WIFI_EAP_CA_FILE; não edite\n"
            f'static const char kWifiEapCaPem[] = R"PEM({pem}\n)PEM";\n',
            encoding="utf-8",
        )
        env.Append(CPPDEFINES=["WIFI_EAP_HAS_CA"], CPPPATH=[str(gerados)])  # noqa: F821
    else:
        sys.stderr.write(
            "\nAviso: Wi-Fi institucional sem WIFI_EAP_CA_FILE. O sensor não confere o servidor\n"
            "da rede, e um ponto de acesso falso com o mesmo nome pode capturar a senha.\n"
            "Peça o certificado da autoridade (CA) à TI da instituição.\n\n"
        )

# String entre aspas escapadas, como o antigo -DWIFI_SSID=\"...\" do platformio.ini
env.Append(CPPDEFINES=[(nome, env.StringifyMacro(v)) for nome, v in definicoes])  # noqa: F821
