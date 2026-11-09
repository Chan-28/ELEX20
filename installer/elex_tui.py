"""Interface em tela cheia do instalador (Textual).

Só coleta respostas e mostra o progresso: quem instala é o motor, em elex_installer.py. O assistente
não muda nada no computador até o usuário confirmar a tela de revisão.
"""

from __future__ import annotations

import asyncio
import subprocess  # noqa: S404 (só para capturar a falha de um comando do motor)
from dataclasses import dataclass, field
from pathlib import Path

import elex_installer as inst
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Static,
    Switch,
)

CSS = """
Screen { background: $surface; }
#banner { dock: top; height: 1; padding: 0 2; background: $primary; color: $text; text-style: bold; }
#step { height: 1; margin: 1 2 0 2; color: $text-muted; }
#heading { height: auto; margin: 0 2; text-style: bold; }
#hint { height: auto; margin: 0 2 1 2; color: $text-muted; }
#body { height: 1fr; padding: 0 2; }
#nav { dock: bottom; height: 3; margin-bottom: 1; padding: 0 2; align-horizontal: right; }
#nav Button { margin-left: 2; }

.section { height: auto; margin-bottom: 1; padding: 0 1; border: round $panel; }
.section-head { height: 3; }
.section-row Horizontal { height: 3; }
.section-title { width: 1fr; padding: 1 0 0 0; text-style: bold; }
.field { height: auto; }
.field-label { height: 1; margin-top: 1; color: $text-muted; }
.field-error { height: auto; color: $error; }
.path-row { height: 3; }
.path-row Input { width: 1fr; }
.status { height: auto; margin-top: 1; }

.ok { color: $success; }
.warn { color: $warning; }
.bad { color: $error; }

#tables { height: auto; }
DataTable { height: auto; margin-bottom: 1; }
.table-title { height: 1; margin-top: 1; text-style: bold; }

#progress-area { height: 1fr; padding: 0 2; }
#step-list { width: 32; height: auto; }
#step-log { width: 1fr; height: 1fr; border: round $panel; }
#bar { width: 100%; margin: 0 2 1 2; }

DirPicker { align: center middle; }
#picker { width: 80%; height: 80%; padding: 1 2; background: $panel; border: round $primary; }
#picker DirectoryTree { height: 1fr; }
#picker-current { height: auto; margin-bottom: 1; }
#picker-nav { height: 3; align-horizontal: right; }
#picker-nav Button { margin-left: 2; }
"""


@dataclass
class Estado:
    """O que o assistente já sabe; as telas leem e gravam aqui."""

    origem: Path
    pasta: Path
    extras: dict[str, str]
    pular_modelo: bool
    dry_run: bool
    pasta_fixa: bool = False
    remocao: inst.Remocao | None = None
    # --ei-model: já preenche o campo do modelo na tela do dispositivo
    modelo_ei: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    firmware_env: dict[str, str] = field(default_factory=dict)
    respostas: inst.Respostas | None = None

    def recarregar(self) -> None:
        """Lê o que já existe na pasta, para o usuário só mudar o necessário."""
        self.env = inst.ler_env((self.pasta / ".env").read_text(encoding="utf-8")) if self.tem_env else {}
        arquivo = self.pasta / "firmware" / ".env"
        self.firmware_env = inst.ler_env(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}

    @property
    def tem_env(self) -> bool:
        return (self.pasta / ".env").is_file()

    @property
    def tem_firmware(self) -> bool:
        return (self.pasta / "firmware" / "platformio.ini").is_file()

    def valor(self, chave: str) -> str:
        return self.extras.get(chave) or self.env.get(chave, "")


def campo(rotulo: str, ident: str, valor: str = "", segredo: bool = False, dica: str = "") -> Vertical:
    return Vertical(
        Label(rotulo, classes="field-label"),
        Input(value=valor, password=segredo, id=ident, placeholder=dica),
        Static("", id=f"{ident}-error", classes="field-error"),
        classes="field",
    )


def secao(titulo: str, ident: str, ligada: bool, *campos: Vertical) -> Vertical:
    corpo = Vertical(*campos, id=f"{ident}-body", classes="field")
    corpo.display = ligada
    return Vertical(
        Horizontal(Label(titulo, classes="section-title"), Switch(value=ligada, id=ident), classes="section-head"),
        corpo,
        classes="section",
    )


def visivel(widget: Widget) -> bool:
    """Campo dentro de uma seção desligada (em qualquer nível) não conta."""
    return all(no.display for no in widget.ancestors_with_self if isinstance(no, Widget))


