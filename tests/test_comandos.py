"""Testes da validação de comandos ao dispositivo (hermes/mcp/comandos.py)."""

import math

import pytest
from comandos import COMANDOS, validar_comando


def test_comando_valido_normaliza_o_valor():
    assert validar_comando("esp32-01", "threshold", 0.7) == ("esp32-01", "threshold", 0.7)
    assert validar_comando("esp32-01", "motor_max_ms", 800) == ("esp32-01", "motor_max_ms", 800.0)


@pytest.mark.parametrize("chave", ["doa_enabled", "motor_enabled"])
def test_liga_desliga_aceita_so_zero_e_um(chave):
    assert validar_comando("d", chave, 0)[2] == 0.0
    assert validar_comando("d", chave, 1)[2] == 1.0
    assert validar_comando("d", chave, True)[2] == 1.0
    with pytest.raises(ValueError, match="só 0 ou 1"):
        validar_comando("d", chave, 2)


@pytest.mark.parametrize(
    ("chave", "valor"),
    [
        ("threshold", 0.29),
        ("threshold", 1.0),
        ("port1_skew", 9),
        ("port1_skew", -9),
        ("motor_max_ms", 99),
        ("motor_max_ms", 2001),
    ],
)
def test_valor_fora_da_faixa_e_recusado(chave, valor):
    with pytest.raises(ValueError, match="entre"):
        validar_comando("d", chave, valor)


@pytest.mark.parametrize("chave", ["reboot", "", "__proto__", "threshold ", "THRESHOLD"])
def test_comando_desconhecido_e_recusado(chave):
    with pytest.raises(ValueError, match="desconhecido"):
        validar_comando("d", chave, 1)


@pytest.mark.parametrize("device_id", ["", "a b", "a/b", "x;drop", "é", "a" * 65, None, 5])
def test_device_id_invalido_e_recusado(device_id):
    with pytest.raises(ValueError, match="device_id"):
        validar_comando(device_id, "threshold", 0.7)


@pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf, "0.7", None])
def test_valor_nao_numerico_e_recusado(valor):
    with pytest.raises(ValueError, match="número"):
        validar_comando("d", "threshold", valor)


def test_faixas_do_firmware_batem():
    # Espelha firmware/lib/elex_core/settings.cpp (settings_apply)
    assert COMANDOS["threshold"] == (0.30, 0.99)
    assert COMANDOS["port1_skew"] == (-8.0, 8.0)
    assert COMANDOS["motor_max_ms"] == (100.0, 2000.0)
    assert COMANDOS["doa_enabled"] is None
    assert COMANDOS["motor_enabled"] is None
