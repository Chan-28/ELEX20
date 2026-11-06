"""Nomes de branch aceitos e recusados por scripts/lint-branch-name.sh."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lint-branch-name.sh"


def conferir(nome: str) -> int:
    return subprocess.run(["sh", str(SCRIPT), nome], capture_output=True, check=False).returncode  # noqa: S603, S607


@pytest.mark.parametrize(
    "nome",
    [
        "main",
        "fix/dataset-author-split",
        "ci/branch-name-lint",
        "docs/security-model-report",
        "claude/busy-spence-d6cf03",
        "dependabot/npm_and_yarn/dev-dependencies-3e181b35c8",
    ],
)
def test_nomes_aceitos(nome):
    assert conferir(nome) == 0


@pytest.mark.parametrize(
    "nome",
    [
        "develop",
        "feature/nova-tela",
        "fix/Maiusculas",
        "fix/com_sublinhado",
        "fix/-comeca-com-hifen",
        "fix/termina-com-hifen-",
        "fix/duas/barras",
        "fix/",
        "main-2",
    ],
)
def test_nomes_recusados(nome):
    assert conferir(nome) == 1


def test_mensagem_explica_o_formato():
    saida = subprocess.run(["sh", str(SCRIPT), "develop"], capture_output=True, text=True, check=False)  # noqa: S603, S607
    assert "develop" in saida.stderr
    assert "<tipo>/<descricao-em-kebab-case>" in saida.stderr