class Passo(Screen):
    """Moldura comum: título do instalador, etapa, conteúdo e navegação."""

    NUMERO = ""
    TITULO = ""
    DICA = ""
    PROXIMO = "Next"
    # campo -> função de validação; campos dentro de uma seção desligada não são validados
    REGRAS: dict = {}

    BINDINGS = [Binding("escape", "voltar", "Back", show=True)]

    @property
    def estado(self) -> Estado:
        return self.app.estado

    def cabecalho(self) -> ComposeResult:
        yield Static(inst.titulo_do_instalador(), id="banner")
        yield Static(self.NUMERO, id="step")
        yield Static(self.TITULO, id="heading")
        yield Static(self.DICA, id="hint")

    def navegacao(self) -> ComposeResult:
        with Horizontal(id="nav"):
            yield Button("Back", id="back")
            yield Button(self.PROXIMO, id="next", variant="primary")
        yield Footer()

    def action_voltar(self) -> None:
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()

    def validar(self) -> bool:
        primeiro = None
        for ident, regra in self.REGRAS.items():
            entrada = self.query_one(f"#{ident}", Input)
            ativo = visivel(entrada)
            erro = regra(entrada.value) if ativo else None
            self.query_one(f"#{ident}-error", Static).update(erro or "")
            if erro and primeiro is None:
                primeiro = entrada
        if primeiro:
            primeiro.focus()
        return primeiro is None

    def avancar(self) -> None:
        raise NotImplementedError

    @on(Button.Pressed, "#back")
    def _voltar(self) -> None:
        self.action_voltar()

    @on(Button.Pressed, "#next")
    def _avancar(self) -> None:
        if self.validar():
            self.avancar()

    @on(Input.Submitted)
    def _enter(self) -> None:
        self.focus_next()

    @on(Switch.Changed)
    def _alternar(self, evento: Switch.Changed) -> None:
        corpo = self.query(f"#{evento.switch.id}-body")
        if corpo:
            corpo.first().display = evento.value


class DirPicker(ModalScreen[Path | None]):
    """Navegador de pastas; devolve a pasta escolhida."""

    BINDINGS = [Binding("escape", "cancelar", "Cancel")]

    def __init__(self, inicio: Path):
        super().__init__()
        self.atual = inicio

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static(str(self.atual), id="picker-current")
            yield DirectoryTree(self.atual, id="tree")
            with Horizontal(id="picker-nav"):
                yield Button("Parent folder", id="up")
                yield Button("Cancel", id="cancel")
                yield Button("Select", id="select", variant="primary")

    def _ir_para(self, pasta: Path) -> None:
        self.atual = pasta
        self.query_one("#picker-current", Static).update(str(pasta))

    @on(DirectoryTree.DirectorySelected)
    def _selecionada(self, evento: DirectoryTree.DirectorySelected) -> None:
        self._ir_para(evento.path)

    @on(Button.Pressed, "#up")
    def _subir(self) -> None:
        self._ir_para(self.atual.parent)
        self.query_one("#tree", DirectoryTree).path = self.atual

    @on(Button.Pressed, "#select")
    def _escolher(self) -> None:
        self.dismiss(self.atual)

    @on(Button.Pressed, "#cancel")
    def action_cancelar(self) -> None:
        self.dismiss(None)


