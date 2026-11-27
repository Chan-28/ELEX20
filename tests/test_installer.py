"""Testes do instalador multiplataforma (installer/elex_installer.py)."""

import json
import re
import shutil
from pathlib import Path

import elex_installer as inst
import pytest

RAIZ = Path(__file__).resolve().parent.parent


def test_ler_env_ignora_comentarios_e_remove_aspas():
    texto = "# comentário\nA=1\n\nB='dois palavras'\nC=\"x\"\nD=\nsem_igual\n"
    assert inst.ler_env(texto) == {"A": "1", "B": "dois palavras", "C": "x", "D": ""}


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("abc123", "abc123"), ("com espaço", "'com espaço'"), ("a#b", "'a#b'"), ("$HOME", "'$HOME'")],
)
def test_formatar_valor_env(valor, esperado):
    assert inst.formatar_valor_env(valor) == esperado


def test_formatar_valor_env_recusa_quebra_de_linha():
    with pytest.raises(ValueError, match="line break"):
        inst.formatar_valor_env("a\nb")


def test_aplicar_env_preserva_comentarios_e_ordem_e_acrescenta_chaves_novas():
    modelo = "# topo\nA=\n# meio\nB=velho\nC=3\n"
    saida = inst.aplicar_env(modelo, {"B": "novo", "A": "1", "Z": "fim"})
    assert saida == "# topo\nA=1\n# meio\nB=novo\nC=3\nZ=fim\n"


def test_instalacao_nova_so_randomiza_a_senha_interna_do_banco_e_mantem_os_placeholders_de_login():
    modelo = inst.ler_env((RAIZ / ".env.example").read_text(encoding="utf-8"))
    valores = inst.montar_valores({}, modelo, "Linux", None, {})
    assert re.fullmatch(r"[0-9a-f]{48}", valores["POSTGRES_PASSWORD"])
    # logins que o usuário digita ficam com admin/password; segredos internos não são do instalador
    for chave in ("GRAFANA_ADMIN_PASSWORD", "HERMES_DASHBOARD_PASS", *inst.SEGREDOS_AUTOMATICOS.values()):
        assert chave not in valores


def test_banco_ja_existente_sem_env_nao_troca_a_senha_padrao():
    modelo = inst.ler_env((RAIZ / ".env.example").read_text(encoding="utf-8"))
    valores = inst.montar_valores({}, modelo, "Linux", None, {}, banco_ja_existe=True)
    assert "POSTGRES_PASSWORD" not in valores


def test_env_existente_nunca_tem_valores_trocados():
    modelo = inst.ler_env((RAIZ / ".env.example").read_text(encoding="utf-8"))
    existente = {"POSTGRES_PASSWORD": "password", "COMPOSE_PROFILES": ""}
    assert inst.montar_valores(existente, modelo, "Linux", None, {}) == {}


def test_env_existente_so_completa_o_que_falta():
    modelo = inst.ler_env((RAIZ / ".env.example").read_text(encoding="utf-8"))
    assert set(inst.montar_valores({"POSTGRES_PASSWORD": "x"}, modelo, "Linux", None, {})) == {"COMPOSE_PROFILES"}


def test_segredos_automaticos_batem_com_o_secrets_init_e_o_compose():
    script = (RAIZ / "init" / "secrets-init.sh").read_text(encoding="utf-8")
    compose = (RAIZ / "docker-compose.yaml").read_text(encoding="utf-8")
    for nome, variavel in inst.SEGREDOS_AUTOMATICOS.items():
        assert f"{nome}:{variavel}" in script, f"{nome} fora do secrets-init.sh"
        assert f"sec_{nome}:/secrets/{nome}" in compose, f"{nome} sem volume no secrets-init"
        assert f"sec_{nome}:" in compose.split("\nvolumes:\n", 1)[1], f"volume sec_{nome} não declarado"
    # nenhuma variável do .env é mais obrigatória para subir a stack
    assert ":?" not in compose


@pytest.mark.parametrize(("sistema", "perfil"), [("Linux", "logs"), ("Darwin", ""), ("Windows", "")])
def test_coleta_de_logs_so_no_linux(sistema, perfil):
    valores = inst.montar_valores({}, {}, sistema, None, {})
    assert valores["COMPOSE_PROFILES"] == perfil


