"""Instalador do ELEX20 para Windows, macOS e Linux.

Só usa a biblioteca padrão do Python, para virar um executável único (PyInstaller).
O que ele faz, nesta ordem:
  1. confere se o Docker está instalado e ligado (e, se não, explica como instalar);
  2. cria o .env com todas as senhas geradas aleatoriamente;
  3. sobe a stack com `docker compose up -d` e espera ficar de pé;
  4. baixa o modelo local do Ollama (opcional);
  5. cria as credenciais e ativa os workflows do n8n, sem passos manuais.

Rodando a partir do repositório (python installer/elex_installer.py) ele instala ali mesmo.
Rodando como executável, ele copia os arquivos embutidos para uma pasta (padrão ~/ELEX20).
"""

from __future__ import annotations

import argparse
import getpass
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
from pathlib import Path


def ler_versao() -> str:
    """Versão gravada pelo CI (versao.txt, a partir da tag); '0.0.0-dev' fora de um build de release."""
    pasta = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent  # type: ignore[attr-defined]  # noqa: SLF001
    try:
        return (pasta / "versao.txt").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


VERSAO = ler_versao()

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
        raise ValueError("valor com quebra de linha")
    if not re.search(r"[\s#$'\"\\`]", valor):
        return valor
    if "'" not in valor:
        return f"'{valor}'"
    raise ValueError("valor com aspa simples e caracteres especiais não é suportado")


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
            "Instale o Docker Desktop: https://www.docker.com/products/docker-desktop/",
            "Na instalação, deixe marcada a opção 'WSL 2'. Reinicie o computador se ele pedir.",
            "Abra o Docker Desktop, espere o ícone ficar verde e rode este instalador de novo.",
        ]
    if sistema == "Darwin":
        return [
            "Instale o Docker Desktop: https://www.docker.com/products/docker-desktop/",
            "Abra o Docker Desktop, espere ele iniciar e rode este instalador de novo.",
            "Com Homebrew: brew install --cask docker",
        ]
    passos_pos = [
        "sudo systemctl enable --now docker",
        "sudo usermod -aG docker $USER   # depois, saia da sessão e entre de novo",
    ]
    if familia & {"arch", "manjaro", "endeavouros", "cachyos"}:
        return ["sudo pacman -S docker docker-compose", *passos_pos]
    if familia & {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "suse", "sles"}:
        return ["sudo zypper install docker docker-compose", *passos_pos]
    if familia & {"fedora", "rhel", "centos", "rocky", "almalinux"}:
        return [
            "Guia oficial: https://docs.docker.com/engine/install/fedora/",
            "curl -fsSL https://get.docker.com | sudo sh   # script de conveniência oficial",
            *passos_pos,
        ]
    if familia & {"ubuntu", "debian", "linuxmint", "pop", "zorin", "elementary", "raspbian"}:
        return [
            "Guia oficial: https://docs.docker.com/engine/install/ubuntu/ (ou /debian/)",
            "curl -fsSL https://get.docker.com | sudo sh   # script de conveniência oficial",
            *passos_pos,
        ]
    return ["Guia oficial: https://docs.docker.com/engine/install/", *passos_pos]


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
        return "password (placeholder: troque)"
    return "a definida no .env"


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


# ── Entrada e saída ──────────────────────────────────────────────────────────