class TelaPasta(Passo):
    NUMERO = "Step 1 of 4"
    TITULO = "Choose where to install"
    DICA = "ELEX20 keeps its configuration in this folder. Nothing changes until you confirm the last step."
    REGRAS = {"dir": inst.validar_pasta}

    docker_ok = False

    def compose(self) -> ComposeResult:
        yield from self.cabecalho()
        with VerticalScroll(id="body"):
            yield Label("Install folder", classes="field-label")
            with Horizontal(classes="path-row"):
                yield Input(value=str(self.estado.pasta), id="dir", disabled=self.estado.pasta_fixa)
                yield Button("Browse…", id="browse", disabled=self.estado.pasta_fixa)
            yield Static("", id="dir-error", classes="field-error")
            yield Static("", id="dir-status", classes="status")
            yield Static("Checking Docker…", id="docker-status", classes="status")
            yield Static("", id="docker-help", classes="status")
            yield Button("Check again", id="retry")
            yield Button("Uninstall ELEX20…", id="uninstall", variant="error", disabled=True)
        yield from self.navegacao()

    def on_mount(self) -> None:
        self.query_one("#back").display = False
        self.query_one("#retry").display = False
        self.query_one("#next", Button).disabled = True
        self.descrever_pasta()
        self.verificar_docker()

    @work(thread=True, exclusive=True)
    def verificar_docker(self) -> None:
        if self.estado.dry_run:
            resultado = (True, "Dry run: Docker will not be used.", [], None)
        else:
            ok, mensagem = inst.checar_docker()
            ajuda = inst.como_instalar_docker() if not ok and "running" not in mensagem else []
            resultado = (ok, mensagem, ajuda, inst.pilha_em_outra_pasta(self.pasta()) if ok else None)
        self.app.call_from_thread(self.mostrar_docker, *resultado)

    def pasta(self) -> Path:
        return Path(self.query_one("#dir", Input).value.strip() or ".").expanduser().resolve()

    def mostrar_docker(self, ok: bool, mensagem: str, ajuda: list[str], outra: str | None) -> None:
        self.docker_ok = ok
        status = self.query_one("#docker-status", Static)
        status.update(Text(("✔ " if ok else "✖ ") + mensagem, style="green" if ok else "red"))
        self.query_one("#docker-help", Static).update(Text("\n".join(ajuda)))
        self.query_one("#retry").display = not ok
        self.query_one("#next", Button).disabled = not ok
        self.query_one("#uninstall", Button).disabled = not ok
        if outra:
            self.query_one("#dir", Input).value = outra
            self.notify(f"ELEX20 is already installed in {outra}.", severity="warning")

    def descrever_pasta(self) -> None:
        pasta = self.pasta()
        self.query_one("#uninstall").display = inst.instalacao_valida(pasta) and (pasta / ".env").is_file()
        if (pasta / ".env").is_file():
            texto, estilo = "Existing installation: your current settings will be kept.", "yellow"
        elif pasta.resolve() == self.estado.origem.resolve():
            texto, estilo = "This is the ELEX20 repository: it can also set up the device.", "green"
        elif pasta.exists() and any(pasta.iterdir()):
            texto, estilo = "This folder is not empty. ELEX20 files will be added to it.", "yellow"
        else:
            texto, estilo = "New folder: it will be created during the installation.", "green"
        self.query_one("#dir-status", Static).update(Text(texto, style=estilo))

    @on(Input.Changed, "#dir")
    def _pasta_mudou(self) -> None:
        if self.query_one("#dir", Input).value.strip():
            self.descrever_pasta()

    @on(Button.Pressed, "#browse")
    def _navegar(self) -> None:
        inicio = next((p for p in (self.pasta(), *self.pasta().parents) if p.is_dir()), Path.home())

        def escolhida(pasta: Path | None) -> None:
            if pasta:
                self.query_one("#dir", Input).value = str(pasta)

        self.app.push_screen(DirPicker(inicio), escolhida)

    @on(Button.Pressed, "#uninstall")
    def _desinstalar(self) -> None:
        self.estado.pasta = self.pasta()
        self.app.push_screen(TelaDesinstalar())

    @on(Button.Pressed, "#retry")
    def _repetir(self) -> None:
        self.query_one("#docker-status", Static).update("Checking Docker…")
        self.verificar_docker()

    def avancar(self) -> None:
        self.estado.pasta = self.pasta()
        self.estado.recarregar()
        self.app.push_screen(TelaServicos())


