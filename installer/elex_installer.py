"""Instalador do ELEX20 para Windows, macOS e Linux.

Separa o motor (este arquivo, só biblioteca padrão, para o .spec poder importá-lo no build) da
interface em tela cheia (elex_tui.py, com Textual). Sem terminal interativo, com --non-interactive
ou sem o Textual, ele usa perguntas e saída em texto simples.

O que ele faz, nesta ordem:
  1. coleta todas as respostas antes de mudar qualquer coisa;
  2. confere o Docker, prepara a pasta e grava o .env;
  3. sobe a stack com `docker compose up -d` e espera ficar de pé;
  4. baixa o modelo local do Ollama (opcional);
  5. cria as credenciais e ativa os workflows do n8n;
  6. grava o firmware/.env (opcional);
  7. coloca um modelo do Edge Impulse no firmware (opcional, só num checkout com firmware/).

Rodando como executável, ele copia os arquivos embutidos para a pasta escolhida.

Com --uninstall, remove os containers. Dados, imagens e arquivos só saem se o usuário pedir.
"""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess  # noqa: S404 (o instalador existe para chamar o docker)
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

NOMES_DE_SISTEMA = {"Darwin": "macOS"}
# Wi-Fi do sensor: até 4 redes (WIFI_ e WIFI2_ a WIFI4_), como em firmware/load_env.py
MAX_REDES_WIFI = 4
METODOS_EAP = ("PEAP", "TTLS")
LIMITE_EAP = 64  # bytes de usuário, identidade e senha aceitos pelo Wi-Fi do ESP32


def versao_do_git(pasta: Path) -> str | None:
    """Última tag de release do repositório, sem o v; None fora de um clone."""
    git = shutil.which("git")
    if git is None:
        return None
    r = subprocess.run(  # noqa: S603
        [git, "tag", "--list", "v[0-9]*", "--sort=-v:refname"],
        cwd=pasta, capture_output=True, text=True, check=False,
    )  # fmt: skip
    tags = r.stdout.split() if r.returncode == 0 else []
    return tags[0].removeprefix("v") if tags else None