def test_ip_da_rede_e_extras_vao_para_o_env_e_extras_vazios_sao_ignorados():
    valores = inst.montar_valores({}, {}, "Linux", "192.168.0.10", {"TELEGRAM_BOT_TOKEN": "t", "DISCORD_BOT_TOKEN": ""})
    assert valores["MQTT_BIND"] == "192.168.0.10"
    assert valores["TELEGRAM_BOT_TOKEN"] == "t"
    assert "DISCORD_BOT_TOKEN" not in valores


def test_normalizar_texto_troca_crlf_por_lf():
    assert inst.normalizar_texto(b"a\r\nb\r\n") == b"a\nb\n"


OS_RELEASE = {
    "ubuntu": 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n',
    "mint": 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n',
    "debian": "ID=debian\n",
    "fedora": "ID=fedora\n",
    "rocky": 'ID="rocky"\nID_LIKE="rhel centos fedora"\n',
    "arch": "ID=arch\n",
    "manjaro": "ID=manjaro\nID_LIKE=arch\n",
    "opensuse": 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
}


@pytest.mark.parametrize(
    ("chave", "contem"),
    [
        ("ubuntu", "get.docker.com"),
        ("mint", "get.docker.com"),
        ("debian", "get.docker.com"),
        ("fedora", "get.docker.com"),
        ("rocky", "get.docker.com"),
        ("arch", "pacman -S docker"),
        ("manjaro", "pacman -S docker"),
        ("opensuse", "zypper install docker"),
    ],
)
def test_instrucoes_de_docker_por_distro(chave, contem):
    distro, parecidas = inst.detectar_distro(OS_RELEASE[chave])
    texto = "\n".join(inst.instrucoes_docker("Linux", distro, parecidas))
    assert contem in texto
    assert "usermod -aG docker" in texto


def test_instrucoes_de_docker_windows_mac_e_distro_desconhecida():
    assert "WSL 2" in "\n".join(inst.instrucoes_docker("Windows"))
    assert "Docker Desktop" in "\n".join(inst.instrucoes_docker("Darwin"))
    assert "docs.docker.com/engine/install" in "\n".join(inst.instrucoes_docker("Linux", "gentoo", []))


def test_credenciais_batem_com_o_que_os_workflows_referenciam():
    creds = inst.credenciais_n8n({"MQTT_N8N_PASS": "m", "N8N_DB_PASSWORD": "p", "POSTGRES_DB": "meubanco"})
    por_id = {c["id"]: c for c in creds}
    assert por_id["elex-postgres"]["data"]["database"] == "meubanco"
    assert por_id["elex-postgres"]["data"]["password"] == "p"
    assert por_id["elex-mqtt"]["data"]["username"] == "n8n"

    usados, ids_de_workflow = set(), set()
    for arquivo in (RAIZ / "n8n" / "workflows").glob("*.json"):
        wf = json.loads(arquivo.read_text(encoding="utf-8"))
        ids_de_workflow.add(wf["id"])
        for no in wf["nodes"]:
            for cred in no.get("credentials", {}).values():
                usados.add((cred["id"], cred["name"]))
    assert usados  # os workflows usam credenciais
    for cid, nome in usados:
        assert por_id[cid]["name"] == nome
    assert ids_de_workflow == set(inst.WORKFLOWS_N8N)


@pytest.mark.parametrize("valor", [None, "", "password"])
def test_descrever_senha_mostra_o_placeholder(valor):
    assert "password" in inst.descrever_senha(valor)


def test_descrever_senha_nunca_mostra_senha_real():
    assert "s3gr3d0" not in inst.descrever_senha("s3gr3d0")


def test_nome_do_projeto_segue_a_regra_do_compose():
    assert inst.nome_do_projeto(Path("/x/ELEX 20!")) == "elex20"


def test_copiar_projeto_leva_tudo_que_o_compose_monta(tmp_path):
    inst.copiar_projeto(RAIZ, tmp_path)
    compose = (RAIZ / "docker-compose.yaml").read_text(encoding="utf-8")
    montagens = re.findall(r"^\s+- (\./[^:\s]+):", compose, flags=re.MULTILINE)
    assert montagens
    for caminho in montagens:
        if caminho.startswith("./hermes_data"):  # criado pelo próprio compose
            continue
        assert (tmp_path / caminho).exists(), f"o instalador não copia {caminho}"
    assert (tmp_path / ".env.example").exists()
    assert not list(tmp_path.rglob("__pycache__"))


