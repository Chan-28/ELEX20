"""Injeta as credenciais do firmware no build (extra_script do PlatformIO).

Ordem de busca: variável de ambiente (CI, direnv) e depois firmware/.env.
O build falha se alguma obrigatória estiver vazia, em vez de gerar um firmware sem rede.

Redes Wi-Fi: a primeira usa WIFI_SSID e WIFI_PASS; até três extras usam o prefixo
WIFI2_ a WIFI4_ (WIFI2_SSID, WIFI2_PASS...). O sensor tenta cada uma até conectar,
começando pela última que funcionou. Cada rede aceita, com o mesmo prefixo:

- EAP_USER: liga o Wi-Fi institucional (WPA2-Enterprise, como o eduroam); PASS vira a
  senha desse usuário. Opcionais: EAP_IDENTITY (identidade externa, ex.:
  anonymous@universidade.br), EAP_METHOD (PEAP ou TTLS) e EAP_CA_FILE (certificado da
  autoridade do servidor RADIUS, em PEM, relativo a firmware/).
- MQTT_HOST (só nas extras, ex.: WIFI2_MQTT_HOST): o servidor visto dessa rede; sem ele
  vale MQTT_HOST.

As redes vão para um cabeçalho gerado na pasta do build (wifi_networks.h), lido pelo main.cpp.
"""

import os
import sys
from pathlib import Path

Import("env")  # noqa: F821  (fornecido pelo SCons/PlatformIO)

OBRIGATORIAS = ("MQTT_HOST", "MQTT_USER", "MQTT_PASS")
MAX_REDES = 4
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


def literal_c(texto: str | None) -> str:
    """String C com escapes octais (não emendam com o caractere seguinte, como os \\x)."""
    if texto is None:
        return "nullptr"
    partes = []
    for byte in texto.encode("utf-8"):
        caractere = chr(byte)
        if 32 <= byte < 127 and caractere not in '\\"?':
            partes.append(caractere)
        else:
            partes.append(f"\\{byte:03o}")
    return '"' + "".join(partes) + '"'


projeto = Path(env["PROJECT_DIR"])  # noqa: F821
dotenv = ler_dotenv(projeto / ".env")


def valor(nome: str) -> str:
    return os.environ.get(nome) or dotenv.get(nome, "")


valores = {nome: valor(nome) for nome in OBRIGATORIAS}
faltando = [nome for nome, v in valores.items() if not v]
if not valor("WIFI_SSID"):
    faltando.insert(0, "WIFI_SSID")
if not valor("WIFI_PASS"):
    faltando.insert(1 if "WIFI_SSID" in faltando else 0, "WIFI_PASS")
if faltando:
    falhar(
        "variáveis vazias ou ausentes: " + ", ".join(faltando) + "\n"
        "Defina-as no ambiente ou em firmware/.env (modelo: firmware/.env.example)."
    )

gerados = Path(env.subst("$BUILD_DIR")) / "generated"  # noqa: F821
gerados.mkdir(parents=True, exist_ok=True)
certificados: list[str] = []
redes: list[str] = []
sem_ca: list[str] = []
tem_eap = False

for numero in range(1, MAX_REDES + 1):
    prefixo = "WIFI_" if numero == 1 else f"WIFI{numero}_"
    ssid, senha = valor(prefixo + "SSID"), valor(prefixo + "PASS")
    if not ssid:
        if senha or valor(prefixo + "EAP_USER"):
            falhar(f"{prefixo}PASS ou {prefixo}EAP_USER definido sem {prefixo}SSID.")
        continue
    if not senha:
        falhar(f"{prefixo}SSID={ssid} sem {prefixo}PASS.")
    if len(ssid.encode("utf-8")) > 32:
        falhar(f"{prefixo}SSID passa de 32 bytes, o limite do Wi-Fi.")
    host = valor(f"WIFI{numero}_MQTT_HOST") if numero > 1 else ""
    usuario, identidade, metodo, ca = None, None, "WPA2_AUTH_PEAP", "nullptr"

    if valor(prefixo + "EAP_USER"):
        tem_eap = True
        usuario = valor(prefixo + "EAP_USER")
        nome_metodo = (valor(prefixo + "EAP_METHOD") or "PEAP").upper()
        if nome_metodo not in METODOS_EAP:
            falhar(f"{prefixo}EAP_METHOD={nome_metodo} não é suportado; use PEAP ou TTLS.")
        metodo = METODOS_EAP[nome_metodo]
        identidade = valor(prefixo + "EAP_IDENTITY") or usuario
        campos = {prefixo + "EAP_USER": usuario, prefixo + "EAP_IDENTITY": identidade, prefixo + "PASS": senha}
        longos = [nome for nome, v in campos.items() if len(v.encode("utf-8")) > LIMITE_EAP]
        if longos:
            falhar(", ".join(longos) + f" passa(m) de {LIMITE_EAP} bytes, o limite do Wi-Fi do ESP32.")

        arquivo_ca = valor(prefixo + "EAP_CA_FILE")
        if arquivo_ca:
            caminho = Path(arquivo_ca)
            caminho = caminho if caminho.is_absolute() else projeto / caminho
            if not caminho.is_file():
                falhar(f"{prefixo}EAP_CA_FILE aponta para {caminho}, que não existe.")
            pem = caminho.read_text(encoding="utf-8").strip()
            if "-----BEGIN CERTIFICATE-----" not in pem or ')PEM"' in pem:
                falhar(f"{caminho} não parece um certificado PEM.")
            # O PEM tem várias linhas e não cabe num -D; vai inteiro para o cabeçalho
            ca = f"kWifiCa{numero}"
            certificados.append(f'static const char {ca}[] = R"PEM({pem}\n)PEM";\n')
        else:
            sem_ca.append(ssid)
    elif len(senha) < 8:
        falhar(f"{prefixo}PASS tem menos de 8 caracteres, o mínimo do WPA2.")

    redes.append(
        f"    {{{literal_c(ssid)}, {literal_c(senha)}, {literal_c(usuario)}, {literal_c(identidade)}, "
        f"{metodo}, {ca}, {literal_c(host or None)}}},\n"
    )

if sem_ca:
    sys.stderr.write(
        "\nAviso: Wi-Fi institucional sem certificado (EAP_CA_FILE) em: " + ", ".join(sem_ca) + ".\n"
        "O sensor não confere o servidor da rede, e um ponto de acesso falso com o mesmo\n"
        "nome pode capturar a senha. Peça o certificado da autoridade (CA) à TI da instituição.\n\n"
    )

(gerados / "wifi_networks.h").write_text(
    "// Gerado por load_env.py a partir das variáveis WIFI_*; não edite\n"
    "#pragma once\n\n"
    + "".join(certificados)
    + ("\n" if certificados else "")
    + "static const WifiNetwork kWifiNetworks[] = {\n"
    + "".join(redes)
    + "};\n",
    encoding="utf-8",
)
env.Append(CPPDEFINES=["WIFI_NETWORKS_GENERATED"], CPPPATH=[str(gerados)])  # noqa: F821
if tem_eap:
    env.Append(CPPDEFINES=["WIFI_HAS_EAP"])  # noqa: F821

# String entre aspas escapadas, como o antigo -DMQTT_HOST=\"...\" do platformio.ini
env.Append(CPPDEFINES=[(nome, env.StringifyMacro(v)) for nome, v in valores.items()])  # noqa: F821
