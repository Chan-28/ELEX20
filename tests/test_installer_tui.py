"""Testes da interface em tela cheia do instalador, sem terminal (modo simulação do Docker)."""

import asyncio
from pathlib import Path

import pytest

textual = pytest.importorskip("textual")

import elex_installer as inst  # noqa: E402
import elex_tui as tui  # noqa: E402
from textual.widgets import Input, Static, Switch  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def montar(tmp_path, firmware=True, env=""):
    pasta = tmp_path / "ELEX20"
    inst.copiar_projeto(RAIZ, pasta)
    if firmware:
        (pasta / "firmware").mkdir()
        (pasta / "firmware" / "platformio.ini").write_text("", encoding="utf-8")
    if env:
        (pasta / ".env").write_text(env, encoding="utf-8")
    return tui.Estado(origem=pasta, pasta=pasta, extras={}, pular_modelo=True, dry_run=True)


def rodar(cenario, estado):
    async def principal():
        app = tui.InstaladorApp(estado)
        async with app.run_test(size=(100, 60)) as piloto:
            await espera_tela(app, piloto, tui.TelaPasta)
            await espera(piloto, lambda: not app.screen.query_one("#next").disabled)
            await cenario(app, piloto)
        return app

    return asyncio.run(principal())


async def espera(piloto, condicao):
    for _ in range(200):
        await piloto.pause(0.02)
        if condicao():
            return
    raise AssertionError("tempo esgotado")


async def espera_tela(app, piloto, classe):
    # app.screen já aponta para a tela nova antes de ela montar os filhos; o
    # botão #next vem por último no compose de todas as telas.
    await espera(piloto, lambda: isinstance(app.screen, classe) and app.screen.query("#next"))


async def proximo(app, piloto, classe):
    app.screen.query_one("#next").press()
    await espera_tela(app, piloto, classe)


async def ate_o_wifi(app, piloto):
    await proximo(app, piloto, tui.TelaServicos)
    await proximo(app, piloto, tui.TelaDispositivo)


def test_ip_no_campo_do_wifi_nao_avanca(tmp_path):
    async def cenario(app, piloto):
        await ate_o_wifi(app, piloto)
        app.screen.query_one("#ssid", Input).value = "192.168.0.10"
        app.screen.query_one("#wifi-pass", Input).value = "12345678"
        app.screen.query_one("#host", Input).value = "192.168.0.10"
        app.screen.query_one("#next").press()
        await piloto.pause(0.1)
        assert isinstance(app.screen, tui.TelaDispositivo)
        assert "IP address" in str(app.screen.query_one("#ssid-error", Static).render())

    rodar(cenario, montar(tmp_path))


def test_fluxo_completo_grava_as_respostas(tmp_path):
    estado = montar(tmp_path)

    async def cenario(app, piloto):
        await proximo(app, piloto, tui.TelaServicos)
        app.screen.query_one("#tg", Switch).value = True
        await piloto.pause()
        app.screen.query_one("#tg-token", Input).value = "token-secreto"
        app.screen.query_one("#tg-users", Input).value = "123456"
        app.screen.query_one("#tg-chat", Input).value = "123456"
        await proximo(app, piloto, tui.TelaDispositivo)
        app.screen.query_one("#ssid", Input).value = "Casa"
        app.screen.query_one("#wifi-pass", Input).value = "senha-do-wifi"
        app.screen.query_one("#host", Input).value = "192.168.0.10"
        await proximo(app, piloto, tui.TelaRevisao)
        tela = "".join(str(c) for linha in app.screen.linhas() for c in linha)
        assert "token-secreto" not in tela
        assert "senha-do-wifi" not in tela
        await proximo(app, piloto, tui.TelaFim)
        assert app.screen.codigo == 0

    rodar(cenario, estado)
    env = inst.ler_env((estado.pasta / ".env").read_text(encoding="utf-8"))
    assert env["TELEGRAM_BOT_TOKEN"] == "token-secreto"
    assert env["MQTT_BIND"] == "192.168.0.10"
    firmware = inst.ler_env((estado.pasta / "firmware" / ".env").read_text(encoding="utf-8"))
    assert firmware["WIFI_SSID"] == "Casa"


def test_instalacao_existente_mantem_os_segredos(tmp_path):
    estado = montar(tmp_path, firmware=False, env="TELEGRAM_BOT_TOKEN=antigo\nMQTT_BIND=192.168.0.10\n")

    async def cenario(app, piloto):
        await proximo(app, piloto, tui.TelaServicos)
        assert app.screen.query_one("#tg", Switch).value
        assert app.screen.query_one("#ip", Input).value == "192.168.0.10"
        app.screen.query_one("#tg-users", Input).value = "1"
        app.screen.query_one("#tg-chat", Input).value = "1"
        await proximo(app, piloto, tui.TelaRevisao)
        assert ("Telegram bot token", "•••••• (unchanged)") in app.screen.linhas()
        await proximo(app, piloto, tui.TelaFim)

    rodar(cenario, estado)
    assert inst.ler_env((estado.pasta / ".env").read_text(encoding="utf-8"))["TELEGRAM_BOT_TOKEN"] == "antigo"