def test_copiar_projeto_normaliza_crlf(tmp_path):
    origem = tmp_path / "origem"
    (origem / "mosquitto").mkdir(parents=True)
    (origem / "mosquitto" / "entrypoint.sh").write_bytes(b"#!/bin/sh\r\nexec true\r\n")
    (origem / "docker-compose.yaml").write_bytes(b"services:\r\n")
    destino = tmp_path / "destino"
    inst.copiar_projeto(origem, destino)
    assert (destino / "mosquitto" / "entrypoint.sh").read_bytes() == b"#!/bin/sh\nexec true\n"
    assert (destino / "docker-compose.yaml").read_bytes() == b"services:\n"


def test_main_recusa_set_mal_formado():
    with pytest.raises(SystemExit):
        inst.main(["--set", "SEM_IGUAL", "--dry-run"])


def test_versao_de_release_vem_do_arquivo(tmp_path, monkeypatch):
    (tmp_path / "version.txt").write_text("1.4.2\n", encoding="utf-8")
    monkeypatch.setattr(inst, "__file__", str(tmp_path / "elex_installer.py"))
    assert inst.ler_versao() == "1.4.2"


def test_versao_de_desenvolvimento_usa_a_ultima_tag(tmp_path, monkeypatch):
    (tmp_path / "version.txt").write_text("0.0.0-dev\n", encoding="utf-8")
    monkeypatch.setattr(inst, "__file__", str(tmp_path / "elex_installer.py"))
    monkeypatch.setattr(inst, "versao_do_git", lambda _: "1.0.0")
    assert inst.ler_versao() == "1.0.0"
    monkeypatch.setattr(inst, "versao_do_git", lambda _: None)
    assert inst.ler_versao() == "dev"


@pytest.mark.parametrize(
    ("sistema", "esperado"), [("Linux", "(Linux)"), ("Darwin", "(macOS)"), ("Windows", "(Windows)")]
)
def test_titulo_tem_versao_e_sistema(sistema, esperado):
    assert inst.titulo_do_instalador("1.4.2", sistema) == f"ELEX20 — installer 1.4.2 {esperado}"


@pytest.mark.parametrize("valor", ["192.168.0.10", "", " ", "x" * 33])
def test_ssid_invalido(valor):
    assert inst.validar_ssid(valor)


def test_ssid_valido():
    assert inst.validar_ssid("Casa 2.4 GHz") is None


@pytest.mark.parametrize("valor", ["abc", "", "0.0.0.0", "127.0.0.1", "192.168.0"])  # noqa: S104 (valor recusado)
def test_ip_invalido(valor):
    assert inst.validar_ip(valor)


def test_ip_valido():
    assert inst.validar_ip("192.168.0.10") is None


@pytest.mark.parametrize(("valor", "ok"), [("123", True), ("-100, 200", True), ("abc", False), ("", False)])
def test_ids(valor, ok):
    assert (inst.validar_ids(valor) is None) is ok


def test_senha_wifi():
    assert inst.validar_senha_wifi("curta")
    assert inst.validar_senha_wifi("12345678") is None


def test_pasta_nao_pode_ser_arquivo(tmp_path):
    arquivo = tmp_path / "x"
    arquivo.write_text("", encoding="utf-8")
    assert inst.validar_pasta(str(arquivo))
    assert inst.validar_pasta(str(tmp_path / "nova" / "pasta")) is None


def test_mascarar_nunca_mostra_o_segredo():
    assert "s3gr3d0" not in inst.mascarar("s3gr3d0")
    assert inst.mascarar("", "antigo") == "•••••• (unchanged)"
    assert inst.mascarar("") == "not set"


def test_resumo_nao_traz_senha_real():
    assert "s3gr3d0" not in str(inst.dados_do_resumo({"GRAFANA_ADMIN_PASSWORD": "s3gr3d0"}, Path("/x")))


def test_nao_interativo_roda_em_ingles_e_cria_os_arquivos(tmp_path, capsys):
    assert inst.main(["-y", "--dry-run", "--skip-model", "--dir", str(tmp_path / "ELEX20")]) == 0
    saida = capsys.readouterr().out
    assert saida.startswith("ELEX20 — installer ")
    assert "Check Docker" in saida
    assert "ELEX20 installed" in saida
    assert (tmp_path / "ELEX20" / ".env").is_file()


def test_versao_do_textual_e_a_mesma_nos_scripts_e_no_build():
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    versao = re.search(r'"(textual==[^"]+)"', pyproject).group(1)
    for arquivo in ("install.sh", "install.bat", ".github/workflows/installer-build.yml"):
        assert versao in (RAIZ / arquivo).read_text(encoding="utf-8"), arquivo