class TelaServicos(Passo):
    NUMERO = "Step 2 of 4"
    TITULO = "Choose what to set up"
    DICA = "Everything here is optional. Turn on only what you need."
    REGRAS = {
        "ip": inst.validar_ip,
        "tg-users": inst.validar_ids,
        "tg-chat": inst.validar_ids,
        "dc-users": inst.validar_ids,
        "dc-chat": inst.validar_ids,
    }

    def compose(self) -> ComposeResult:
        e = self.estado
        guardado = "Leave blank to keep the current value"
        ip = e.valor("MQTT_BIND")
        ip_ligado = bool(ip) and ip != "127.0.0.1"
        yield from self.cabecalho()
        with VerticalScroll(id="body"):
            yield secao(
                "Connect a sensor through this network",
                "lan",
                ip_ligado,
                campo("This computer's IP address", "ip", ip if ip_ligado else inst.detectar_ip_lan() or ""),
            )
            yield secao(
                "OpenRouter (cloud AI for Hermes)",
                "or",
                bool(e.valor("OPENROUTER_API_KEY")),
                campo("API key", "or-key", segredo=True, dica=guardado if e.valor("OPENROUTER_API_KEY") else ""),
            )
            yield secao(
                "Telegram bot",
                "tg",
                bool(e.valor("TELEGRAM_BOT_TOKEN")),
                campo(
                    "Bot token (from @BotFather)",
                    "tg-token",
                    segredo=True,
                    dica=guardado if e.valor("TELEGRAM_BOT_TOKEN") else "",
                ),
                campo("Your user ID", "tg-users", e.valor("TELEGRAM_ALLOWED_USERS")),
                campo("Chat ID for alerts", "tg-chat", e.valor("TELEGRAM_HOME_CHANNEL")),
            )
            yield secao(
                "Discord bot",
                "dc",
                bool(e.valor("DISCORD_BOT_TOKEN")),
                campo("Bot token", "dc-token", segredo=True, dica=guardado if e.valor("DISCORD_BOT_TOKEN") else ""),
                campo("Your user ID", "dc-users", e.valor("DISCORD_ALLOWED_USERS")),
                campo("Channel ID for alerts", "dc-chat", e.valor("DISCORD_HOME_CHANNEL")),
            )
            if not e.pular_modelo:
                yield Vertical(
                    Horizontal(
                        Label(f"Download the local AI model {inst.MODELO_OLLAMA} (~2 GB)", classes="section-title"),
                        Switch(value=True, id="model"),
                        classes="section-head",
                    ),
                    classes="section",
                )
        yield from self.navegacao()

    @on(Input.Blurred, "#tg-users")
    def _copiar_usuario(self, evento: Input.Blurred) -> None:
        """Em conversa privada, o chat dos alertas é o próprio ID do usuário."""
        chat = self.query_one("#tg-chat", Input)
        if not chat.value:
            chat.value = evento.value.split(",")[0].strip()

    def validar(self) -> bool:
        ok = super().validar()
        faltando = [
            (chave, ident)
            for chave, ident, liga in (
                ("TELEGRAM_BOT_TOKEN", "tg-token", "tg"),
                ("DISCORD_BOT_TOKEN", "dc-token", "dc"),
                ("OPENROUTER_API_KEY", "or-key", "or"),
            )
            if self.query_one(f"#{liga}", Switch).value
            and not self.query_one(f"#{ident}", Input).value
            and not self.estado.valor(chave)
        ]
        for _, ident in faltando:
            self.query_one(f"#{ident}-error", Static).update("This field is required.")
        return ok and not faltando

    def coletar(self) -> tuple[str | None, dict[str, str], bool]:
        """Lê a tela: só entra o que está ligado e foi preenchido."""
        extras: dict[str, str] = dict(self.estado.extras)
        for liga, campos in (
            ("or", {"or-key": "OPENROUTER_API_KEY"}),
            (
                "tg",
                {
                    "tg-token": "TELEGRAM_BOT_TOKEN",
                    "tg-users": "TELEGRAM_ALLOWED_USERS",
                    "tg-chat": "TELEGRAM_HOME_CHANNEL",
                },
            ),
            (
                "dc",
                {
                    "dc-token": "DISCORD_BOT_TOKEN",
                    "dc-users": "DISCORD_ALLOWED_USERS",
                    "dc-chat": "DISCORD_HOME_CHANNEL",
                },
            ),
        ):
            if self.query_one(f"#{liga}", Switch).value:
                for ident, chave in campos.items():
                    valor = self.query_one(f"#{ident}", Input).value.strip()
                    if valor:
                        extras[chave] = valor
        ip = self.query_one("#ip", Input).value.strip() if self.query_one("#lan", Switch).value else None
        modelo = self.query("#model")
        return ip, extras, bool(modelo) and modelo.first(Switch).value

    def avancar(self) -> None:
        ip, extras, modelo = self.coletar()
        self.estado.respostas = inst.Respostas(
            destino=self.estado.pasta, ip_lan=ip, extras=extras, baixar_modelo=modelo
        )
        self.app.push_screen(TelaDispositivo() if self.estado.tem_firmware else TelaRevisao())


def campos_da_rede(n: int, rede: inst.RedeWifi, host: str = "") -> list[Vertical]:
    """Campos de uma rede Wi-Fi do sensor; n é 1 ou 2 (as demais ficam como estão no arquivo)."""
    sufixo = "" if n == 1 else str(n)
    guardada = "Leave blank to keep the current value" if rede.senha else ""
    campos = [
        campo(
            "Wi-Fi network name (2.4 GHz only)",
            f"ssid{sufixo}",
            rede.ssid,
            dica="The name you see in the Wi-Fi list, not an IP address",
        ),
        campo("Wi-Fi password (or your account password)", f"wifi-pass{sufixo}", segredo=True, dica=guardada),
    ]
    if n > 1:
        campos.append(
            campo(
                "This computer's IP address on this network",
                f"host{sufixo}",
                rede.mqtt_host or host,
                dica="Same as above if the server stays on one network",
            )
        )
    campos.append(
        secao(
            "Institutional network with a personal login (WPA2-Enterprise, like eduroam)",
            f"eap{n}",
            rede.institucional,
            campo("Username", f"eap{n}-user", rede.eap_usuario, dica="student@university.edu"),
            campo(
                "Outer identity (optional)",
                f"eap{n}-identity",
                rede.eap_identidade,
                dica="anonymous@university.edu, if your IT team asks for it",
            ),
            campo("Method", f"eap{n}-method", rede.eap_metodo or "PEAP", dica="PEAP or TTLS"),
            campo(
                "CA certificate file (.pem)",
                f"eap{n}-ca",
                rede.ca,
                dica="From your IT team; without it a fake access point could capture the password",
            ),
        )
    )
    return campos


