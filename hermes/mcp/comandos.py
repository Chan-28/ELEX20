"""Validação dos comandos que o Hermes pode pedir ao dispositivo (lista fechada).

As faixas espelham firmware/lib/elex_core/settings.cpp e o Code node do workflow
n8n/workflows/comando-dispositivo.json; mudou uma, confira as outras duas.
"""

import math
import re

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# chave -> (mínimo, máximo) para números; None para ligar/desligar (0 ou 1)
COMANDOS: dict[str, tuple[float, float] | None] = {
    "threshold": (0.30, 0.99),
    "doa_enabled": None,
    "motor_enabled": None,
    "port1_skew": (-8.0, 8.0),
    "motor_max_ms": (100.0, 2000.0),
}


def validar_comando(device_id: str, chave: str, valor: float) -> tuple[str, str, float]:
    """Devolve (device_id, chave, valor) normalizados ou levanta ValueError."""
    if not isinstance(device_id, str) or not DEVICE_ID_RE.fullmatch(device_id):
        raise ValueError("device_id inválido")
    if chave not in COMANDOS:
        raise ValueError(f"comando desconhecido; permitidos: {', '.join(sorted(COMANDOS))}")
    if isinstance(valor, bool):
        valor = float(valor)
    if not isinstance(valor, int | float) or not math.isfinite(valor):
        raise ValueError("valor deve ser um número finito")
    faixa = COMANDOS[chave]
    if faixa is None:
        if valor not in (0, 1):
            raise ValueError(f"{chave} aceita só 0 ou 1")
    elif not faixa[0] <= valor <= faixa[1]:
        raise ValueError(f"{chave} deve estar entre {faixa[0]} e {faixa[1]}")
    return device_id, chave, float(valor)