class SaidaMuda(inst.Saida):
    def __init__(self):
        self.linhas = []

    def etapa(self, _chave, texto):
        self.linhas.append(texto)

    def info(self, texto):
        self.linhas.append(texto)

    def aviso(self, texto):
        self.linhas.append(texto)

    def erro(self, texto):
        self.linhas.append(texto)

    def detalhe(self, texto):
        self.linhas.append(texto)


def instalacao_copiada(pasta):
    inst.copiar_projeto(RAIZ, pasta)
    (pasta / ".env").write_text("A=1\n", encoding="utf-8")
    return pasta


@pytest.mark.parametrize(
    ("remocao", "presentes", "ausentes"),
    [
        (inst.Remocao(), ["down", "--remove-orphans"], ["--volumes", "--rmi"]),
        (inst.Remocao(dados=True), ["--volumes"], ["--rmi"]),
        (inst.Remocao(imagens=True), ["--rmi all"], ["--volumes"]),
    ],
)
def test_desinstalar_so_apaga_volumes_quando_pedido(tmp_path, remocao, presentes, ausentes):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    saida = SaidaMuda()
    assert inst.Instalador(RAIZ, inst.Respostas(destino=pasta), True, saida).desinstalar(remocao) == 0
    texto = "\n".join(saida.linhas)
    for trecho in presentes:
        assert trecho in texto
    for trecho in ausentes:
        assert trecho not in texto


def test_simulacao_de_remocao_nao_apaga_arquivos(tmp_path):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    (pasta / "hermes_data").mkdir()
    remocao = inst.Remocao(dados=True, arquivos=True)
    assert inst.Instalador(RAIZ, inst.Respostas(destino=pasta), True, SaidaMuda()).desinstalar(remocao) == 0
    assert (pasta / ".env").is_file()
    assert (pasta / "hermes_data").is_dir()


def test_desinstalar_recusa_pasta_que_nao_e_do_elex20(tmp_path):
    (tmp_path / "foto.jpg").write_text("x", encoding="utf-8")
    remocao = inst.Remocao(dados=True, arquivos=True)
    assert inst.Instalador(RAIZ, inst.Respostas(destino=tmp_path), True, SaidaMuda()).desinstalar(remocao) == 1
    assert (tmp_path / "foto.jpg").exists()


def test_remover_arquivos_preserva_o_que_nao_e_do_instalador(tmp_path):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    (pasta / "meu-arquivo.txt").write_text("x", encoding="utf-8")
    inst.remover_arquivos(pasta, SaidaMuda())
    assert sorted(p.name for p in pasta.iterdir()) == ["meu-arquivo.txt"]


def test_remover_arquivos_apaga_a_pasta_que_ficou_vazia(tmp_path):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    inst.remover_arquivos(pasta, SaidaMuda())
    assert not pasta.exists()


def test_apagar_arquivos_mantem_o_env_se_os_dados_ficam(tmp_path):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    inst.remover_arquivos(pasta, SaidaMuda(), manter_env=True)
    assert [p.name for p in pasta.iterdir()] == [".env"]


def test_remover_arquivos_nao_toca_no_repositorio(tmp_path):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    (pasta / ".git").mkdir()
    (pasta / "firmware").mkdir()
    (pasta / "firmware" / ".env").write_text("WIFI_PASS=x\n", encoding="utf-8")
    inst.remover_arquivos(pasta, SaidaMuda())
    assert not (pasta / ".env").exists()
    assert not (pasta / "firmware" / ".env").exists()
    assert (pasta / "docker-compose.yaml").is_file()
    assert (pasta / ".git").is_dir()


def test_remover_arquivos_nao_segue_link_para_fora(tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "importante.txt").write_text("x", encoding="utf-8")
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    shutil.rmtree(pasta / "grafana")
    (pasta / "grafana").symlink_to(fora, target_is_directory=True)
    inst.remover_arquivos(pasta, SaidaMuda())
    assert (fora / "importante.txt").exists()


def test_flags_de_apagar_exigem_uninstall():
    with pytest.raises(SystemExit):
        inst.main(["--delete-data", "--dry-run", "-y"])