class TelaDispositivo(Passo):
    NUMERO = "Step 3 of 4"
    TITULO = "Set up the device"
    DICA = (
        "Saves the Wi-Fi and server settings used when you flash the ESP32-S3, and the sound model. "
        "The sensor tries each Wi-Fi network until one connects."
    )
    REGRAS = {
        "ssid": inst.validar_ssid,
        "host": inst.validar_ip,
        "eap1-user": inst.validar_usuario_eap,
        "eap1-identity": inst.validar_identidade_eap,
        "eap1-method": inst.validar_metodo_eap,
        "eap1-ca": inst.validar_certificado,
        "ssid2": inst.validar_ssid,
        "host2": inst.validar_ip,
        "eap2-user": inst.validar_usuario_eap,
        "eap2-identity": inst.validar_identidade_eap,
        "eap2-method": inst.validar_metodo_eap,
        "eap2-ca": inst.validar_certificado,
        "ei-path": inst.validar_modelo_ei,
    }

    @property
    def redes_atuais(self) -> list[inst.RedeWifi]:
        return inst.redes_do_env(self.estado.firmware_env)

    def compose(self) -> ComposeResult:
        e = self.estado
        atual = e.firmware_env
        host = e.respostas.ip_lan or atual.get("MQTT_HOST") or inst.detectar_ip_lan() or ""
        redes = self.redes_atuais + [inst.RedeWifi(ssid=""), inst.RedeWifi(ssid="")]
        yield from self.cabecalho()
        with VerticalScroll(id="body"):
            yield secao(
                "Create the device configuration (firmware/.env)",
                "fw",
                True,
                *campos_da_rede(1, redes[0]),
                campo("This computer's IP address", "host", host),
            )
            yield secao(
                "Add a second Wi-Fi network (such as home and university)",
                "net2",
                bool(redes[1].ssid),
                *campos_da_rede(2, redes[1], host),
            )
            yield secao(
                "Add an Edge Impulse sound model to the firmware",
                "ei",
                e.modelo_ei is not None,
                campo(
                    "Model .zip or folder",
                    "ei-path",
                    str(e.modelo_ei or ""),
                    dica="From Edge Impulse: Deployment → Arduino library",
                ),
            )
        yield from self.navegacao()

    def validar(self) -> bool:
        ok = super().validar()
        atuais = {rede.ssid: rede.senha for rede in self.redes_atuais}
        for n, sufixo in ((1, ""), (2, "2")):
            entrada = self.query_one(f"#wifi-pass{sufixo}", Input)
            if not visivel(entrada):
                continue
            ssid = self.query_one(f"#ssid{sufixo}", Input).value.strip()
            institucional = visivel(self.query_one(f"#eap{n}-user", Input))
            guardada = not entrada.value and atuais.get(ssid)
            erro = None if guardada else inst.validar_senha_wifi(entrada.value, institucional)
            self.query_one(f"#wifi-pass{sufixo}-error", Static).update(erro or "")
            ok = ok and not erro
        return ok

    def rede(self, n: int, host: str) -> inst.RedeWifi:
        sufixo = "" if n == 1 else str(n)

        def valor(ident: str) -> str:
            return self.query_one(f"#{ident}", Input).value.strip()

        rede = inst.RedeWifi(ssid=valor(f"ssid{sufixo}"), senha=self.query_one(f"#wifi-pass{sufixo}", Input).value)
        if self.query_one(f"#eap{n}", Switch).value:
            rede.eap_usuario = valor(f"eap{n}-user")
            rede.eap_identidade = valor(f"eap{n}-identity")
            rede.eap_metodo = valor(f"eap{n}-method").upper()
            rede.ca = valor(f"eap{n}-ca")
        if n > 1 and valor(f"host{sufixo}") != host:
            rede.mqtt_host = valor(f"host{sufixo}")
        return rede

    def avancar(self) -> None:
        respostas = self.estado.respostas
        respostas.firmware = None
        if self.query_one("#fw", Switch).value:
            host = self.query_one("#host", Input).value.strip()
            redes = [self.rede(1, host)]
            if self.query_one("#net2", Switch).value:
                redes.append(self.rede(2, host))
            # A terceira e a quarta rede só se configuram no arquivo ou com --wifi; ficam como estão
            redes += self.redes_atuais[2:]
            respostas.firmware = inst.Firmware(redes=redes, host=host)
            # Sem isso, o broker só escutaria o loopback e a placa nunca conectaria
            respostas.ip_lan = respostas.ip_lan or host
        respostas.modelo_ei = None
        if self.query_one("#ei", Switch).value:
            respostas.modelo_ei = Path(self.query_one("#ei-path", Input).value.strip()).expanduser().resolve()
        self.app.push_screen(TelaRevisao())