class Instalador:
    def __init__(
        self,
        raiz_origem: Path,
        destino: Path,
        nao_interativo: bool,
        dry_run: bool,
        extras: dict[str, str],
        pular_modelo: bool = False,
    ):
        self.origem = raiz_origem
        self.pular_modelo = pular_modelo
        self.ip_lan: str | None = None
        self.destino = destino
        self.nao_interativo = nao_interativo
        self.dry_run = dry_run
        self.extras = extras
        self.sistema = platform.system()

    # saída
    def titulo(self, texto: str) -> None:
        print(f"\n== {texto}")

    def info(self, texto: str) -> None:
        print(f"   {texto}")

    def erro(self, texto: str) -> None:
        print(f"\n[ERRO] {texto}", file=sys.stderr)

    # entrada
    def perguntar(self, texto: str, padrao: str = "", segredo: bool = False) -> str:
        if self.nao_interativo:
            return padrao
        sufixo = f" [{padrao}]" if padrao and not segredo else ""
        try:
            leitura = getpass.getpass if segredo else input
            resposta = leitura(f"   {texto}{sufixo}: ").strip()
        except EOFError:
            return padrao
        return resposta or padrao

    def confirmar(self, texto: str, padrao: bool = True) -> bool:
        if self.nao_interativo:
            return padrao
        dica = "S/n" if padrao else "s/N"
        resposta = self.perguntar(f"{texto} ({dica})").lower()
        if not resposta:
            return padrao
        return resposta.startswith(("s", "y"))

    # comandos
    def docker(self, *args: str, capturar: bool = False, check: bool = True, entrada: str | None = None):
        cmd = ["docker", *args]
        if self.dry_run:
            self.info("(simulação) " + " ".join(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.run(  # noqa: S603
            cmd, cwd=self.destino, check=check, text=True, capture_output=capturar, input=entrada
        )

    def compose(self, *args: str, **kw):
        return self.docker("compose", *args, **kw)

    # ── etapas ───────────────────────────────────────────────────────────────

    def verificar_docker(self) -> bool:
        self.titulo("1/5  Conferindo o Docker")
        if self.dry_run:
            self.info("(simulação) verificação do Docker ignorada")
            return True
        if shutil.which("docker") is None:
            self.erro("O Docker não está instalado.")
            self.mostrar_como_instalar()
            return False
        versao = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=False)  # noqa: S603, S607
        if versao.returncode != 0:
            self.erro("O Docker está instalado, mas falta o 'docker compose' (plugin Compose v2).")
            self.mostrar_como_instalar()
            return False
        info = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)  # noqa: S603, S607
        if info.returncode != 0:
            saida = (info.stderr or "") + (info.stdout or "")
            if "permission denied" in saida.lower():
                self.erro(
                    "Sem permissão para usar o Docker. No Linux: sudo usermod -aG docker $USER e reinicie a sessão."
                )
            else:
                self.erro(
                    "O Docker está instalado, mas não está rodando. "
                    "Abra o Docker Desktop (ou: sudo systemctl start docker)."
                )
            return False
        self.info("Docker e Compose funcionando.")
        return True

    def mostrar_como_instalar(self) -> None:
        distro, parecidas = "", []
        if self.sistema == "Linux":
            try:
                distro, parecidas = detectar_distro(Path("/etc/os-release").read_text(encoding="utf-8"))
            except OSError:
                pass
        print("\nComo instalar o Docker neste computador:")
        for linha in instrucoes_docker(self.sistema, distro, parecidas):
            print(f"   {linha}")

    def preparar_pasta(self) -> None:
        self.titulo("2/5  Preparando os arquivos")
        if self.origem.resolve() != self.destino.resolve():
            self.info(f"Copiando para {self.destino}")
            copiar_projeto(self.origem, self.destino)
        else:
            self.info(f"Usando a pasta do repositório: {self.destino}")

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
        self.titulo("3/5  Gerando as senhas e o arquivo .env")
        arquivo = self.destino / ".env"
        modelo_texto = (self.destino / ".env.example").read_text(encoding="utf-8")
        existente = ler_env(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}

        banco_ja_existe = False
        if not existente and self.volumes_antigos():
            if self.senha_padrao_do_banco_funciona():
                self.info("A stack já roda com as senhas padrão (subida sem .env); elas serão mantidas.")
                banco_ja_existe = True
            else:
                self.erro(
                    "Existem dados de uma instalação anterior (volume do banco), mas não há .env.\n"
                    "Um .env novo teria senhas diferentes e o banco antigo não abriria.\n"
                    "Recupere o .env antigo, ou apague os dados antigos de propósito (docker compose down -v)."
                )
                return None

        ip_lan = None
        extras = dict(self.extras)
        if not existente:
            ip = detectar_ip_lan()
            if self.confirmar("Vai ligar o sensor ESP32 na sua rede Wi-Fi/rede local?", padrao=False):
                ip_lan = self.perguntar("IP deste computador na rede", ip or "")
            if self.confirmar("Quer configurar o Hermes com OpenRouter (chave de API)?", padrao=False):
                extras.setdefault("OPENROUTER_API_KEY", self.perguntar("Chave OPENROUTER_API_KEY", segredo=True))
            if self.confirmar("Quer configurar o bot do Telegram?", padrao=False):
                extras.setdefault("TELEGRAM_BOT_TOKEN", self.perguntar("Token do bot (do @BotFather)", segredo=True))
                extras.setdefault(
                    "TELEGRAM_ALLOWED_USERS",
                    self.perguntar("Seu ID de usuário no Telegram (quem pode falar com o bot)"),
                )
                extras.setdefault(
                    "TELEGRAM_HOME_CHANNEL",
                    self.perguntar("ID do chat que recebe os alertas", extras.get("TELEGRAM_ALLOWED_USERS", "")),
                )
            if self.confirmar("Quer configurar o bot do Discord?", padrao=False):
                extras.setdefault("DISCORD_BOT_TOKEN", self.perguntar("Token do bot do Discord", segredo=True))
                extras.setdefault("DISCORD_ALLOWED_USERS", self.perguntar("Seu ID de usuário no Discord"))
                extras.setdefault("DISCORD_HOME_CHANNEL", self.perguntar("ID do canal que recebe os alertas"))

        self.ip_lan = ip_lan
        modelo = ler_env(modelo_texto)
        novos = montar_valores(existente, modelo, self.sistema, ip_lan, extras, banco_ja_existe)
        if existente and not novos:
            self.info("O .env já está completo; nada foi alterado.")
        else:
            texto_base = arquivo.read_text(encoding="utf-8") if existente else modelo_texto
            arquivo.write_text(aplicar_env(texto_base, novos), encoding="utf-8")
            if os.name == "posix":
                arquivo.chmod(0o600)
            self.info(f"Arquivo .env {'atualizado' if existente else 'criado'} com {len(novos)} valor(es) novo(s).")
        return {**modelo, **existente, **novos}

    def subir_stack(self) -> bool:
        self.titulo("4/5  Subindo os serviços (a primeira vez baixa alguns GB)")
        try:
            self.compose("up", "-d")
        except subprocess.CalledProcessError:
            self.erro("O docker compose falhou. Veja a mensagem acima (portas ocupadas? pouco espaço em disco?).")
            return False
        if self.dry_run:
            return True
        self.info("Esperando o n8n e o Grafana ficarem prontos...")
        pendentes = {"n8n": f"{URL_N8N}/healthz", "Grafana": f"{URL_GRAFANA}/api/health"}
        limite = time.monotonic() + 600
        while pendentes and time.monotonic() < limite:
            for nome, url in list(pendentes.items()):
                if esperar_http(url):
                    self.info(f"{nome} pronto.")
                    del pendentes[nome]
            if pendentes:
                time.sleep(5)
        if pendentes:
            self.erro(
                f"Não respondeu a tempo: {', '.join(pendentes)}. "
                f"Veja: docker compose logs {' '.join(n.lower() for n in pendentes)}"
            )
            return False
        return True

    def baixar_modelo(self) -> None:
        if not self.confirmar(
            f"Baixar o modelo local de IA {MODELO_OLLAMA} (~2 GB, serve de reserva sem internet)?", True
        ):
            return
        self.info("Baixando o modelo; pode demorar...")
        try:
            self.compose("exec", "-T", "ollama", "ollama", "pull", MODELO_OLLAMA)
        except subprocess.CalledProcessError:
            self.info(f"Não deu certo agora. Tente depois: docker compose exec ollama ollama pull {MODELO_OLLAMA}")

    def ler_segredo(self, servico: str, nome: str) -> str:
        """Lê um segredo gerado pela stack, de dentro do container que o monta."""
        if self.dry_run:
            return f"<{nome}>"
        r = self.compose("exec", "-T", servico, "cat", f"/run/secrets/{nome}/value", capturar=True)
        return r.stdout.strip()

    def provisionar_n8n(self, valores: dict[str, str]) -> bool:
        self.titulo("5/5  Configurando o n8n (credenciais e workflows)")
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
            self.compose("cp", str(arquivo), "n8n:/tmp/elex-cred.json")
            try:
                self.compose(*n8n, "import:credentials", "--input=/tmp/elex-cred.json", capturar=True)
            finally:
                self.compose("exec", "-T", "n8n", "rm", "-f", "/tmp/elex-cred.json", check=False)  # noqa: S108 (caminho no container)
            self.compose(*n8n, "import:workflow", "--separate", "--input=/workflows", capturar=True)
            for wid in WORKFLOWS_N8N:
                self.compose(*n8n, "publish:workflow", f"--id={wid}", capturar=True)
            self.compose("restart", "n8n", capturar=True)
        except subprocess.CalledProcessError as exc:
            self.erro(f"Falha ao configurar o n8n: {(exc.stderr or exc.stdout or exc)}")
            return False
        finally:
            arquivo.unlink(missing_ok=True)
        self.info("Credenciais criadas e workflows ativados.")
        return True

    def gerar_env_firmware(self, ip_lan: str | None) -> None:
        if not (self.destino / "firmware" / "platformio.ini").exists():
            return
        if not self.confirmar("Gerar o firmware/.env com Wi-Fi e senha MQTT para compilar o firmware?", padrao=False):
            return
        ssid = self.perguntar("Nome da rede Wi-Fi (SSID, só 2,4 GHz)")
        senha = self.perguntar("Senha do Wi-Fi", segredo=True)
        host = self.perguntar("IP deste computador na rede", ip_lan or detectar_ip_lan() or "")
        texto = (
            f"WIFI_SSID={ssid}\nWIFI_PASS={senha}\nMQTT_HOST={host}\nMQTT_USER=device\n"
            f"MQTT_PASS={self.ler_segredo('mosquitto', 'mqtt_device')}\n"
        )
        arquivo = self.destino / "firmware" / ".env"
        arquivo.write_text(texto, encoding="utf-8")
        if os.name == "posix":
            arquivo.chmod(0o600)
        self.info("firmware/.env criado.")

    def resumo(self, valores: dict[str, str]) -> None:
        print("\n" + "=" * 64)
        print(" ELEX20 instalado")
        print("=" * 64)
        print(f" Pasta:      {self.destino}")
        print(
            f" Grafana:    {URL_GRAFANA}   usuário {valores.get('GRAFANA_ADMIN_USER', 'admin')}"
            f"  senha {descrever_senha(valores.get('GRAFANA_ADMIN_PASSWORD'))}"
        )
        print(
            f" Hermes:     {URL_HERMES}   usuário {valores.get('HERMES_DASHBOARD_USER', 'admin')}"
            f"  senha {descrever_senha(valores.get('HERMES_DASHBOARD_PASS'))}"
        )
        print(f" n8n:        {URL_N8N}   (crie sua conta na primeira abertura)")
        print("\n Dados para gravar no sensor (firmware):")
        print(f"   MQTT_HOST = {valores.get('MQTT_BIND', '127.0.0.1')}   MQTT_USER = device")
        print("   MQTT_PASS: rode na pasta acima  docker compose exec mosquitto cat /run/secrets/mqtt_device/value")
        print("\n Os logins admin/password são placeholders: troque-os (no .env e na tela de cada serviço).")
        print(" As senhas internas (banco, MQTT, tokens) foram geradas sozinhas e ficam em volumes do Docker.")
        print(" Guarde o arquivo .env da pasta acima e não o compartilhe.")
        print(" Para parar: docker compose stop   |   Para iniciar de novo: docker compose start")

    def executar(self) -> int:
        if not self.verificar_docker():
            return 1
        self.preparar_pasta()
        valores = self.configurar_env()
        if valores is None:
            return 1
        if not self.subir_stack():
            return 1
        if not self.pular_modelo:
            self.baixar_modelo()
        n8n_ok = self.provisionar_n8n(valores)
        self.gerar_env_firmware(self.ip_lan)
        self.resumo(valores)
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


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Instala o ELEX20 (Docker, senhas, n8n) em Windows, macOS ou Linux.")
    parser.add_argument(
        "--dir", type=Path, help="pasta de instalação (padrão: ~/ELEX20 no executável; o repositório, no código-fonte)"
    )
    parser.add_argument(
        "--nao-interativo", "-y", action="store_true", help="não pergunta nada; usa os padrões e os --set"
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="CHAVE=VALOR",
        help="define uma variável do .env (ex.: OPENROUTER_API_KEY=...)",
    )
    parser.add_argument("--sem-modelo", action="store_true", help="não baixa o modelo local do Ollama")
    parser.add_argument(
        "--dry-run", action="store_true", help="cria os arquivos, mas só mostra os comandos do Docker sem executá-los"
    )
    parser.add_argument("--versao", action="version", version=f"elex-installer {VERSAO}")
    args = parser.parse_args(argv)

    extras: dict[str, str] = {}
    for item in args.set:
        chave, separador, valor = item.partition("=")
        if not separador or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", chave):
            parser.error(f"--set espera CHAVE=VALOR, recebi: {item!r}")
        extras[chave] = valor

    origem = raiz_do_projeto()
    destino = (args.dir or (Path.home() / "ELEX20" if getattr(sys, "frozen", False) else origem)).expanduser().resolve()
    destino.mkdir(parents=True, exist_ok=True)

    print(f"ELEX20 — instalador {VERSAO} ({platform.system()} {platform.machine()})")
    instalador = Instalador(origem, destino, args.nao_interativo, args.dry_run, extras, args.sem_modelo)
    try:
        codigo = instalador.executar()
    except KeyboardInterrupt:
        print("\nInterrompido.")
        codigo = 130
    if getattr(sys, "frozen", False) and platform.system() == "Windows" and not args.nao_interativo:
        input("\nPressione Enter para fechar...")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