def test_uninstall_nao_interativo_sem_flags_mantem_os_dados(tmp_path, capsys):
    pasta = instalacao_copiada(tmp_path / "ELEX20")
    assert inst.main(["--uninstall", "-y", "--dry-run", "--dir", str(pasta)]) == 0
    saida = capsys.readouterr().out
    assert "--volumes" not in saida
    assert "ELEX20 uninstalled" in saida
    assert "Your data stays in Docker volumes." in saida


def test_n8n_despublica_antes_de_publicar_para_destravar_gatilho(tmp_path, monkeypatch):
    """Gatilho que falhou ao ativar só volta se o workflow for despublicado e publicado de novo."""
    chamadas = []

    def compose(_self, *args, check=True, **_kw):
        chamadas.append((args, check))

    monkeypatch.setattr(inst.Instalador, "compose", compose)
    monkeypatch.setattr(inst.Instalador, "ler_segredo", lambda *_a: "x")
    instalador = inst.Instalador(RAIZ, inst.Respostas(destino=tmp_path), False, SaidaMuda())
    assert instalador.provisionar_n8n({})
    comandos = [
        (a[4], a[5] if len(a) > 5 else None, check) for a, check in chamadas if a[:4] == ("exec", "-T", "n8n", "n8n")
    ]
    for wid in inst.WORKFLOWS_N8N:
        despublicar = comandos.index(("unpublish:workflow", f"--id={wid}", False))
        assert comandos.index(("publish:workflow", f"--id={wid}", True)) == despublicar + 1
    assert chamadas[-1][0] == ("restart", "n8n")


PEM_FALSO = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def test_env_do_firmware_grava_varias_redes(tmp_path, monkeypatch):
    """Senha em branco mantém a da mesma rede; o certificado vai para firmware/."""
    monkeypatch.setattr(inst.Instalador, "ler_segredo", lambda *_a: "segredo")
    arquivo = tmp_path / "firmware" / ".env"
    arquivo.parent.mkdir()
    arquivo.write_text("WIFI_SSID=Casa\nWIFI_PASS=senha-de-casa\nOUTRA=x\n", encoding="utf-8")
    ca = tmp_path / "baixado.pem"
    ca.write_text(PEM_FALSO, encoding="utf-8")
    redes = [
        inst.RedeWifi("Casa"),
        inst.RedeWifi(
            "eduroam", "minha-senha", eap_usuario="aluno@univ.br", eap_metodo="ttls", ca=str(ca), mqtt_host="10.1.0.9"
        ),
    ]
    respostas = inst.Respostas(destino=tmp_path, firmware=inst.Firmware(redes, "192.168.0.5"))
    inst.Instalador(RAIZ, respostas, False, SaidaMuda()).gerar_env_firmware()
    env = inst.ler_env(arquivo.read_text(encoding="utf-8"))
    assert env == {
        "WIFI_SSID": "Casa",
        "WIFI_PASS": "senha-de-casa",
        "WIFI2_SSID": "eduroam",
        "WIFI2_PASS": "minha-senha",
        "WIFI2_EAP_USER": "aluno@univ.br",
        "WIFI2_EAP_METHOD": "TTLS",
        "WIFI2_EAP_CA_FILE": "wifi-ca-2.pem",
        "WIFI2_MQTT_HOST": "10.1.0.9",
        "MQTT_HOST": "192.168.0.5",
        "MQTT_USER": "device",
        "MQTT_PASS": "segredo",
    }
    assert (tmp_path / "firmware" / "wifi-ca-2.pem").read_text(encoding="utf-8") == PEM_FALSO
    assert inst.redes_do_env(env)[1].institucional


def test_env_do_firmware_sem_a_stack_mantem_a_senha_do_mqtt(tmp_path, monkeypatch):
    def falha(*_a):
        raise inst.subprocess.CalledProcessError(1, "docker")

    monkeypatch.setattr(inst.Instalador, "ler_segredo", falha)
    arquivo = tmp_path / "firmware" / ".env"
    arquivo.parent.mkdir()
    arquivo.write_text("WIFI_SSID=Casa\nWIFI_PASS=12345678\nMQTT_PASS=antiga\n", encoding="utf-8")
    respostas = inst.Respostas(destino=tmp_path, firmware=inst.Firmware([inst.RedeWifi("Casa")], "10.0.0.5"))
    inst.Instalador(RAIZ, respostas, False, SaidaMuda()).gerar_env_firmware()
    assert inst.ler_env(arquivo.read_text(encoding="utf-8"))["MQTT_PASS"] == "antiga"


