"""Smoke test para validar o pipeline BLE -> LSL -> filtro -> UI.

O teste confirma:
- dependências necessárias disponíveis (bleak, pylsl)
- dispositivo BLE está acessível e anunciando
- streams LSL esperados aparecem com os nomes corretos

Este teste não substitui a execução contínua com hardware real; ele valida o contrato do pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validador do pipeline EMG BLE/LSL.")
    # No Windows/Linux, endereços BLE usam MAC (ex: "AA:BB:CC:DD:EE:FF"). 
    # No macOS, usam UUID. Atualize o default para o formato do seu SO.
    parser.add_argument("--address", default="AA:BB:CC:DD:EE:FF", help="Endereço MAC ou UUID do ESP32 BLE")
    parser.add_argument("--wait-seconds", type=float, default=12.0, help="Tempo máximo aguardando os streams")
    parser.add_argument("--expected-raw", default="EMG", help="Nome do stream bruto esperado")
    parser.add_argument("--expected-processed", default="EMG_Processado", help="Nome do stream processado esperado")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    try:
        from bleak import BleakScanner
        from pylsl import resolve_streams
    except ImportError as exc:
        print(f"[ERRO] Dependências ausentes: {exc}")
        return 1

    print(f"[1/3] Procurando dispositivo BLE {args.address}...")
    try:
        # Busca o dispositivo para validar que o rádio Bluetooth funciona e o ESP32 está ativo
        device = await BleakScanner.find_device_by_address(args.address, timeout=5.0)
        
        if not device:
            print(f"[ERRO] Dispositivo BLE {args.address} não encontrado no scan.")
            return 2
            
        print(f"      Dispositivo encontrado: {device.name or 'Sem Nome'}")
    except Exception as exc:
        print(f"[ERRO] Falha ao acessar o hardware Bluetooth: {exc}")
        return 2

    print("[2/3] Aguardando streams LSL...")
    deadline = time.time() + args.wait_seconds
    found_raw = False
    found_processed = False

    while time.time() < deadline:
        # resolve_streams(0.5) bloqueia a execução por 0.5s.
        # Em um script assíncrono complexo usaríamos run_in_executor, 
        # mas para este script simples de validação, isso é perfeitamente aceitável.
        streams = resolve_streams(0.5)
        nomes = {stream.name() for stream in streams}
        
        found_raw = args.expected_raw in nomes
        found_processed = args.expected_processed in nomes
        
        if found_raw and found_processed:
            break
            
        # Repassa o controle para o event loop
        await asyncio.sleep(0.1)

    if not found_raw:
        print(f"[ERRO] Stream bruto '{args.expected_raw}' não apareceu.")
        return 3
    if not found_processed:
        print(f"[ERRO] Stream processado '{args.expected_processed}' não apareceu.")
        return 4

    print("[3/3] Contrato do pipeline validado com sucesso.")
    print(f"- {args.expected_raw} encontrado")
    print(f"- {args.expected_processed} encontrado")
    return 0


if __name__ == "__main__":
    try:
        # Ponto de entrada assíncrono padrão
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nTeste interrompido pelo usuário.")
        sys.exit(130)