class TelaRevisao(Passo):
    NUMERO = "Step 4 of 4"
    TITULO = "Review and install"
    DICA = "Check your choices. Secrets stay hidden."
    PROXIMO = "Install"

    def linhas(self) -> list[tuple[str, str]]:
        e = self.estado
        r = e.respostas
        x = r.extras

        def segredo(chave: str) -> str:
            novo = x.get(chave) if x.get(chave) != e.env.get(chave) else ""
            return inst.mascarar(novo or "", e.env.get(chave))

        linhas = [
            ("Install folder", str(r.destino)),
            ("Sensor network address", r.ip_lan or e.env.get("MQTT_BIND") or "This computer only"),
            ("OpenRouter API key", segredo("OPENROUTER_API_KEY")),
            ("Telegram bot token", segredo("TELEGRAM_BOT_TOKEN")),
            ("Telegram user ID", x.get("TELEGRAM_ALLOWED_USERS") or e.env.get("TELEGRAM_ALLOWED_USERS") or "not set"),
            ("Telegram alerts chat", x.get("TELEGRAM_HOME_CHANNEL") or e.env.get("TELEGRAM_HOME_CHANNEL") or "not set"),
            ("Discord bot token", segredo("DISCORD_BOT_TOKEN")),
            ("Local AI model", f"Download {inst.MODELO_OLLAMA}" if r.baixar_modelo else "Skip"),
        ]
        if r.firmware:
            atuais = {rede.ssid: rede.senha for rede in inst.redes_do_env(e.firmware_env)}
            for n, rede in enumerate(r.firmware.redes, start=1):
                tipo = f"institutional, {rede.eap_usuario}" if rede.institucional else "personal"
                servidor = f", server {rede.mqtt_host}" if rede.mqtt_host else ""
                linhas += [
                    (f"Device Wi-Fi network {n}", f"{rede.ssid} ({tipo}{servidor})"),
                    (f"Device Wi-Fi password {n}", inst.mascarar(rede.senha, atuais.get(rede.ssid))),
                ]
            linhas.append(("Device server address", r.firmware.host))
        else:
            linhas.append(("Device configuration", "Skip"))
        if e.tem_firmware:
            linhas.append(("Firmware sound model", str(r.modelo_ei) if r.modelo_ei else "Keep the current one"))
        if e.dry_run:
            linhas.append(("Mode", "Dry run: Docker commands are only shown"))
        return linhas

    def compose(self) -> ComposeResult:
        yield from self.cabecalho()
        with VerticalScroll(id="body"):
            yield DataTable(id="review", show_cursor=False, zebra_stripes=True)
        yield from self.navegacao()

    def on_mount(self) -> None:
        tabela = self.query_one("#review", DataTable)
        tabela.add_columns("Setting", "Value")
        tabela.add_rows(self.linhas())

    def avancar(self) -> None:
        self.app.switch_mode_install()


class TelaDesinstalar(Passo):
    NUMERO = "Uninstall"
    TITULO = "Uninstall ELEX20"
    DICA = "Services always stop and their containers are removed. Choose what else to delete."
    PROXIMO = "Uninstall"

    def compose(self) -> ComposeResult:
        pasta = self.estado.pasta
        inicial = self.estado.remocao or inst.Remocao()
        arquivos = (
            "Delete .env and firmware/.env (the repository stays)"
            if inst.e_repositorio(pasta)
            else "Delete the installed files and .env"
        )
        opcoes = (
            ("Delete all data: history, dashboards, n8n account and passwords", "del-data", inicial.dados),
            ("Delete downloaded Docker images (frees several GB)", "del-images", inicial.imagens),
            (arquivos, "del-files", inicial.arquivos),
        )
        yield from self.cabecalho()
        with VerticalScroll(id="body"):
            yield Static(f"Folder: {pasta}", classes="status")
            yield Static("", id="uninstall-error", classes="field-error")
            for rotulo, ident, ligada in opcoes:
                yield Vertical(
                    Horizontal(Label(rotulo, classes="section-title"), Switch(value=ligada, id=ident)),
                    classes="section section-row",
                )
            yield Static(
                Text("Deleted data cannot be recovered.", style="bold red"), id="delete-warning", classes="status"
            )
            yield campo("Type delete to confirm", "confirm")
        yield from self.navegacao()

    def on_mount(self) -> None:
        self.query_one("#next", Button).variant = "error"
        if len(self.app.screen_stack) <= 2:
            self.query_one("#back").display = False
        self.mostrar_confirmacao()

    def remocao(self) -> inst.Remocao:
        return inst.Remocao(
            dados=self.query_one("#del-data", Switch).value,
            imagens=self.query_one("#del-images", Switch).value,
            arquivos=self.query_one("#del-files", Switch).value,
        )

    def mostrar_confirmacao(self) -> None:
        visivel = self.remocao().exige_confirmacao
        self.query_one("#delete-warning").display = visivel
        self.query_one("#confirm", Input).parent.display = visivel

    @on(Switch.Changed)
    def _opcao_mudou(self) -> None:
        self.mostrar_confirmacao()

    def validar(self) -> bool:
        pasta = self.estado.pasta
        problema = None if inst.instalacao_valida(pasta) else f"No ELEX20 installation found in {pasta}."
        self.query_one("#uninstall-error", Static).update(problema or "")
        entrada = self.query_one("#confirm", Input)
        confirmou = not self.remocao().exige_confirmacao or entrada.value.strip() == "delete"
        self.query_one("#confirm-error", Static).update("" if confirmou else "Type delete to continue.")
        if not confirmou:
            entrada.focus()
        return confirmou and not problema

    def avancar(self) -> None:
        self.app.iniciar_remocao(self.remocao())


