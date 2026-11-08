"""Regras do docker-compose.yaml que o CI confere."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_toda_imagem_tem_versao_e_digest():
    """Sem digest, a mesma tag pode trazer outra imagem; o Dependabot atualiza os dois juntos."""
    compose = (RAIZ / "docker-compose.yaml").read_text(encoding="utf-8")
    imagens = re.findall(r"^\s*image:\s*(\S+)\s*$", compose, re.M)
    assert imagens
    sem_digest = [i for i in imagens if not re.fullmatch(r"[^:@\s]+:[^@\s]+@sha256:[0-9a-f]{64}", i)]
    assert sem_digest == []
