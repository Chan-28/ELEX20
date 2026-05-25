import argparse
import time
from typing import Optional

import numpy as np
import serial
from pylsl import StreamInfo, StreamOutlet, cf_float32


class EMGSerialCapture:
    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = 115200,
        sample_rate: float = 1000.0,
        stream_name: str = "EMG",
        stream_type: str = "EMG",
        source_id: str = "emg-bt-001",
        timeout: float = 1.0,
        window_size: int = 500,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.serial_port = serial.Serial(port, baudrate, timeout=timeout)
        self.historico_sinal = np.zeros(window_size, dtype=float)

        info = StreamInfo(
            name=stream_name,
            type=stream_type,
            channel_count=1,
            nominal_srate=sample_rate,
            channel_format=cf_float32,
            source_id=source_id,
        )
        self.outlet = StreamOutlet(info)

    def run(self) -> None:
        print(f"Aguardando dados do EMG via Bluetooth/serial em {self.port}...")

        try:
            while True:
                if self.serial_port.in_waiting <= 0:
                    time.sleep(0.001)
                    continue

                linha = self.serial_port.readline().decode("utf-8", errors="ignore").strip()
                if not linha:
                    continue

                try:
                    nova_amostra = float(linha)
                except ValueError:
                    continue

                self.historico_sinal = np.roll(self.historico_sinal, -1)
                self.historico_sinal[-1] = nova_amostra
                self.outlet.push_sample([nova_amostra])
                print(f"Amostra bruta: {nova_amostra:.2f}")
        except KeyboardInterrupt:
            print("\nConexão encerrada.")
        finally:
            self.serial_port.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Captura EMG via serial e publica no LSL.")
    parser.add_argument("--port", default="COM3", help="Porta serial do dispositivo. Exemplo: COM3")
    parser.add_argument("--baudrate", type=int, default=115200, help="Taxa de comunicação serial")
    parser.add_argument("--sample-rate", type=float, default=1000.0, help="Taxa nominal do stream LSL")
    parser.add_argument("--window-size", type=int, default=500, help="Tamanho do histórico interno")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture = EMGSerialCapture(
        port=args.port,
        baudrate=args.baudrate,
        sample_rate=args.sample_rate,
        window_size=args.window_size,
    )
    capture.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
