import asyncio
import argparse
import struct
import time
from collections import deque
from typing import Optional, List, Tuple

import numpy as np
import scipy.signal as signal
from bleak import BleakScanner, BleakClient
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_streams, cf_float32


class EMGBLEToLSLProcessor:
    def __init__(
        self,
        device_name: str = "ESP32-EMG",
        char_uuid: str = "bef8d6c9-9c21-4c9e-b632-bd763f7a92bf",
        raw_stream_name: str = "EMG",
        processed_stream_name: str = "EMG_Processado",
        sample_rate: float = 500.0,
        processing_mode: str = "rms",
        rms_window_ms: float = 50.0,
        buffer_size: int = 500,
        use_bandpass: bool = True,
        use_notch: bool = True,
        use_envelope: bool = True,
    ):
        self.device_name = device_name
        self.char_uuid = char_uuid
        self.raw_stream_name = raw_stream_name
        self.processed_stream_name = processed_stream_name
        self.sample_rate = sample_rate
        self.processing_mode = processing_mode
        self.rms_window_ms = rms_window_ms
        self.buffer_size = buffer_size
        self.use_bandpass = use_bandpass
        self.use_notch = use_notch
        self.use_envelope = use_envelope

        self.raw_outlet = self._create_lsl_outlet(raw_stream_name, 1, sample_rate, "emg-esp32-ble-raw-001")
        self.processed_outlet: Optional[StreamOutlet] = None

        self.channel_count = 1
        self.rms_window_samples = max(1, int((self.rms_window_ms / 1000.0) * self.sample_rate))
        self.rms_buffers = [deque(maxlen=self.rms_window_samples)]

        self.normalization_buffer: Optional[deque] = None
        if self.processing_mode == "normalized":
            self.normalization_buffer = deque(maxlen=int(self.sample_rate * 5.0))

        self.signal_window = deque(maxlen=self.buffer_size)

        self.sos_bandpass = None
        self.b_notch = None
        self.a_notch = None
        self.sos_envelope = None
        self.bp_state = None
        self.notch_state = None
        self.env_state = None
        self._init_filters()

        self.total_samples = 0
        self.error_count = 0

    def _create_lsl_outlet(self, name: str, channel_count: int, srate: float, source_id: str) -> StreamOutlet:
        info = StreamInfo(
            name=name,
            type="EMG",
            channel_count=channel_count,
            nominal_srate=srate,
            channel_format=cf_float32,
            source_id=source_id,
        )
        return StreamOutlet(info, chunk_size=32)

    def _init_filters(self):
        if self.use_bandpass:
            self.sos_bandpass = signal.butter(
                4, [20.0, 450.0], btype="bandpass", fs=self.sample_rate, output="sos"
            )
            # Usa a função nativa do SciPy para obter as condições iniciais
            self.bp_state = signal.sosfilt_zi(self.sos_bandpass)

        if self.use_notch:
            self.b_notch, self.a_notch = signal.iirnotch(
                60.0, 30.0, fs=self.sample_rate
            )
            self.notch_state = signal.lfilter_zi(self.b_notch, self.a_notch)

        if self.use_envelope:
            self.sos_envelope = signal.butter(
                2, 5.0, btype="lowpass", fs=self.sample_rate, output="sos"
            )
            # O SciPy garante que sos_envelope é um ndarray, sem necessidade de checagens extras
            self.env_state = signal.sosfilt_zi(self.sos_envelope)

    async def run(self):
        print(f"Procurando dispositivo BLE '{self.device_name}'...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name == self.device_name,
            timeout=10.0,
        )
        if device is None:
            raise RuntimeError(f"Dispositivo '{self.device_name}' não encontrado")

        print(f"Dispositivo encontrado: {device.address}")
        print("Criando stream LSL processado...")

        self.processed_outlet = self._create_lsl_outlet(
            self.processed_stream_name, 1, self.sample_rate, "emg-esp32-ble-processed-001"
        )

        async def keep_alive():
            while True:
                await asyncio.sleep(1)

        def on_notify(sender, data: bytearray):
            try:
                if len(data) != 8:
                    return

                timestamp_ms, voltage = struct.unpack("<If", data)
                raw_value = float(voltage)

                self.raw_outlet.push_sample([raw_value], timestamp=time.time())

                processed_value = self._process_sample([raw_value])[0]
                # processed_outlet may be Optional; guard against None to satisfy static analyzers
                if self.processed_outlet is not None:
                    self.processed_outlet.push_sample([processed_value], timestamp=time.time())

                self.total_samples += 1
                if self.total_samples % 500 == 0:
                    print(
                        f"Amostras: {self.total_samples} | "
                        f"Bruto: {raw_value:.4f} | "
                        f"Processado: {processed_value:.4f}"
                    )

            except Exception as e:
                self.error_count += 1
                if self.error_count % 50 == 1:
                    print(f"Erro no callback BLE: {e}")

        async with BleakClient(device) as client:
            print(f"Conectado ao BLE. Assinando UUID {self.char_uuid}...")
            await client.start_notify(self.char_uuid, on_notify)
            print("Notificações ativas. Ctrl+C para parar.")
            await keep_alive()

    def _preprocess_sample(self, sample_value: float) -> float:
        self.signal_window.append(sample_value)
        hist = np.asarray(self.signal_window, dtype=float)

        if len(hist) < 4:
            return float(sample_value)

        if self.use_bandpass and self.sos_bandpass is not None:
            y, self.bp_state = signal.sosfilt(self.sos_bandpass, hist, zi=self.bp_state)
            hist = np.asarray(y, dtype=float)

        if self.use_notch and self.b_notch is not None and self.a_notch is not None:
            y, self.notch_state = signal.lfilter(self.b_notch, self.a_notch, hist, zi=self.notch_state)
            hist = np.asarray(y, dtype=float)

        if self.use_envelope and self.sos_envelope is not None:
            rect = np.abs(hist)
            y, self.env_state = signal.sosfilt(self.sos_envelope, rect, zi=self.env_state)
            hist = np.asarray(y, dtype=float)

        return float(hist[-1])

    def calculate_rms(self, channel_idx: int) -> float:
        buffer = self.rms_buffers[channel_idx]
        if len(buffer) == 0:
            return 0.0
        data = np.array(buffer, dtype=float)
        return float(np.sqrt(np.mean(data ** 2)))

    def _process_sample(self, sample: List[float]) -> List[float]:
        preprocessed = self._preprocess_sample(sample[0])
        self.rms_buffers[0].append(preprocessed)

        if self.processing_mode == "raw":
            return [preprocessed]

        if self.processing_mode == "rms":
            return [self.calculate_rms(0)]

        if self.processing_mode == "normalized":
            rms_value = self.calculate_rms(0)
            if self.normalization_buffer is not None:
                self.normalization_buffer.append([rms_value])
            if not self.normalization_buffer or len(self.normalization_buffer) < 100:
                return [rms_value]
            arr = np.array(list(self.normalization_buffer))
            min_v = float(np.min(arr))
            max_v = float(np.max(arr))
            rng = max_v - min_v if (max_v - min_v) != 0 else 1.0
            return [float((rms_value - min_v) / rng)]

        raise ValueError(f"Modo inválido: {self.processing_mode}")