@pytest.mark.parametrize(
    ("senha", "institucional", "ok"),
    [
        ("1234567", False, False),
        ("12345678", False, True),
        ("curta", True, True),
        ("", True, False),
        ("x" * 65, True, False),
    ],
)
def test_senha_do_wifi_institucional_segue_o_limite_do_eap(senha, institucional, ok):
    assert (inst.validar_senha_wifi(senha, institucional) is None) is ok


def test_certificado_precisa_ser_pem(tmp_path):
    bom, ruim = tmp_path / "ca.pem", tmp_path / "ca.der"
    bom.write_text(PEM_FALSO, encoding="utf-8")
    ruim.write_bytes(b"\x30\x82\x01")
    assert inst.validar_certificado("") is None
    assert inst.validar_certificado(str(bom)) is None
    assert inst.validar_certificado(str(ruim))
    assert inst.validar_certificado(str(tmp_path / "nao-existe.pem"))


def test_limites_do_wifi_batem_com_o_firmware():
    load_env = (RAIZ / "firmware" / "load_env.py").read_text(encoding="utf-8")
    assert f"MAX_REDES = {inst.MAX_REDES_WIFI}" in load_env
    assert f"LIMITE_EAP = {inst.LIMITE_EAP}" in load_env
    for metodo in inst.METODOS_EAP:
        assert f'"{metodo}"' in load_env


def test_wifi_so_atualiza_o_ip_do_computador(tmp_path, monkeypatch):
    """--wifi depois de mudar de rede: o broker e o firmware seguem o IP novo."""
    pasta = tmp_path / "ELEX20"
    (pasta / "firmware").mkdir(parents=True)
    (pasta / "firmware" / "platformio.ini").write_text("", encoding="utf-8")
    (pasta / "firmware" / ".env").write_text(
        "WIFI_SSID=Casa\nWIFI_PASS=12345678\nMQTT_HOST=192.168.0.5\nMQTT_USER=device\nMQTT_PASS=s\n",
        encoding="utf-8",
    )
    (pasta / ".env").write_text("MQTT_BIND=192.168.0.5\n", encoding="utf-8")
    comandos = []
    monkeypatch.setattr(inst, "detectar_ip_lan", lambda: "10.0.0.7")
    monkeypatch.setattr(inst, "confirmar", lambda texto, _padrao=True: "Change the Wi-Fi" not in texto)
    monkeypatch.setattr(inst.Instalador, "ler_segredo", lambda *_a: "s")
    monkeypatch.setattr(inst.Instalador, "compose", lambda _self, *a, **_k: comandos.append(a))
    monkeypatch.setattr(inst.shutil, "which", lambda _nome: None)
    args = inst.argparse.Namespace(dir=pasta, dry_run=False)
    # O padrão da pergunta é o MQTT_HOST atual; quem muda de rede digita o IP novo
    monkeypatch.setattr(inst, "perguntar", lambda t, padrao="", **_k: "10.0.0.7" if "IP address" in t else padrao)
    assert inst.configurar_wifi(args, RAIZ) == 0
    assert inst.env_do_firmware(pasta)["MQTT_HOST"] == "10.0.0.7"
    assert inst.ler_env((pasta / ".env").read_text(encoding="utf-8"))["MQTT_BIND"] == "10.0.0.7"
    assert ("up", "-d", "mosquitto") in comandos


def test_wifi_sem_mudanca_nao_regrava_a_placa(tmp_path, monkeypatch, capsys):
    pasta = tmp_path / "ELEX20"
    (pasta / "firmware").mkdir(parents=True)
    (pasta / "firmware" / "platformio.ini").write_text("", encoding="utf-8")
    (pasta / "firmware" / ".env").write_text(
        "WIFI_SSID=Casa\nWIFI_PASS=12345678\nMQTT_HOST=10.0.0.7\nMQTT_USER=device\nMQTT_PASS=s\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(inst, "detectar_ip_lan", lambda: "10.0.0.7")
    monkeypatch.setattr(inst, "perguntar", lambda _t, padrao="", **_k: padrao)
    monkeypatch.setattr(inst, "confirmar", lambda _t, padrao=True: padrao)
    monkeypatch.setattr(inst.Instalador, "ler_segredo", lambda *_a: "s")
    args = inst.argparse.Namespace(dir=pasta, dry_run=False)
    assert inst.configurar_wifi(args, RAIZ) == 0
    assert "no need to flash" in capsys.readouterr().out
