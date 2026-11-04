"""Testes do instalador multiplataforma (installer/elex_installer.py)."""

import json
import re
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
    with pytest.raises(ValueError, match="quebra de linha"):
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


def test_versao_vem_do_arquivo_versao_txt():
    esperado = (RAIZ / "installer" / "versao.txt").read_text(encoding="utf-8").strip()
    assert esperado
    assert inst.ler_versao() == esperado
    assert inst.VERSAO == esperado