def parse_args():
    parser = argparse.ArgumentParser(description="Recebe EMG via BLE, publica em LSL e aplica pré-processamento + RMS.")
    parser.add_argument("--device-name", default="ESP32-EMG")
    parser.add_argument("--char-uuid", default="bef8d6c9-9c21-4c9e-b632-bd763f7a92bf")
    parser.add_argument("--sample-rate", type=float, default=500.0)
    parser.add_argument("--mode", choices=["raw", "rms", "normalized"], default="rms")
    parser.add_argument("--rms-window-ms", type=float, default=50.0)
    parser.add_argument("--buffer-size", type=int, default=500)
    parser.add_argument("--no-bandpass", action="store_true")
    parser.add_argument("--no-notch", action="store_true")
    parser.add_argument("--no-envelope", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    app = EMGBLEToLSLProcessor(
        device_name=args.device_name,
        char_uuid=args.char_uuid,
        sample_rate=args.sample_rate,
        processing_mode=args.mode,
        rms_window_ms=args.rms_window_ms,
        buffer_size=args.buffer_size,
        use_bandpass=not args.no_bandpass,
        use_notch=not args.no_notch,
        use_envelope=not args.no_envelope,
    )
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\nConexão encerrada.")
    except Exception as e:
        print(f"\nErro crítico: {e}")
        raise


if __name__ == "__main__":
    main()