def test_falha_mostra_o_registro(tmp_path, monkeypatch):
    def falhar(self):
        self.saida.erro("docker compose failed.")
        return False

    monkeypatch.setattr(inst.Instalador, "subir_stack", falhar)

    async def cenario(app, piloto):
        await proximo(app, piloto, tui.TelaServicos)
        await proximo(app, piloto, tui.TelaRevisao)
        await proximo(app, piloto, tui.TelaFim)
        assert app.screen.codigo == 1
        assert app.screen.query("#final-log")

    rodar(cenario, montar(tmp_path, firmware=False))


def test_sem_docker_nao_avanca(tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "checar_docker", lambda: (False, "Docker is not installed."))
    monkeypatch.setattr(inst, "como_instalar_docker", lambda: ["install it"])
    estado = montar(tmp_path, firmware=False)
    estado.dry_run = False

    async def principal():
        app = tui.InstaladorApp(estado)
        async with app.run_test() as piloto:
            await espera_tela(app, piloto, tui.TelaPasta)
            await espera(piloto, lambda: app.screen.query_one("#retry").display)
            assert app.screen.query_one("#next").disabled

    asyncio.run(principal())


def test_desinstalar_pela_tela_exige_digitar_delete(tmp_path):
    estado = montar(tmp_path, firmware=False, env="A=1\n")
    (estado.pasta / "hermes_data").mkdir()

    async def cenario(app, piloto):
        assert app.screen.query_one("#uninstall").display
        app.screen.query_one("#uninstall").press()
        await espera_tela(app, piloto, tui.TelaDesinstalar)
        await espera(piloto, lambda: not app.screen.query_one("#delete-warning").display)
        app.screen.query_one("#del-data", Switch).value = True
        await piloto.pause()
        assert app.screen.query_one("#delete-warning").display
        app.screen.query_one("#next").press()
        await piloto.pause(0.1)
        assert isinstance(app.screen, tui.TelaDesinstalar)
        app.screen.query_one("#confirm", Input).value = "delete"
        await proximo(app, piloto, tui.TelaFim)
        assert app.screen.codigo == 0

    rodar(cenario, estado)
    assert (estado.pasta / ".env").is_file()
    assert (estado.pasta / "hermes_data").is_dir()


def test_desinstalar_sem_apagar_nao_pede_confirmacao(tmp_path):
    estado = montar(tmp_path, firmware=False, env="A=1\n")

    async def cenario(app, piloto):
        app.screen.query_one("#uninstall").press()
        await espera_tela(app, piloto, tui.TelaDesinstalar)
        await proximo(app, piloto, tui.TelaFim)
        assert app.screen.resumo["title"] == "ELEX20 uninstalled"

    rodar(cenario, estado)


def test_instalacao_nova_nao_mostra_desinstalar(tmp_path):
    async def cenario(app, _piloto):
        assert not app.screen.query_one("#uninstall").display

    rodar(cenario, montar(tmp_path, firmware=False))


def test_flag_uninstall_abre_direto_na_tela_de_remocao(tmp_path):
    estado = montar(tmp_path, firmware=False, env="A=1\n")
    estado.remocao = inst.Remocao(dados=True)

    async def principal():
        app = tui.InstaladorApp(estado)
        async with app.run_test(size=(100, 60)) as piloto:
            await espera_tela(app, piloto, tui.TelaDesinstalar)
            assert app.screen.query_one("#del-data", Switch).value
            assert not app.screen.query_one("#back").display

    asyncio.run(principal())


def test_modelo_do_edge_impulse_entra_no_firmware(tmp_path):
    estado = montar(tmp_path)
    exportacao = tmp_path / "Meu_Modelo_inferencing"
    (exportacao / "src").mkdir(parents=True)
    (exportacao / "library.properties").write_text("name=Meu_Modelo_inferencing\n", encoding="utf-8")
    (exportacao / "src" / "Meu_Modelo_inferencing.h").write_text("", encoding="utf-8")

    async def cenario(app, piloto):
        await ate_o_wifi(app, piloto)
        app.screen.query_one("#fw", Switch).value = False
        app.screen.query_one("#ei", Switch).value = True
        await piloto.pause()
        app.screen.query_one("#ei-path", Input).value = str(tmp_path / "nada.zip")
        app.screen.query_one("#next").press()
        await piloto.pause(0.1)
        assert "does not exist" in str(app.screen.query_one("#ei-path-error", Static).render())
        app.screen.query_one("#ei-path", Input).value = str(exportacao)
        await proximo(app, piloto, tui.TelaRevisao)
        assert ("Firmware sound model", str(exportacao)) in app.screen.linhas()
        await proximo(app, piloto, tui.TelaFim)
        assert app.screen.codigo == 0

    rodar(cenario, estado)
    assert (estado.pasta / "firmware" / "lib" / "ei-model" / "Meu_Modelo_inferencing" / "library.properties").is_file()
