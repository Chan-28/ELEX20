"""CHANGELOG.md e o script que o workflow de release usa para conferir e montar as notas."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "changelog-section.sh"
CHANGELOG = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="sem bash")


def secao(tag: str, arquivo: Path | None = None) -> subprocess.CompletedProcess:
    argumentos = ["bash", str(SCRIPT), tag] + ([str(arquivo)] if arquivo else [])
    return subprocess.run(argumentos, cwd=RAIZ, capture_output=True, text=True, check=False)  # noqa: S603


def test_toda_versao_do_changelog_tem_texto_e_link():
    versoes = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", CHANGELOG, re.M)
    assert versoes, "nenhuma versão no CHANGELOG.md"
    for versao in versoes:
        resultado = secao(f"v{versao}")
        assert resultado.returncode == 0, resultado.stderr
        assert resultado.stdout.strip()
        assert re.search(rf"^\[{re.escape(versao)}\]: https://", CHANGELOG, re.M), f"falta o link de {versao}"


def test_versoes_em_ordem_decrescente():
    versoes = [tuple(map(int, v.split("."))) for v in re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG, re.M)]
    assert versoes == sorted(versoes, reverse=True)


def test_secao_para_na_proxima_versao(tmp_path):
    arquivo = tmp_path / "CHANGELOG.md"
    arquivo.write_text(
        "# Changelog\n\n## [2.0.0] - 2026-01-02\n\n### Adicionado\n\n- novo\n\n"
        "## [1.0.0] - 2026-01-01\n\n- velho\n\n[2.0.0]: https://x\n",
        encoding="utf-8",
    )
    resultado = secao("v2.0.0", arquivo)
    assert resultado.returncode == 0
    assert resultado.stdout == "### Adicionado\n\n- novo\n"
    assert secao("v1.0.0", arquivo).stdout.strip() == "- velho"


def test_release_sem_secao_ou_tag_invalida_falha(tmp_path):
    arquivo = tmp_path / "CHANGELOG.md"
    arquivo.write_text("# Changelog\n\n## [1.0.0] - 2026-01-01\n\n\n## [0.9.0] - 2025-12-01\n\n- x\n", encoding="utf-8")
    assert secao("v3.0.0", arquivo).returncode == 1
    assert secao("v1.0.0", arquivo).returncode == 1  # seção vazia
    assert secao("release-final", arquivo).returncode == 1


def test_workflow_de_release_exige_o_changelog():
    workflow = (RAIZ / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "scripts/changelog-section.sh" in workflow
    assert re.search(r"installers:\n(?:.*\n)*?\s+needs: changelog", workflow)


def test_versao_do_projeto_e_a_da_ultima_release():
    """pyproject.toml, package.json e package-lock.json acompanham a última versão do CHANGELOG."""
    ultima = re.search(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG, re.M).group(1)
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1) == ultima
    pacote = json.loads((RAIZ / "package.json").read_text(encoding="utf-8"))
    trava = json.loads((RAIZ / "package-lock.json").read_text(encoding="utf-8"))
    assert pacote["version"] == trava["version"] == trava["packages"][""]["version"] == ultima