def ler_versao() -> str:
    """Versão gravada pelo CI em version.txt; fora de um build de release, a última tag do Git."""
    congelado = getattr(sys, "frozen", False)
    pasta = Path(sys._MEIPASS) if congelado else Path(__file__).resolve().parent  # type: ignore[attr-defined]  # noqa: SLF001
    try:
        versao = (pasta / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        versao = ""
    if versao and not versao.endswith("-dev"):
        return versao
    return (None if congelado else versao_do_git(pasta)) or "dev"


VERSAO = ler_versao()


def titulo_do_instalador(versao: str | None = None, sistema: str | None = None) -> str:
    sistema = sistema or platform.system()
    return f"ELEX20 — installer {versao or VERSAO} ({NOMES_DE_SISTEMA.get(sistema, sistema)})"


# Segredos internos: o serviço secrets-init (init/secrets-init.sh) gera cada um sozinho na primeira
# subida e os guarda em volumes. nome do arquivo em /run/secrets/<nome>/value -> variável do .env que
# o sobrescreve (opcional). O instalador só os lê, nunca os gera.
SEGREDOS_AUTOMATICOS = {
    "grafana_ro": "GRAFANA_RO_PASSWORD",
    "n8n_db": "N8N_DB_PASSWORD",
    "hermes_ro": "HERMES_RO_PASSWORD",
    "mqtt_device": "MQTT_DEVICE_PASS",
    "mqtt_n8n": "MQTT_N8N_PASS",
    "hermes_webhook": "HERMES_WEBHOOK_SECRET",
    "n8n_command": "N8N_COMMAND_TOKEN",
}
# Logins que o usuário digita (Grafana e Hermes) ficam com os placeholders admin/password do compose.
# A senha do superusuário do banco é interna e vira aleatória numa instalação nova.
SENHAS_INTERNAS_DE_EXEMPLO = ("POSTGRES_PASSWORD",)

MODELO_OLLAMA = "qwen2.5:3b"
ARQUIVOS_DO_PROJETO = (
    "docker-compose.yaml",
    ".env.example",
    "grafana",
    "hermes/config.yaml",
    "hermes/mcp",
    "init",
    "mosquitto",
    "n8n",
    "timescaledb/init.sql",
    "timescaledb/db-init.sql",
    "timescaledb/db-init.sh",
)
EXTENSOES_DE_TEXTO = {".sh", ".sql", ".conf", ".yaml", ".yml", ".json", ".jsonc", ".alloy", ".py", ".example", ""}
WORKFLOWS_N8N = ("elex-ingestao-mqtt", "elex-comando-dispositivo")
URL_N8N = "http://127.0.0.1:5678"
URL_GRAFANA = "http://127.0.0.1:3000"
URL_HERMES = "http://127.0.0.1:9119"


# ── Funções puras (testadas em tests/test_installer.py) ──────────────────────


def gerar_segredo() -> str:
    return secrets.token_hex(24)


def ler_env(texto: str) -> dict[str, str]:
    """Lê um .env simples: CHAVE=valor, ignorando comentários e linhas vazias."""
    valores: dict[str, str] = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
            valor = valor[1:-1]
        valores[chave.strip()] = valor
    return valores


def formatar_valor_env(valor: str) -> str:
    """Põe aspas só quando o valor tem espaço, #, $ ou aspas (o compose interpreta esses caracteres)."""
    if "\n" in valor or "\r" in valor:
        raise ValueError("value with a line break")
    if not re.search(r"[\s#$'\"\\`]", valor):
        return valor
    if "'" not in valor:
        return f"'{valor}'"
    raise ValueError("values with a single quote and special characters are not supported")


def aplicar_env(modelo: str, valores: dict[str, str]) -> str:
    """Preenche o modelo (.env.example) preservando comentários e a ordem; chaves novas vão ao fim."""
    restantes = dict(valores)
    saida: list[str] = []
    for linha in modelo.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", linha)
        if m and m.group(1) in restantes:
            chave = m.group(1)
            saida.append(f"{chave}={formatar_valor_env(restantes.pop(chave))}")
        else:
            saida.append(linha)
    for chave, valor in restantes.items():
        saida.append(f"{chave}={formatar_valor_env(valor)}")
    return "\n".join(saida) + "\n"


def montar_valores(
    existente: dict[str, str],
    modelo: dict[str, str],
    sistema: str,
    ip_lan: str | None,
    extras: dict[str, str],
    banco_ja_existe: bool = False,
) -> dict[str, str]:
    """Decide o que gravar no .env. Nunca troca um valor que já existe (o banco guarda a senha antiga)."""
    novo_env = not existente and not banco_ja_existe
    valores: dict[str, str] = {}
    if novo_env:
        for chave in SENHAS_INTERNAS_DE_EXEMPLO:
            if modelo.get(chave) == "password":
                valores[chave] = gerar_segredo()
    # A coleta de logs (Alloy) só funciona no Docker do Linux
    if "COMPOSE_PROFILES" not in existente:
        valores["COMPOSE_PROFILES"] = "logs" if sistema == "Linux" else ""
    if ip_lan:
        valores["MQTT_BIND"] = ip_lan
    for chave, valor in extras.items():
        if valor:
            valores[chave] = valor
    return valores


def normalizar_texto(dados: bytes) -> bytes:
    """CRLF vira LF: shell scripts e configs montados em containers Linux quebram com \\r."""
    return dados.replace(b"\r\n", b"\n")


def detectar_distro(texto_os_release: str) -> tuple[str, list[str]]:
    info = ler_env(texto_os_release)
    return info.get("ID", "").lower(), info.get("ID_LIKE", "").lower().split()


def instrucoes_docker(sistema: str, distro: str = "", parecidas: list[str] | None = None) -> list[str]:
    """Texto de ajuda para instalar o Docker, por sistema e distribuição Linux."""
    familia = {distro, *(parecidas or [])}
    if sistema == "Windows":
        return [
            "Install Docker Desktop: https://www.docker.com/products/docker-desktop/",
            "During setup, keep the 'WSL 2' option checked. Restart the computer if asked.",
            "Open Docker Desktop, wait for the green icon and run this installer again.",
        ]
    if sistema == "Darwin":
        return [
            "Install Docker Desktop: https://www.docker.com/products/docker-desktop/",
            "Open Docker Desktop, wait for it to start and run this installer again.",
            "With Homebrew: brew install --cask docker",
        ]
    passos_pos = [
        "sudo systemctl enable --now docker",
        "sudo usermod -aG docker $USER   # then log out and back in",
    ]
    if familia & {"arch", "manjaro", "endeavouros", "cachyos"}:
        return ["sudo pacman -S docker docker-compose", *passos_pos]
    if familia & {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "suse", "sles"}:
        return ["sudo zypper install docker docker-compose", *passos_pos]
    if familia & {"fedora", "rhel", "centos", "rocky", "almalinux"}:
        return [
            "Official guide: https://docs.docker.com/engine/install/fedora/",
            "curl -fsSL https://get.docker.com | sudo sh   # official convenience script",
            *passos_pos,
        ]
    if familia & {"ubuntu", "debian", "linuxmint", "pop", "zorin", "elementary", "raspbian"}:
        return [
            "Official guide: https://docs.docker.com/engine/install/ubuntu/ (or /debian/)",
            "curl -fsSL https://get.docker.com | sudo sh   # official convenience script",
            *passos_pos,
        ]
    return ["Official guide: https://docs.docker.com/engine/install/", *passos_pos]


def credenciais_n8n(valores: dict[str, str]) -> list[dict]:
    """Credenciais que os workflows de n8n/workflows/ referenciam (ids fixos: reimportar atualiza)."""
    return [
        {
            "id": "elex-mqtt",
            "name": "Mosquitto (usuário n8n)",
            "type": "mqtt",
            "data": {
                "protocol": "mqtt",
                "host": "mosquitto",
                "port": 1883,
                "username": "n8n",
                "password": valores["MQTT_N8N_PASS"],
                "clean": True,
                "clientId": "",
                "ssl": False,
                "passwordless": False,
            },
        },
        {
            "id": "elex-postgres",
            "name": "TimescaleDB (n8n_app)",
            "type": "postgres",
            "data": {
                "host": "timescaledb",
                "database": valores.get("POSTGRES_DB", "grafana"),
                "user": "n8n_app",
                "password": valores["N8N_DB_PASSWORD"],
                "port": 5432,
                "maxConnections": 100,
                "allowUnauthorizedCerts": False,
                "ssl": "disable",
                "sshTunnel": False,
            },
        },
    ]


def descrever_senha(valor: str | None) -> str:
    """Texto do resumo final: senha real nunca vai para o terminal, só o placeholder conhecido."""
    if valor in (None, "", "password"):
        return "password (change it)"
    return "set in .env"


def nome_do_projeto(pasta: Path) -> str:
    return re.sub(r"[^a-z0-9_-]", "", pasta.name.lower())


def detectar_ip_lan() -> str | None:
    """IP do computador na rede local (sem enviar nada: o UDP só escolhe a interface de saída)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


# ── Validação das respostas (usada pelas duas interfaces) ────────────────────


def validar_ip(valor: str) -> str | None:
    try:
        ip = ipaddress.ip_address(valor.strip())
    except ValueError:
        return "Enter a valid IP address, such as 192.168.0.10."
    if ip.is_unspecified or ip.is_loopback:
        return "Use this computer's address on your network, not 0.0.0.0 or 127.0.0.1."
    return None


def validar_ssid(valor: str) -> str | None:
    texto = valor.strip()
    if not texto:
        return "Enter the name of your Wi-Fi network."
    if len(texto.encode("utf-8")) > 32:
        return "A Wi-Fi network name has at most 32 bytes."
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", texto):
        return "This looks like an IP address. Enter the network name shown on your phone or computer."
    return None


def validar_senha_wifi(valor: str, institucional: bool = False) -> str | None:
    if institucional:
        if not valor:
            return "Enter the password of your institutional account."
        if len(valor.encode("utf-8")) > LIMITE_EAP:
            return f"The ESP32 accepts passwords of up to {LIMITE_EAP} bytes."
        return None
    if not 8 <= len(valor) <= 63:
        return "A Wi-Fi password has 8 to 63 characters."
    return None


def validar_usuario_eap(valor: str) -> str | None:
    if not valor.strip():
        return "Enter your full username, such as student@university.edu."
    if len(valor.strip().encode("utf-8")) > LIMITE_EAP:
        return f"The ESP32 accepts usernames of up to {LIMITE_EAP} bytes."
    return None


def validar_identidade_eap(valor: str) -> str | None:
    if len(valor.strip().encode("utf-8")) > LIMITE_EAP:
        return f"The ESP32 accepts identities of up to {LIMITE_EAP} bytes."
    return None


def validar_metodo_eap(valor: str) -> str | None:
    if valor.strip() and valor.strip().upper() not in METODOS_EAP:
        return "Use PEAP or TTLS; your IT team can tell you which."
    return None


def validar_certificado(valor: str) -> str | None:
    """Certificado da autoridade (CA) da rede institucional, em PEM; vazio é aceito."""
    if not valor.strip():
        return None
    caminho = Path(valor.strip()).expanduser()
    if not caminho.is_file():
        return f"File not found: {caminho}"
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "Could not read this file; use the certificate in PEM format (.pem or .crt)."
    if "-----BEGIN CERTIFICATE-----" not in texto:
        return "This is not a PEM certificate (it should start with -----BEGIN CERTIFICATE-----)."
    return None


def validar_ids(valor: str) -> str | None:
    """IDs numéricos separados por vírgula (ID de grupo no Telegram é negativo)."""
    if not re.fullmatch(r"\s*-?\d+\s*(,\s*-?\d+\s*)*", valor):
        return "Enter a numeric ID. Separate several IDs with commas."
    return None


def validar_obrigatorio(valor: str) -> str | None:
    return None if valor.strip() else "This field is required."


def validar_pasta(texto: str) -> str | None:
    if not texto.strip():
        return "Choose a folder."
    pasta = Path(texto.strip()).expanduser()
    if pasta.exists() and not pasta.is_dir():
        return "This path is a file, not a folder."
    existente = next((p for p in (pasta, *pasta.parents) if p.exists()), None)
    if existente is None or not os.access(existente, os.W_OK):
        return "You do not have permission to write to this folder."
    return None


# ── Modelo do Edge Impulse no firmware ──────────────────────────────────────

PASTA_MODELO_EI = Path("firmware") / "lib" / "ei-model"
# Onde o nome da biblioteca do modelo aparece (ambiente esp32s3_model e include para o LDF)
ARQUIVOS_COM_O_MODELO_EI = (Path("firmware") / "platformio.ini", Path("firmware") / "src" / "main.cpp")
NOME_DO_MODELO_EI = re.compile(r"\b[A-Za-z0-9_]+_inferencing\b")


def achar_biblioteca_ei(arquivos: list[str]) -> tuple[str, str] | None:
    """Raiz e nome da biblioteca exportada (Deployment → Arduino library), a partir dos caminhos.

    A raiz tem library.properties e src/<nome>_inferencing.h; ela pode ser a própria pasta ou
    a primeira subpasta do .zip.
    """
    conjunto = set(arquivos)
    for arquivo in sorted(arquivos, key=len):
        achado = re.fullmatch(r"((?:[^/]+/)?)src/([A-Za-z0-9_]+_inferencing)\.h", arquivo)
        if achado and f"{achado.group(1)}library.properties" in conjunto:
            return achado.group(1), achado.group(2)
    return None


def listar_modelo_ei(caminho: Path) -> list[str]:
    if caminho.is_dir():
        return [p.relative_to(caminho).as_posix() for p in caminho.rglob("*") if p.is_file()]
    with zipfile.ZipFile(caminho) as arquivo:
        return [nome for nome in arquivo.namelist() if not nome.endswith("/")]


def validar_modelo_ei(texto: str) -> str | None:
    if not texto.strip():
        return "Choose the .zip or folder exported from Edge Impulse."
    caminho = Path(texto.strip()).expanduser()
    if not caminho.exists():
        return "This file or folder does not exist."
    if caminho.is_file() and not zipfile.is_zipfile(caminho):
        return "Choose the .zip from Deployment → Arduino library, or its extracted folder."
    try:
        achado = achar_biblioteca_ei(listar_modelo_ei(caminho))
    except (OSError, zipfile.BadZipFile):
        return "Could not read this file."
    if achado is None:
        return "This is not an Edge Impulse Arduino library (no library.properties and src/*_inferencing.h)."
    return None


def rotulos_do_modelo_ei(texto_model_variables: str) -> list[str]:
    """Rótulos do modelo, lidos de src/model-parameters/model_variables.h."""
    achado = re.search(r"inferencing_categories\w*\[\]\s*=\s*\{(.*?)\}", texto_model_variables, re.S)
    return re.findall(r'"([^"]*)"', achado.group(1)) if achado else []


def rotulos_desconhecidos(rotulos: list[str], categorias: list[dict]) -> list[str]:
    """Rótulos sem urgência no ELEX20: nem o nome em inglês nem o legado em português."""
    conhecidos = {c["rotulo"] for c in categorias} | {c.get("rotulo_legado", c["rotulo"]) for c in categorias}
    return [r for r in rotulos if r not in conhecidos]


def trocar_nome_do_modelo_ei(texto: str, nome: str) -> str:
    return NOME_DO_MODELO_EI.sub(nome, texto)


def mascarar(valor: str, atual: str | None = None) -> str:
    """Texto da revisão: um segredo nunca aparece na tela."""
    if valor:
        return "•••••• (new)"
    return "•••••• (unchanged)" if atual else "not set"


# ── Respostas e resumo ───────────────────────────────────────────────────────


@dataclass
class RedeWifi:
    """Uma rede Wi-Fi do sensor; ele tenta cada uma até conectar."""

    ssid: str
    senha: str = ""  # vazia: mantém a senha que já está no firmware/.env para este SSID
    # Wi-Fi institucional (WPA2-Enterprise, como o eduroam): usuário preenchido
    eap_usuario: str = ""
    eap_identidade: str = ""
    eap_metodo: str = ""
    ca: str = ""  # certificado (PEM); fora de firmware/, é copiado para lá
    mqtt_host: str = ""  # só nas redes extras: o servidor visto dessa rede

    @property
    def institucional(self) -> bool:
        return bool(self.eap_usuario)


@dataclass
class Firmware:
    redes: list[RedeWifi]  # a primeira vira WIFI_*, as outras WIFI2_ a WIFI4_
    host: str

    @property
    def ssid(self) -> str:
        return self.redes[0].ssid


def prefixo_wifi(numero: int) -> str:
    return "WIFI_" if numero == 1 else f"WIFI{numero}_"


def redes_do_env(env: dict[str, str]) -> list[RedeWifi]:
    """Redes configuradas num firmware/.env, na ordem de tentativa."""
    redes = []
    for numero in range(1, MAX_REDES_WIFI + 1):
        p = prefixo_wifi(numero)
        if not env.get(p + "SSID"):
            continue
        redes.append(
            RedeWifi(
                ssid=env[p + "SSID"],
                senha=env.get(p + "PASS", ""),
                eap_usuario=env.get(p + "EAP_USER", ""),
                eap_identidade=env.get(p + "EAP_IDENTITY", ""),
                eap_metodo=env.get(p + "EAP_METHOD", ""),
                ca=env.get(p + "EAP_CA_FILE", ""),
                mqtt_host=env.get(f"WIFI{numero}_MQTT_HOST", "") if numero > 1 else "",
            )
        )
    return redes


def env_das_redes(redes: list[RedeWifi]) -> str:
    """Linhas WIFI_* do firmware/.env; campos vazios ficam de fora."""
    linhas = []
    for numero, rede in enumerate(redes[:MAX_REDES_WIFI], start=1):
        p = prefixo_wifi(numero)
        campos = [("SSID", rede.ssid), ("PASS", rede.senha)]
        if rede.institucional:
            campos += [
                ("EAP_USER", rede.eap_usuario),
                ("EAP_IDENTITY", rede.eap_identidade),
                ("EAP_METHOD", rede.eap_metodo.upper()),
                ("EAP_CA_FILE", rede.ca),
            ]
        if numero > 1:
            campos.append(("MQTT_HOST", rede.mqtt_host))
        linhas += [f"{p}{chave}={valor}" for chave, valor in campos if valor]
    return "".join(linha + "\n" for linha in linhas)


@dataclass
class Respostas:
    """Tudo o que o usuário decide, coletado antes da instalação começar."""

    destino: Path
    ip_lan: str | None = None
    extras: dict[str, str] = field(default_factory=dict)
    baixar_modelo: bool = True
    firmware: Firmware | None = None
    # .zip ou pasta exportada do Edge Impulse (Deployment → Arduino library)
    modelo_ei: Path | None = None


@dataclass
class Remocao:
    """O que a desinstalação apaga além dos containers; nada disso é o padrão."""

    dados: bool = False
    imagens: bool = False
    arquivos: bool = False

    @property
    def exige_confirmacao(self) -> bool:
        return self.dados or self.arquivos


def dados_do_resumo(valores: dict[str, str], destino: Path) -> dict:
    """Conteúdo do resumo final; senhas reais nunca entram aqui."""
    return {
        "title": "ELEX20 installed",
        "folder": str(destino),
        "services": [
            (
                "Grafana",
                URL_GRAFANA,
                valores.get("GRAFANA_ADMIN_USER", "admin"),
                descrever_senha(valores.get("GRAFANA_ADMIN_PASSWORD")),
            ),
            (
                "Hermes",
                URL_HERMES,
                valores.get("HERMES_DASHBOARD_USER", "admin"),
                descrever_senha(valores.get("HERMES_DASHBOARD_PASS")),
            ),
            ("n8n", URL_N8N, "create on first visit", "create on first visit"),
        ],
        "device": [
            ("MQTT_HOST", valores.get("MQTT_BIND", "127.0.0.1")),
            ("MQTT_USER", "device"),
            ("MQTT_PASS", "docker compose exec mosquitto cat /run/secrets/mqtt_device/value"),
        ],
        "notes": [
            "Change the admin/password logins in .env and in each service.",
            "Internal passwords were generated automatically and stay in Docker volumes.",
            "Keep the .env file safe and do not share it.",
            "Stop: docker compose stop   Start again: docker compose start",
        ],
    }


# ── Saída em texto simples ───────────────────────────────────────────────────


class Saida:
    """Saída em texto; a interface em tela cheia a substitui pela dela."""

    def etapa(self, chave: str, texto: str) -> None:  # noqa: ARG002
        print(f"\n== {texto}")

    def concluir_etapa(self, chave: str, ok: bool = True) -> None:
        pass

    def info(self, texto: str) -> None:
        print(f"   {texto}")

    def aviso(self, texto: str) -> None:
        print(f"   [WARNING] {texto}")

    def erro(self, texto: str) -> None:
        print(f"\n[ERROR] {texto}", file=sys.stderr)

    def detalhe(self, texto: str) -> None:
        print(f"   {texto}")


def imprimir_resumo(dados: dict) -> None:
    linha = "=" * 64
    print(f"\n{linha}\n {dados['title']}\n{linha}\n Folder: {dados['folder']}")
    if dados["services"]:
        print("\n Services")
    for nome, url, usuario, senha in dados["services"]:
        print(f"   {nome:<8} {url:<24} user: {usuario}  password: {senha}")
    if dados["device"]:
        print("\n Device settings")
    for chave, valor in dados["device"]:
        print(f"   {chave:<10} {valor}")
    print("\n Notes")
    for nota in dados["notes"]:
        print(f"   - {nota}")


# ── Motor ────────────────────────────────────────────────────────────────────


def checar_docker() -> tuple[bool, str]:
    """Confere o Docker sem mudar nada; devolve (ok, mensagem)."""
    if shutil.which("docker") is None:
        return False, "Docker is not installed."
    versao = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if versao.returncode != 0:
        return False, "Docker is installed, but the Compose v2 plugin is missing."
    info = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if info.returncode != 0:
        saida = (info.stderr or "") + (info.stdout or "")
        if "permission denied" in saida.lower():
            return False, "No permission to use Docker. On Linux: sudo usermod -aG docker $USER, then log in again."
        return False, "Docker is not running. Open Docker Desktop or run: sudo systemctl start docker"
    return True, "Docker and Compose are working."


def como_instalar_docker() -> list[str]:
    sistema = platform.system()
    distro, parecidas = "", []
    if sistema == "Linux":
        try:
            distro, parecidas = detectar_distro(Path("/etc/os-release").read_text(encoding="utf-8"))
        except OSError:
            pass
    return instrucoes_docker(sistema, distro, parecidas)


def pilha_em_outra_pasta(destino: Path) -> str | None:
    """Pasta de outra instalação: os nomes dos containers são fixos, então só cabe uma na máquina."""
    docker = shutil.which("docker")
    if docker is None:
        return None
    r = subprocess.run(  # noqa: S603
        [docker, "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', "timescaledb"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    pasta = r.stdout.strip()
    if r.returncode != 0 or not pasta or pasta == "<no value>":
        return None
    return None if Path(pasta).resolve() == destino.resolve() else pasta


def pasta_da_pilha() -> Path | None:
    """Pasta da instalação em uso, lida do container do banco."""
    pasta = pilha_em_outra_pasta(Path("/nonexistent-elex20"))
    return Path(pasta) if pasta else None


def instalacao_valida(pasta: Path) -> bool:
    """Evita tratar como ELEX20 uma pasta qualquer: a desinstalação apaga arquivos nela."""
    return (pasta / "docker-compose.yaml").is_file() and (pasta / "timescaledb" / "db-init.sql").is_file()


def e_repositorio(pasta: Path) -> bool:
    return (pasta / ".git").exists()


def remover_arquivos(pasta: Path, saida: Saida, manter_env: bool = False) -> None:
    """Apaga só o que o instalador criou. Em um clone, os arquivos do projeto ficam.

    Nunca apaga a pasta inteira de uma vez: ela foi escolhida pelo usuário e pode ter outras coisas.
    """
    alvos = ["firmware/.env"] if e_repositorio(pasta) else list(ARQUIVOS_DO_PROJETO)
    if not manter_env:
        alvos.append(".env")
    raiz = pasta.resolve()
    for relativo in alvos:
        alvo = pasta / relativo
        if alvo.is_symlink():
            alvo.unlink()
        elif not alvo.resolve().is_relative_to(raiz):
            continue
        elif alvo.is_dir():
            shutil.rmtree(alvo)
        elif alvo.exists():
            alvo.unlink()
    if e_repositorio(pasta):
        saida.info("Deleted the configuration. The repository files stay in place.")
        return
    # Pastas que ficaram vazias, das mais fundas para a raiz
    for sub in sorted((p for p in pasta.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if sub.is_symlink() or any(sub.iterdir()):
            continue
        sub.rmdir()
    if any(pasta.iterdir()):
        saida.aviso(f"Other files remain in {pasta}; they were not created by the installer.")
    else:
        pasta.rmdir()
        saida.info(f"Deleted {pasta}.")


def resumo_da_remocao(pasta: Path, remocao: Remocao) -> dict:
    notas = ["Containers and the network were removed."]
    notas.append("All data was deleted." if remocao.dados else "Your data stays in Docker volumes.")
    notas.append("Docker images were deleted." if remocao.imagens else "Docker images stay on this computer.")
    if remocao.arquivos and not remocao.dados:
        notas.append("The .env was kept because your data needs it. Keep it to use that data again.")
    if not remocao.arquivos:
        notas.append("Files and the .env stay in the folder. Run the installer there to set ELEX20 up again.")
    if e_repositorio(pasta):
        notas.append("The repository was kept. Delete the folder yourself if you no longer need it.")
    return {"title": "ELEX20 uninstalled", "folder": str(pasta), "services": [], "device": [], "notes": notas}


class Instalador:
    def __init__(self, raiz_origem: Path, respostas: Respostas, dry_run: bool, saida: Saida | None = None):
        self.origem = raiz_origem
        self.respostas = respostas
        self.destino = respostas.destino
        self.dry_run = dry_run
        self.saida = saida or Saida()
        self.sistema = platform.system()
        self.processo: subprocess.Popen | None = None
        self.resumo: dict | None = None

    def etapas(self) -> list[tuple[str, str]]:
        etapas = [
            ("docker", "Check Docker"),
            ("files", "Prepare files"),
            ("env", "Write configuration"),
            ("stack", "Start services"),
        ]
        if self.respostas.baixar_modelo:
            etapas.append(("model", "Download AI model"))
        etapas.append(("n8n", "Configure n8n"))
        if self.respostas.firmware:
            etapas.append(("firmware", "Write device configuration"))
        if self.respostas.modelo_ei:
            etapas.append(("ei-model", "Add the sound model to the firmware"))
        return etapas

    def etapas_da_remocao(self, remocao: Remocao) -> list[tuple[str, str]]:
        etapas = [("docker", "Check Docker"), ("stack", "Remove services")]
        if remocao.dados:
            etapas.append(("data", "Delete Hermes data"))
        if remocao.arquivos:
            etapas.append(("files", "Delete files"))
        return etapas

    # comandos
    def docker(self, *args: str, capturar: bool = False, check: bool = True):
        cmd = ["docker", *args]
        if self.dry_run:
            self.saida.info("(dry run) " + " ".join(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if capturar:
            return subprocess.run(cmd, cwd=self.destino, check=check, text=True, capture_output=True)  # noqa: S603
        self.processo = subprocess.Popen(  # noqa: S603
            cmd, cwd=self.destino, text=True, errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        for linha in self.processo.stdout:  # type: ignore[union-attr]
            self.saida.detalhe(linha.rstrip())
        codigo = self.processo.wait()
        if check and codigo != 0:
            raise subprocess.CalledProcessError(codigo, cmd)
        return subprocess.CompletedProcess(cmd, codigo, "", "")

    def compose(self, *args: str, **kw):
        return self.docker("compose", *args, **kw)

    def cancelar(self) -> None:
        if self.processo and self.processo.poll() is None:
            self.processo.terminate()

    # ── etapas ───────────────────────────────────────────────────────────────

    def verificar_docker(self) -> bool:
        if self.dry_run:
            self.saida.info("(dry run) Docker check skipped")
            return True
        ok, mensagem = checar_docker()
        if not ok:
            self.saida.erro(mensagem)
            if shutil.which("docker") is None or "Compose" in mensagem:
                self.saida.info("How to install Docker on this computer:")
                for linha in como_instalar_docker():
                    self.saida.info(linha)
            return False
        outra = pilha_em_outra_pasta(self.destino)
        if outra:
            self.saida.erro(f"ELEX20 is already installed in {outra}. Run the installer on that folder.")
            return False
        self.saida.info(mensagem)
        return True

    def preparar_pasta(self) -> None:
        self.destino.mkdir(parents=True, exist_ok=True)
        if self.origem.resolve() != self.destino.resolve():
            self.saida.info(f"Copying files to {self.destino}")
            copiar_projeto(self.origem, self.destino)
        else:
            self.saida.info(f"Using the repository folder: {self.destino}")

    def senha_padrao_do_banco_funciona(self) -> bool:
        """True se o banco já em execução aceita a senha padrão (stack subida sem .env)."""
        if self.dry_run:
            return False
        r = self.compose(
            "exec", "-T", "-e", "PGPASSWORD=password", "timescaledb",
            "psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "grafana", "-tAc", "select 1",
            capturar=True, check=False,
        )  # fmt: skip
        return r.returncode == 0 and r.stdout.strip() == "1"

    def volumes_antigos(self) -> bool:
        if self.dry_run:
            return False
        r = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True, check=False)  # noqa: S603, S607
        prefixo = nome_do_projeto(self.destino) + "_"
        return any(v.startswith(prefixo) and v.endswith("timescaledb_data") for v in r.stdout.split())

    def configurar_env(self) -> dict[str, str] | None:
        arquivo = self.destino / ".env"
        modelo_texto = (self.destino / ".env.example").read_text(encoding="utf-8")
        existente = ler_env(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}

        banco_ja_existe = False
        if not existente and self.volumes_antigos():
            if self.senha_padrao_do_banco_funciona():
                self.saida.info("The stack already uses the default passwords (no .env); they will be kept.")
                banco_ja_existe = True
            else:
                self.saida.erro(
                    "Data from a previous installation exists, but there is no .env file.\n"
                    "A new .env would have different passwords and the old database would not open.\n"
                    "Restore the old .env, or delete the old data on purpose (docker compose down -v)."
                )
                return None

        modelo = ler_env(modelo_texto)
        novos = montar_valores(
            existente, modelo, self.sistema, self.respostas.ip_lan, self.respostas.extras, banco_ja_existe
        )
        novos = {chave: valor for chave, valor in novos.items() if existente.get(chave) != valor}
        if existente and not novos:
            self.saida.info("The .env file is already complete; nothing changed.")
        else:
            texto_base = arquivo.read_text(encoding="utf-8") if existente else modelo_texto
            arquivo.write_text(aplicar_env(texto_base, novos), encoding="utf-8")
            if os.name == "posix":
                arquivo.chmod(0o600)
            self.saida.info(f".env {'updated' if existente else 'created'} with {len(novos)} new value(s).")
        return {**modelo, **existente, **novos}

    def subir_stack(self) -> bool:
        self.saida.info("The first run downloads a few GB and can take several minutes.")
        try:
            self.compose("up", "-d")
        except subprocess.CalledProcessError:
            self.saida.erro("docker compose failed. Check the output above (port in use? low disk space?).")
            return False
        if self.dry_run:
            return True
        self.saida.info("Waiting for n8n and Grafana to be ready...")
        pendentes = {"n8n": f"{URL_N8N}/healthz", "Grafana": f"{URL_GRAFANA}/api/health"}
        limite = time.monotonic() + 600
        while pendentes and time.monotonic() < limite:
            for nome, url in list(pendentes.items()):
                if esperar_http(url):
                    self.saida.info(f"{nome} is ready.")
                    del pendentes[nome]
            if pendentes:
                time.sleep(5)
        if pendentes:
            self.saida.erro(
                f"No response in time: {', '.join(pendentes)}. "
                f"See: docker compose logs {' '.join(n.lower() for n in pendentes)}"
            )
            return False
        return True

    def baixar_modelo(self) -> bool:
        self.saida.info(f"Downloading {MODELO_OLLAMA}; this can take a while...")
        try:
            self.compose("exec", "-T", "ollama", "ollama", "pull", MODELO_OLLAMA)
        except subprocess.CalledProcessError:
            self.saida.aviso(f"Download failed. Try later: docker compose exec ollama ollama pull {MODELO_OLLAMA}")
            return False
        return True

    def ler_segredo(self, servico: str, nome: str) -> str:
        """Lê um segredo gerado pela stack, de dentro do container que o monta."""
        if self.dry_run:
            return f"<{nome}>"
        r = self.compose("exec", "-T", servico, "cat", f"/run/secrets/{nome}/value", capturar=True)
        return r.stdout.strip()

    def provisionar_n8n(self, valores: dict[str, str]) -> bool:
        n8n = ("exec", "-T", "n8n", "n8n")
        with tempfile.NamedTemporaryFile(prefix="elex-cred-", suffix=".json", dir=self.destino, delete=False) as tmp:
            arquivo = Path(tmp.name)
        try:
            if os.name == "posix":
                arquivo.chmod(0o600)
            segredos = {
                "MQTT_N8N_PASS": self.ler_segredo("n8n", "mqtt_n8n"),
                "N8N_DB_PASSWORD": self.ler_segredo("n8n", "n8n_db"),
                "POSTGRES_DB": valores.get("POSTGRES_DB", "grafana"),
            }
            arquivo.write_text(json.dumps(credenciais_n8n(segredos)), encoding="utf-8")
            self.compose("cp", str(arquivo), "n8n:/tmp/elex-cred.json", capturar=True)
            try:
                self.compose(*n8n, "import:credentials", "--input=/tmp/elex-cred.json", capturar=True)
            finally:
                self.compose("exec", "-T", "n8n", "rm", "-f", "/tmp/elex-cred.json", check=False, capturar=True)  # noqa: S108 (caminho no container)
            self.compose(*n8n, "import:workflow", "--separate", "--input=/workflows", capturar=True)
            for wid in WORKFLOWS_N8N:
                # O n8n 2.x não tenta de novo um gatilho que falhou ao ativar (ex.: broker fora
                # do ar), e publicar a mesma versão não muda nada. Despublicar antes zera esse
                # estado; numa instalação nova não há o que despublicar, então o erro é ignorado.
                self.compose(*n8n, "unpublish:workflow", f"--id={wid}", check=False, capturar=True)
                self.compose(*n8n, "publish:workflow", f"--id={wid}", capturar=True)
            self.compose("restart", "n8n", capturar=True)
        except subprocess.CalledProcessError as exc:
            self.saida.erro(f"n8n setup failed: {(exc.stderr or exc.stdout or exc)}")
            return False
        finally:
            arquivo.unlink(missing_ok=True)
        self.saida.info("Credentials created and workflows activated.")
        return True

    def gerar_env_firmware(self) -> None:
        dados = self.respostas.firmware
        arquivo = self.destino / "firmware" / ".env"
        atual = ler_env(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
        senhas = {rede.ssid: rede.senha for rede in redes_do_env(atual)}
        redes = []
        for numero, rede in enumerate(dados.redes[:MAX_REDES_WIFI], start=1):
            # Senha em branco mantém a que já estava gravada para a mesma rede
            senha = rede.senha or senhas.get(rede.ssid, "")
            redes.append(replace(rede, senha=senha, ca=self.instalar_certificado(rede.ca, numero)))
        texto = env_das_redes(redes) + (
            f"MQTT_HOST={dados.host}\nMQTT_USER=device\nMQTT_PASS={self.senha_mqtt_do_dispositivo(atual)}\n"
        )
        arquivo.write_text(texto, encoding="utf-8")
        if os.name == "posix":
            arquivo.chmod(0o600)
        nomes = ", ".join(rede.ssid for rede in redes)
        self.saida.info(f"firmware/.env written with {len(redes)} Wi-Fi network(s): {nomes}.")

    def senha_mqtt_do_dispositivo(self, atual: dict[str, str]) -> str:
        """Senha do usuário device; sem a stack no ar, fica a que já estava no arquivo."""
        try:
            return self.ler_segredo("mosquitto", "mqtt_device") or atual.get("MQTT_PASS", "")
        except (subprocess.CalledProcessError, OSError):
            if not atual.get("MQTT_PASS"):
                self.saida.aviso("Could not read the MQTT password: is the stack running? Fill MQTT_PASS by hand.")
            return atual.get("MQTT_PASS", "")

    def instalar_certificado(self, caminho: str, numero: int) -> str:
        """Copia o certificado da rede para firmware/ (onde *.pem não é versionado)."""
        if not caminho:
            return ""
        firmware = (self.destino / "firmware").resolve()
        origem = Path(caminho).expanduser()
        if not origem.is_absolute():
            return caminho  # já relativo a firmware/, como o load_env.py espera
        origem = origem.resolve()
        if origem.is_relative_to(firmware):
            return origem.relative_to(firmware).as_posix()
        nome = f"wifi-ca-{numero}.pem"
        shutil.copyfile(origem, firmware / nome)
        return nome

    def incluir_modelo_ei(self) -> bool:
        """Copia a biblioteca do Edge Impulse para firmware/lib/ei-model e aponta o build para ela."""
        origem = self.respostas.modelo_ei
        firmware = self.destino / "firmware"
        if not (firmware / "platformio.ini").is_file():
            self.saida.erro("No firmware folder here: the model goes into a copy of the repository.")
            return False
        try:
            raiz, nome = achar_biblioteca_ei(listar_modelo_ei(origem)) or (None, None)
        except (OSError, zipfile.BadZipFile) as erro:
            self.saida.erro(f"Could not read the model: {erro}")
            return False
        if nome is None:
            self.saida.erro("This is not an Edge Impulse Arduino library.")
            return False
        pasta_modelos = self.destino / PASTA_MODELO_EI
        pasta_modelos.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=pasta_modelos.parent) as temporaria:
            nova = Path(temporaria) / nome
            if origem.is_dir():
                shutil.copytree(origem / raiz, nova)
            else:
                with zipfile.ZipFile(origem) as arquivo:
                    for membro in arquivo.infolist():
                        if membro.is_dir() or not membro.filename.startswith(raiz):
                            continue
                        alvo = (nova / membro.filename[len(raiz) :]).resolve()
                        if not alvo.is_relative_to(nova.resolve()):
                            self.saida.erro(f"Unsafe path in the .zip: {membro.filename}")
                            return False
                        alvo.parent.mkdir(parents=True, exist_ok=True)
                        with arquivo.open(membro) as entrada, alvo.open("wb") as saida:
                            shutil.copyfileobj(entrada, saida)
            metadados = nova / "src" / "model-parameters" / "model_metadata.h"
            frequencia = (
                re.search(r"EI_CLASSIFIER_FREQUENCY\s+(\d+)", metadados.read_text(encoding="utf-8"))
                if metadados.is_file()
                else None
            )
            if frequencia and int(frequencia.group(1)) != 16000:
                self.saida.erro(f"The model expects {frequencia.group(1)} Hz audio; ELEX20 records at 16000 Hz.")
                return False
            # Só um modelo por vez: o build usa o que estiver aqui
            for antiga in pasta_modelos.iterdir():
                if antiga.is_dir():
                    shutil.rmtree(antiga)
                else:
                    antiga.unlink()
            shutil.move(str(nova), str(pasta_modelos / nome))
        for relativo in ARQUIVOS_COM_O_MODELO_EI:
            arquivo = self.destino / relativo
            if not arquivo.is_file():
                continue
            texto = arquivo.read_text(encoding="utf-8")
            novo = trocar_nome_do_modelo_ei(texto, nome)
            if novo != texto:
                arquivo.write_text(novo, encoding="utf-8")
        self.saida.info(f"Model {nome} added to firmware/lib/ei-model.")
        self.avisar_rotulos_do_modelo(pasta_modelos / nome)
        self.saida.info("Flash it with: cd firmware && pio run -e esp32s3_model -t upload")
        return True

    def avisar_rotulos_do_modelo(self, biblioteca: Path) -> None:
        variaveis = biblioteca / "src" / "model-parameters" / "model_variables.h"
        lista = self.destino / "classes" / "sound_classes.json"
        if not variaveis.is_file() or not lista.is_file():
            return
        rotulos = rotulos_do_modelo_ei(variaveis.read_text(encoding="utf-8"))
        categorias = json.loads(lista.read_text(encoding="utf-8"))["categorias"]
        self.saida.detalhe(f"Model labels: {', '.join(rotulos) or 'none found'}")
        desconhecidos = rotulos_desconhecidos(rotulos, categorias)
        if desconhecidos:
            self.saida.aviso(
                f"Labels unknown to ELEX20: {', '.join(desconhecidos)}. They are saved without urgency, "
                "so they never vibrate or alert. See classes/sound_classes.json."
            )

    def remover_stack(self, remocao: Remocao) -> bool:
        args = ["down", "--remove-orphans"]
        if remocao.dados:
            args.append("--volumes")
        if remocao.imagens:
            args += ["--rmi", "all"]
        try:
            self.compose(*args)
        except subprocess.CalledProcessError:
            self.saida.erro("docker compose failed. Check the output above.")
            return False
        return True

    def remover_dados_do_hermes(self) -> bool:
        """hermes_data é uma pasta montada, não um volume: o `down --volumes` não a alcança."""
        pasta = self.destino / "hermes_data"
        if self.dry_run:
            self.saida.info(f"(dry run) would delete {pasta}")
            return True
        shutil.rmtree(pasta, ignore_errors=True)
        if pasta.exists():
            self.saida.aviso(f"Could not delete everything. Run: sudo rm -rf {pasta}")
        return True

    def remover_pasta(self, manter_env: bool = False) -> bool:
        if self.dry_run:
            self.saida.info(f"(dry run) would delete the installed files in {self.destino}")
            return True
        remover_arquivos(self.destino, self.saida, manter_env)
        return True

    def desinstalar(self, remocao: Remocao) -> int:
        titulos = dict(self.etapas_da_remocao(remocao))

        def etapa(chave: str, funcao, *args) -> bool:
            self.saida.etapa(chave, titulos[chave])
            ok = funcao(*args)
            self.saida.concluir_etapa(chave, ok)
            return ok

        if not instalacao_valida(self.destino):
            self.saida.erro(f"No ELEX20 installation found in {self.destino}.")
            return 1
        if not etapa("docker", self.verificar_docker):
            return 1
        if not etapa("stack", self.remover_stack, remocao):
            return 1
        if remocao.dados:
            etapa("data", self.remover_dados_do_hermes)
        if remocao.arquivos:
            # Sem o .env, os dados guardados ficariam inacessíveis: a senha do banco está nele
            etapa("files", self.remover_pasta, not remocao.dados)
        self.resumo = resumo_da_remocao(self.destino, remocao)
        return 0

    def _etapa(self, chave: str, funcao, *args):
        """Roda uma etapa e marca o resultado; False e None contam como falha."""
        self.saida.etapa(chave, dict(self.etapas())[chave])
        resultado = funcao(*args)
        self.saida.concluir_etapa(chave, resultado not in (False, None) or funcao == self.gerar_env_firmware)
        return resultado

    def executar(self) -> int:
        if not self._etapa("docker", self.verificar_docker):
            return 1
        self.saida.etapa("files", "Prepare files")
        self.preparar_pasta()
        self.saida.concluir_etapa("files")
        valores = self._etapa("env", self.configurar_env)
        if valores is None:
            return 1
        if not self._etapa("stack", self.subir_stack):
            return 1
        if self.respostas.baixar_modelo:
            self._etapa("model", self.baixar_modelo)
        n8n_ok = self._etapa("n8n", self.provisionar_n8n, valores)
        if self.respostas.firmware:
            self._etapa("firmware", self.gerar_env_firmware)
        modelo_ok = not self.respostas.modelo_ei or self._etapa("ei-model", self.incluir_modelo_ei)
        self.resumo = dados_do_resumo(valores, self.destino)
        if not modelo_ok:
            return 1
        return 0 if n8n_ok else 2


def esperar_http(url: str, timeout: float = 5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:  # noqa: S310 (URL fixa, loopback)
            return 200 <= resposta.status < 400
    except (urllib.error.URLError, OSError):
        return False


def copiar_projeto(origem: Path, destino: Path) -> None:
    """Copia só o necessário para rodar a stack, normalizando as quebras de linha dos textos."""
    for relativo in ARQUIVOS_DO_PROJETO:
        fonte = origem / relativo
        if not fonte.exists():
            continue
        arquivos = (
            [fonte]
            if fonte.is_file()
            else [p for p in fonte.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        )
        for arquivo in arquivos:
            alvo = destino / arquivo.relative_to(origem)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            dados = arquivo.read_bytes()
            if arquivo.suffix in EXTENSOES_DE_TEXTO:
                dados = normalizar_texto(dados)
            alvo.write_bytes(dados)
            if arquivo.suffix == ".sh" and os.name == "posix":
                alvo.chmod(0o755)


def raiz_do_projeto() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]  # noqa: SLF001
    return Path(__file__).resolve().parent.parent


def pasta_padrao(origem: Path) -> Path:
    return Path.home() / "ELEX20" if getattr(sys, "frozen", False) else origem


# ── Perguntas em texto simples ───────────────────────────────────────────────


def perguntar(texto: str, padrao: str = "", segredo: bool = False, validar=None) -> str:
    sufixo = f" [{padrao}]" if padrao and not segredo else ""
    while True:
        try:
            leitura = getpass.getpass if segredo else input
            resposta = leitura(f"   {texto}{sufixo}: ").strip() or padrao
        except EOFError:
            return padrao
        erro = validar(resposta) if validar else None
        if not erro:
            return resposta
        print(f"   {erro}")


def confirmar(texto: str, padrao: bool = True) -> bool:
    resposta = perguntar(f"{texto} ({'Y/n' if padrao else 'y/N'})").lower()
    return resposta.startswith("y") if resposta else padrao


def coletar_respostas(destino: Path | None, origem: Path, extras: dict[str, str], pular_modelo: bool) -> Respostas:
    """Perguntas em texto simples, para quando a interface em tela cheia não está disponível."""
    print("\n== Install location")
    pasta = destino or Path(perguntar("Install folder", str(pasta_padrao(origem)), validar=validar_pasta))
    pasta = pasta.expanduser().resolve()
    respostas = Respostas(destino=pasta, extras=dict(extras), baixar_modelo=not pular_modelo)

    if not (pasta / ".env").exists():
        print("\n== Services")
        if confirmar("Will the ESP32 sensor connect through your network?", False):
            respostas.ip_lan = perguntar("This computer's IP address", detectar_ip_lan() or "", validar=validar_ip)
        if confirmar("Set up an OpenRouter API key for Hermes?", False):
            respostas.extras.setdefault("OPENROUTER_API_KEY", perguntar("OpenRouter API key", segredo=True))
        if confirmar("Set up the Telegram bot?", False):
            respostas.extras.setdefault("TELEGRAM_BOT_TOKEN", perguntar("Bot token (from @BotFather)", segredo=True))
            usuarios = perguntar("Your Telegram user ID", validar=validar_ids)
            respostas.extras.setdefault("TELEGRAM_ALLOWED_USERS", usuarios)
            respostas.extras.setdefault(
                "TELEGRAM_HOME_CHANNEL", perguntar("Chat ID for alerts", usuarios, validar=validar_ids)
            )
        if confirmar("Set up the Discord bot?", False):
            respostas.extras.setdefault("DISCORD_BOT_TOKEN", perguntar("Bot token", segredo=True))
            respostas.extras.setdefault("DISCORD_ALLOWED_USERS", perguntar("Your Discord user ID", validar=validar_ids))
            respostas.extras.setdefault("DISCORD_HOME_CHANNEL", perguntar("Channel ID for alerts", validar=validar_ids))

    if not pular_modelo:
        respostas.baixar_modelo = confirmar(f"Download the local AI model {MODELO_OLLAMA} (~2 GB)?", True)
    if (pasta / "firmware" / "platformio.ini").exists() and confirmar("Create firmware/.env for the sensor?", False):
        print("\n== Device")
        respostas.firmware = coletar_firmware(pasta, respostas.ip_lan)
        respostas.ip_lan = respostas.ip_lan or respostas.firmware.host
    if (pasta / "firmware" / "platformio.ini").exists() and confirmar(
        "Add an Edge Impulse sound model to the firmware?", False
    ):
        caminho = perguntar("Model .zip or folder (Deployment → Arduino library)", validar=validar_modelo_ei)
        respostas.modelo_ei = Path(caminho).expanduser().resolve()
    return respostas


def env_do_firmware(pasta: Path) -> dict[str, str]:
    arquivo = pasta / "firmware" / ".env"
    return ler_env(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}


def perguntar_rede(numero: int, atual: RedeWifi | None, host: str) -> RedeWifi:
    """Perguntas de uma rede Wi-Fi; Enter mantém o valor atual."""
    atual = atual or RedeWifi(ssid="")
    ssid = perguntar("Wi-Fi network name (SSID, 2.4 GHz only)", atual.ssid, validar=validar_ssid)
    mesma = ssid == atual.ssid
    rede = RedeWifi(ssid=ssid)
    if confirmar(
        "Is it an institutional network with a personal login (WPA2-Enterprise, like eduroam)?",
        mesma and atual.institucional,
    ):
        rede.eap_usuario = perguntar(
            "Username (such as student@university.edu)",
            atual.eap_usuario if mesma else "",
            validar=validar_usuario_eap,
        )
    guardada = mesma and bool(atual.senha)
    rotulo = "Password of this account" if rede.institucional else "Wi-Fi password"
    rede.senha = perguntar(
        rotulo + (" (Enter keeps the current one)" if guardada else ""),
        segredo=True,
        validar=lambda v: None if (guardada and not v) else validar_senha_wifi(v, rede.institucional),
    )
    if rede.institucional:
        anterior = atual if mesma else RedeWifi(ssid="")
        rede.eap_identidade = perguntar(
            "Outer identity, optional (such as anonymous@university.edu)",
            anterior.eap_identidade,
            validar=validar_identidade_eap,
        )
        rede.eap_metodo = perguntar(
            "Method, PEAP or TTLS", anterior.eap_metodo or "PEAP", validar=validar_metodo_eap
        ).upper()
        print("   The CA certificate lets the sensor check it is talking to the real network;")
        print("   ask your IT team for it (on eduroam, it is usually on the network setup page).")
        rede.ca = perguntar("CA certificate file (.pem), optional", anterior.ca, validar=validar_certificado)
        if not rede.ca:
            print("   Without it, a fake access point with the same name could capture the password.")
    if numero > 1:
        rede.mqtt_host = perguntar(
            "This computer's IP address when the sensor is on this network",
            (atual.mqtt_host if mesma else "") or host,
            validar=validar_ip,
        )
        if rede.mqtt_host == host:
            rede.mqtt_host = ""
    return rede


def coletar_firmware(pasta: Path, ip_lan: str | None) -> Firmware:
    """Redes Wi-Fi e servidor do sensor, em texto simples (instalação e --wifi)."""
    atual = env_do_firmware(pasta)
    existentes = redes_do_env(atual)
    print("   The sensor can store up to 4 Wi-Fi networks and tries each one until it connects.")
    print("\n-- Wi-Fi network 1")
    principal = perguntar_rede(1, existentes[0] if existentes else None, "")
    host = perguntar(
        "This computer's IP address (the MQTT server)",
        ip_lan or detectar_ip_lan() or atual.get("MQTT_HOST", ""),
        validar=validar_ip,
    )
    redes = [principal]
    while len(redes) < MAX_REDES_WIFI and confirmar(
        "Add another Wi-Fi network (such as home and university)?", len(existentes) > len(redes)
    ):
        print(f"\n-- Wi-Fi network {len(redes) + 1}")
        anterior = existentes[len(redes)] if len(existentes) > len(redes) else None
        redes.append(perguntar_rede(len(redes) + 1, anterior, host))
    return Firmware(redes=redes, host=host)


def ambiente_pio(pasta: Path) -> str:
    """Firmware com modelo quando há uma biblioteca do Edge Impulse em firmware/lib/ei-model."""
    modelos = pasta / PASTA_MODELO_EI
    tem_modelo = modelos.is_dir() and any(p.is_dir() for p in modelos.iterdir())
    return "esp32s3_model" if tem_modelo else "esp32s3"


def configurar_wifi(args, origem: Path) -> int:
    """--wifi: troca as redes do sensor, acompanha o IP do computador e grava a placa."""
    print(titulo_do_instalador())
    pasta = (args.dir or pasta_da_pilha() or origem).expanduser().resolve()
    if not (pasta / "firmware" / "platformio.ini").is_file():
        print(f"No firmware folder in {pasta}. Run this from a copy of the repository, or use --dir.")
        return 1
    saida = Saida()
    instalador = Instalador(origem, Respostas(destino=pasta), args.dry_run, saida)
    atual = env_do_firmware(pasta)
    ip = detectar_ip_lan()
    print(f"\n== Wi-Fi of the sensor ({pasta / 'firmware' / '.env'})")
    for numero, rede in enumerate(redes_do_env(atual), start=1):
        tipo = "institutional" if rede.institucional else "personal"
        servidor = rede.mqtt_host or atual.get("MQTT_HOST", "?")
        print(f"   {numero}. {rede.ssid} ({tipo}), server {servidor}")
    print(f"   This computer's IP address now: {ip or 'unknown'}")

    if not atual or confirmar("Change the Wi-Fi networks?", not atual):
        firmware = coletar_firmware(pasta, ip)
    else:
        # Só o IP do computador mudou: confere o servidor de cada rede
        redes = redes_do_env(atual)
        host = perguntar(
            f"This computer's IP address on {redes[0].ssid}", atual.get("MQTT_HOST") or ip or "", validar=validar_ip
        )
        for rede in redes[1:]:
            rede.mqtt_host = perguntar(
                f"This computer's IP address on {rede.ssid}", rede.mqtt_host or host, validar=validar_ip
            )
            rede.mqtt_host = "" if rede.mqtt_host == host else rede.mqtt_host
        firmware = Firmware(redes=redes, host=host)
    instalador.respostas.firmware = firmware
    instalador.gerar_env_firmware()
    # Senhas em branco mantêm as gravadas: só o arquivo final diz se a placa precisa mudar
    mudou_firmware = env_do_firmware(pasta) != atual

    # O broker só escuta no IP de MQTT_BIND: acompanha o IP atual do computador
    env_pilha = pasta / ".env"
    if ip and env_pilha.is_file():
        valores = ler_env(env_pilha.read_text(encoding="utf-8"))
        if valores.get("MQTT_BIND") != ip and confirmar(
            f"Make the MQTT server listen on {ip} (now {valores.get('MQTT_BIND') or 'this computer only'})?", True
        ):
            env_pilha.write_text(
                aplicar_env(env_pilha.read_text(encoding="utf-8"), {"MQTT_BIND": ip}), encoding="utf-8"
            )
            try:
                instalador.compose("up", "-d", "mosquitto")
                print(f"   MQTT server now listens on {ip}:1883.")
            except (subprocess.CalledProcessError, OSError):
                print("   Could not restart it; run: docker compose up -d mosquitto")

    if not mudou_firmware:
        print("\nThe sensor configuration did not change; no need to flash it again.")
        return 0
    comando = ["pio", "run", "-e", ambiente_pio(pasta), "-t", "upload"]
    if not shutil.which("pio"):
        print("\nPlatformIO (pio) was not found. Flash the sensor with:")
        print(f"   cd {pasta / 'firmware'} && {' '.join(comando)}")
        return 0
    if args.dry_run or not confirmar("Flash the sensor now? (connect it by USB first)", True):
        print(f"Flash it later with: cd {pasta / 'firmware'} && {' '.join(comando)}")
        return 0
    return subprocess.run(comando, cwd=pasta / "firmware", check=False).returncode  # noqa: S603


def coletar_remocao(destino: Path | None, remocao: Remocao) -> tuple[Path, Remocao] | None:
    """Perguntas da desinstalação em texto simples; None se o usuário desistir."""
    print("\n== Uninstall")
    padrao = destino or pasta_da_pilha() or pasta_padrao(raiz_do_projeto())
    pasta = Path(perguntar("Installed folder", str(padrao))).expanduser().resolve()
    remocao.dados = remocao.dados or confirmar("Delete all data, including history and passwords?", False)
    remocao.imagens = remocao.imagens or confirmar("Delete downloaded Docker images?", False)
    remocao.arquivos = remocao.arquivos or confirmar("Delete the installed files and .env?", False)
    if remocao.exige_confirmacao and perguntar("This cannot be undone. Type delete to confirm") != "delete":
        print("   Nothing was changed.")
        return None
    if not confirmar(f"Remove ELEX20 from {pasta}?", False):
        print("   Nothing was changed.")
        return None
    return pasta, remocao


def executar_remocao(args, origem: Path, elex_tui) -> tuple[int, dict | None]:
    remocao = Remocao(args.delete_data, args.delete_images, args.delete_files)
    if elex_tui:
        padrao = pasta_da_pilha() or pasta_padrao(origem)
        return elex_tui.executar(origem, args.dir, padrao, {}, True, args.dry_run, remocao)
    print(titulo_do_instalador())
    if args.non_interactive:
        pasta = (args.dir or pasta_da_pilha() or pasta_padrao(origem)).expanduser().resolve()
    else:
        escolha = coletar_remocao(args.dir, remocao)
        if escolha is None:
            return 0, None
        pasta, remocao = escolha
    instalador = Instalador(origem, Respostas(destino=pasta), args.dry_run)
    return instalador.desinstalar(remocao), instalador.resumo


def verificar_interface() -> int:
    """Abre a interface sem terminal e fecha: confirma que o executável traz o Textual completo."""
    import elex_tui  # noqa: PLC0415

    elex_tui.verificar()
    print("ui ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Install ELEX20 (Docker, passwords, n8n) on Windows, macOS or Linux.")
    parser.add_argument("--dir", type=Path, help="install folder (default: ask; ~/ELEX20 or this repository)")
    parser.add_argument(
        "--non-interactive", "-y", action="store_true", help="ask nothing; use the defaults and --set values"
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="set a .env variable (e.g. OPENROUTER_API_KEY=...)",
    )
    parser.add_argument("--skip-model", action="store_true", help="do not download the local Ollama model")
    parser.add_argument(
        "--ei-model",
        type=Path,
        metavar="PATH",
        help="add an Edge Impulse Arduino library (.zip or folder) to firmware/lib/ei-model",
    )
    parser.add_argument(
        "--wifi",
        action="store_true",
        help="change the sensor's Wi-Fi networks or follow this computer's new IP, then flash the sensor",
    )
    parser.add_argument("--dry-run", action="store_true", help="create the files, but only show the Docker commands")
    parser.add_argument("--uninstall", action="store_true", help="remove the ELEX20 containers")
    parser.add_argument(
        "--delete-data", action="store_true", help="with --uninstall: also delete all data and generated passwords"
    )
    parser.add_argument("--delete-images", action="store_true", help="with --uninstall: also delete the Docker images")
    parser.add_argument(
        "--delete-files", action="store_true", help="with --uninstall: also delete the installed files and .env"
    )
    parser.add_argument("--no-tui", action="store_true", help="use plain text prompts instead of the full-screen UI")
    parser.add_argument("--check-ui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"elex-installer {VERSAO}")
    args = parser.parse_args(argv)

    if args.check_ui:
        return verificar_interface()
    if not args.uninstall and (args.delete_data or args.delete_images or args.delete_files):
        parser.error("--delete-data, --delete-images and --delete-files need --uninstall")
    if args.ei_model:
        erro = validar_modelo_ei(str(args.ei_model))
        if erro:
            parser.error(f"--ei-model: {erro}")
        args.ei_model = args.ei_model.expanduser().resolve()

    extras: dict[str, str] = {}
    for item in args.set:
        chave, separador, valor = item.partition("=")
        if not separador or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", chave):
            parser.error(f"--set expects KEY=VALUE, got: {item!r}")
        extras[chave] = valor

    origem = raiz_do_projeto()
    pausar = getattr(sys, "frozen", False) and platform.system() == "Windows" and not args.non_interactive
    tela_cheia = not (args.non_interactive or args.no_tui) and sys.stdin.isatty() and sys.stdout.isatty()
    elex_tui = None
    if tela_cheia:
        try:
            import elex_tui  # noqa: PLC0415
        except (ImportError, TypeError):
            print("The Textual library is not available; using plain text prompts.")

    try:
        if args.wifi:
            codigo, resumo = configurar_wifi(args, origem), None
        elif args.uninstall:
            codigo, resumo = executar_remocao(args, origem, elex_tui)
        elif elex_tui:
            codigo, resumo = elex_tui.executar(
                origem, args.dir, pasta_padrao(origem), extras, args.skip_model, args.dry_run, modelo_ei=args.ei_model
            )
        else:
            print(titulo_do_instalador())
            if args.non_interactive:
                pasta = (args.dir or pasta_padrao(origem)).expanduser().resolve()
                respostas = Respostas(
                    destino=pasta, extras=extras, baixar_modelo=not args.skip_model, modelo_ei=args.ei_model
                )
            else:
                respostas = coletar_respostas(args.dir, origem, extras, args.skip_model)
                respostas.modelo_ei = respostas.modelo_ei or args.ei_model
            instalador = Instalador(origem, respostas, args.dry_run)
            codigo = instalador.executar()
            resumo = instalador.resumo
        if resumo:
            imprimir_resumo(resumo)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        codigo = 130
    if pausar:
        input("\nPress Enter to close...")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