class SaidaTui(inst.Saida):
    """Leva a saída do motor, que roda em uma thread, para a tela."""

    def __init__(self, tela: TelaInstalacao):
        self.tela = tela

    def _ui(self, funcao, *args) -> None:
        self.tela.app.call_from_thread(funcao, *args)

    def etapa(self, chave: str, texto: str) -> None:
        self._ui(self.tela.iniciar_etapa, chave, texto)

    def concluir_etapa(self, chave: str, ok: bool = True) -> None:
        self._ui(self.tela.concluir_etapa, chave, ok)

    def info(self, texto: str) -> None:
        self._ui(self.tela.escrever, texto, "")

    def aviso(self, texto: str) -> None:
        self._ui(self.tela.escrever, f"Warning: {texto}", "yellow")

    def erro(self, texto: str) -> None:
        self._ui(self.tela.escrever, f"Error: {texto}", "bold red")

    def detalhe(self, texto: str) -> None:
        self._ui(self.tela.escrever, texto, "dim")


class TelaInstalacao(Screen):
    def __init__(self, estado: Estado, remocao: inst.Remocao | None = None):
        super().__init__()
        self.estado = estado
        self.remocao = remocao
        respostas = estado.respostas or inst.Respostas(destino=estado.pasta)
        self.instalador = inst.Instalador(estado.origem, respostas, estado.dry_run, SaidaTui(self))
        self.etapas = self.instalador.etapas_da_remocao(remocao) if remocao else self.instalador.etapas()
        self.linhas: list[Text] = []

    def compose(self) -> ComposeResult:
        yield Static(inst.titulo_do_instalador(), id="banner")
        yield Static("Uninstalling" if self.remocao else "Installing", id="step")
        yield Static("Removing ELEX20" if self.remocao else "Installing ELEX20", id="heading")
        yield Static("Keep this window open. This can take several minutes.", id="hint")
        yield ProgressBar(total=len(self.etapas), id="bar", show_eta=False)
        with Horizontal(id="progress-area"):
            with Vertical(id="step-list"):
                for chave, texto in self.etapas:
                    yield Static(f"○ {texto}", id=f"s-{chave}")
            yield RichLog(id="step-log", wrap=True, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        self.instalar()

    @work(thread=True, exclusive=True)
    def instalar(self) -> None:
        try:
            if self.remocao:
                codigo = self.instalador.desinstalar(self.remocao)
            else:
                codigo = self.instalador.executar()
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            self.instalador.saida.erro(str(exc))
            codigo = 1
        self.app.call_from_thread(self.app.terminar, codigo, self.instalador.resumo)

    def iniciar_etapa(self, chave: str, texto: str) -> None:
        self.query_one(f"#s-{chave}", Static).update(Text(f"◐ {texto}", style="bold"))
        self.escrever(texto, "bold")

    def concluir_etapa(self, chave: str, ok: bool) -> None:
        texto = dict(self.etapas)[chave]
        marca = Text(f"✔ {texto}", style="green") if ok else Text(f"✖ {texto}", style="red")
        self.query_one(f"#s-{chave}", Static).update(marca)
        self.query_one("#bar", ProgressBar).advance(1)

    def escrever(self, texto: str, estilo: str) -> None:
        linha = Text(texto, style=estilo)
        self.linhas.append(linha)
        self.query_one("#step-log", RichLog).write(linha)


class TelaFim(Screen):
    BINDINGS = [Binding("enter", "sair", "Exit"), Binding("q", "sair", "Exit")]

    def __init__(self, codigo: int, resumo: dict | None, remocao: bool = False):
        super().__init__()
        self.codigo = codigo
        self.resumo = resumo
        self.remocao = remocao

    def compose(self) -> ComposeResult:
        ok = self.codigo == 0
        if self.remocao:
            titulo = "ELEX20 is uninstalled" if ok else "The removal did not finish"
        else:
            titulo = "ELEX20 is installed" if ok else "The installation did not finish"
        yield Static(inst.titulo_do_instalador(), id="banner")
        yield Static("Finished", id="step")
        yield Static(Text(titulo, style="green" if ok else "red"), id="heading")
        if self.codigo == 2:
            dica = "The services are running, but n8n needs attention. Run the installer again."
        else:
            dica = (
                f"Folder: {self.resumo['folder']}" if self.resumo else "Check the log, fix the problem and try again."
            )
        yield Static(dica, id="hint")
        with VerticalScroll(id="body"):
            if self.resumo:
                if self.resumo["services"]:
                    yield Label("Services", classes="table-title")
                    yield DataTable(id="services", show_cursor=False, zebra_stripes=True)
                    yield Label("Device settings", classes="table-title")
                    yield DataTable(id="device", show_cursor=False, zebra_stripes=True)
                yield Label("Notes", classes="table-title")
                yield Static("\n".join(f"• {nota}" for nota in self.resumo["notes"]))
            else:
                yield RichLog(id="final-log", wrap=True)
        with Horizontal(id="nav"):
            yield Button("Exit", id="next", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        if self.resumo and self.resumo["services"]:
            servicos = self.query_one("#services", DataTable)
            servicos.add_columns("Service", "Address", "User", "Password")
            servicos.add_rows(self.resumo["services"])
            dispositivo = self.query_one("#device", DataTable)
            dispositivo.add_columns("Setting", "Value")
            dispositivo.add_rows(self.resumo["device"])
        elif not self.resumo:
            registro = self.query_one("#final-log", RichLog)
            for linha in self.app.registro_final:
                registro.write(linha)

    @on(Button.Pressed, "#next")
    def action_sair(self) -> None:
        self.app.exit((self.codigo, self.resumo))


class InstaladorApp(App[tuple[int, dict | None]]):
    CSS = CSS
    TITLE = "ELEX20 installer"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+q", "sair", "Quit", show=True, priority=True)]

    def __init__(self, estado: Estado):
        super().__init__()
        self.estado = estado
        self.pediu_sair = False
        self.registro_final: list[Text] = []

    def on_mount(self) -> None:
        self.push_screen(TelaDesinstalar() if self.estado.remocao else TelaPasta())

    def switch_mode_install(self) -> None:
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(TelaInstalacao(self.estado))

    def iniciar_remocao(self, remocao: inst.Remocao) -> None:
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(TelaInstalacao(self.estado, remocao))

    def terminar(self, codigo: int, resumo: dict | None) -> None:
        tela = self.screen
        if isinstance(tela, TelaInstalacao):
            self.registro_final = tela.linhas
        self.switch_screen(TelaFim(codigo, resumo, isinstance(tela, TelaInstalacao) and tela.remocao is not None))

    def action_sair(self) -> None:
        tela = self.screen
        if isinstance(tela, TelaInstalacao) and not self.pediu_sair:
            self.pediu_sair = True
            self.notify("The installation is running. Press Ctrl+Q again to stop it.", severity="warning")
            return
        if isinstance(tela, TelaInstalacao):
            tela.instalador.cancelar()
        self.exit((130, None))


def executar(
    origem: Path,
    pasta: Path | None,
    padrao: Path,
    extras: dict[str, str],
    pular_modelo: bool,
    dry_run: bool,
    remocao: inst.Remocao | None = None,
    modelo_ei: Path | None = None,
) -> tuple[int, dict | None]:
    estado = Estado(
        origem=origem,
        pasta=(pasta or padrao).expanduser().resolve(),
        extras=extras,
        pular_modelo=pular_modelo,
        dry_run=dry_run,
        pasta_fixa=pasta is not None,
        remocao=remocao,
        modelo_ei=modelo_ei,
    )
    return InstaladorApp(estado).run() or (130, None)


def verificar() -> None:
    """Percorre as telas do assistente sem terminal; falha se faltar algo no executável."""

    async def percorrer() -> None:
        estado = Estado(origem=Path.cwd(), pasta=Path.cwd(), extras={}, pular_modelo=False, dry_run=True)
        estado.respostas = inst.Respostas(destino=Path.cwd())
        app = InstaladorApp(estado)
        async with app.run_test() as piloto:
            await piloto.pause()
            for tela in (TelaServicos(), TelaDispositivo(), TelaRevisao(), TelaDesinstalar()):
                app.push_screen(tela)
                await piloto.pause()
            app.push_screen(TelaFim(0, inst.dados_do_resumo({}, Path.cwd())))
            await piloto.pause()

    asyncio.run(percorrer())
