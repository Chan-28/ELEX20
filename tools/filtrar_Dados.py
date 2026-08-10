import argparse
import time
from collections import deque
from typing import Optional, List

import numpy as np
import scipy.signal as signal
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_byprop, cf_float32


class EMGLSLProcessor:
    """
    Lê o stream LSL de EMG bruto (publicado pelo captar_Dados.py),
    aplica pré-processamento + RMS/normalização e publica um novo
    stream LSL com os dados processados.

    Uso típico:
        1. Inicie captar_Dados.py  →  stream "EMG" disponível na rede LSL
        2. Inicie este script      →  stream "EMG_Processado" disponível na rede LSL
    """

    def __init__(
        self,
        raw_stream_name: str = "EMG",
        processed_stream_name: str = "EMG_Processado",
        sample_rate: float = 1500.0,
        processing_mode: str = "rms",
        rms_window_ms: float = 50.0,
        buffer_size: int = 500,
        use_bandpass: bool = True,
        use_notch: bool = True,
        use_envelope: bool = True,
        resolve_timeout: float = 10.0,
    ):
        self.raw_stream_name = raw_stream_name
        self.processed_stream_name = processed_stream_name
        self.sample_rate = sample_rate
        self.processing_mode = processing_mode
        self.rms_window_ms = rms_window_ms
        self.buffer_size = buffer_size
        self.use_bandpass = use_bandpass
        self.use_notch = use_notch
        self.use_envelope = use_envelope
        self.resolve_timeout = resolve_timeout

        # --- Buffers de processamento ---
        self.rms_window_samples = max(1, int((rms_window_ms / 1000.0) * sample_rate))
        self.rms_buffer: deque = deque(maxlen=self.rms_window_samples)
        self.signal_window: deque = deque(maxlen=buffer_size)

        self.normalization_buffer: Optional[deque] = None
        if processing_mode == "normalized":
            self.normalization_buffer = deque(maxlen=int(sample_rate * 5.0))

        # --- Filtros ---
        self.sos_bandpass = None
        self.b_notch = None
        self.a_notch = None
        self.sos_envelope = None
        self.bp_state = None
        self.notch_state = None
        self.env_state = None
        self._init_filters()

        # --- Estatísticas ---
        self.total_samples = 0
        self.error_count = 0

    # ------------------------------------------------------------------
    # Inicialização dos filtros
    # ------------------------------------------------------------------

    def _init_filters(self) -> None:
        nyq = self.sample_rate / 2.0  # Frequência de Nyquist

        if self.use_bandpass:
            bp_low = 20.0
            bp_high = min(430.0, nyq * 0.95)  # Garante que fica abaixo de Nyquist

            if bp_low >= bp_high:
                print(
                    f"Aviso: taxa de amostragem {self.sample_rate} Hz muito baixa para o "
                    f"filtro passa-banda (20–430 Hz). Filtro passa-banda desativado."
                )
                self.use_bandpass = False
            else:
                self.sos_bandpass = signal.butter(
                    4, [bp_low, bp_high], btype="bandpass", fs=self.sample_rate, output="sos"
                )
                self.bp_state = signal.sosfilt_zi(self.sos_bandpass)

        if self.use_notch:
            notch_freq = 60.0
            if notch_freq >= nyq:
                print(
                    f"Aviso: frequência do filtro notch (60 Hz) >= Nyquist ({nyq} Hz). "
                    f"Filtro notch desativado."
                )
                self.use_notch = False
            else:
                self.b_notch, self.a_notch = signal.iirnotch(notch_freq, 30.0, fs=self.sample_rate)
                self.notch_state = signal.lfilter_zi(self.b_notch, self.a_notch)

        if self.use_envelope:
            self.sos_envelope = signal.butter(
                2, 5.0, btype="lowpass", fs=self.sample_rate, output="sos"
            )
            self.env_state = signal.sosfilt_zi(self.sos_envelope)

    # ------------------------------------------------------------------
    # Criação do outlet LSL processado
    # ------------------------------------------------------------------

    def _create_outlet(self) -> StreamOutlet:
        info = StreamInfo(
            name=self.processed_stream_name,
            type="EMG",
            channel_count=1,
            nominal_srate=self.sample_rate,
            channel_format=cf_float32,
            source_id="emg-lsl-processed-001",
        )
        return StreamOutlet(info, chunk_size=32)

    # ------------------------------------------------------------------
    # Pipeline de processamento
    # ------------------------------------------------------------------

    def _preprocess_sample(self, sample_value: float) -> float:
        self.signal_window.append(sample_value)
        hist = np.asarray(self.signal_window, dtype=float)

        if len(hist) < 4:
            return float(sample_value)

        if self.use_bandpass and self.sos_bandpass is not None:
            y, self.bp_state = signal.sosfilt(self.sos_bandpass, hist, zi=self.bp_state)
            hist = np.asarray(y, dtype=float)

        if self.use_notch and self.b_notch is not None and self.a_notch is not None:
            y, self.notch_state = signal.lfilter(
                self.b_notch, self.a_notch, hist, zi=self.notch_state
            )
            hist = np.asarray(y, dtype=float)

        if self.use_envelope and self.sos_envelope is not None:
            rect = np.abs(hist)
            y, self.env_state = signal.sosfilt(self.sos_envelope, rect, zi=self.env_state)
            hist = np.asarray(y, dtype=float)

        return float(hist[-1])

    def _calculate_rms(self) -> float:
        if len(self.rms_buffer) == 0:
            return 0.0
        data = np.array(self.rms_buffer, dtype=float)
        return float(np.sqrt(np.mean(data ** 2)))

    def _process_sample(self, raw_value: float) -> float:
        preprocessed = self._preprocess_sample(raw_value)
        self.rms_buffer.append(preprocessed)

        if self.processing_mode == "raw":
            return preprocessed

        if self.processing_mode == "rms":
            return self._calculate_rms()

        if self.processing_mode == "normalized":
            rms_value = self._calculate_rms()
            if self.normalization_buffer is not None:
                self.normalization_buffer.append(rms_value)
            if not self.normalization_buffer or len(self.normalization_buffer) < 100:
                return rms_value
            arr = np.array(list(self.normalization_buffer))
            min_v = float(np.min(arr))
            max_v = float(np.max(arr))
            rng = (max_v - min_v) if (max_v - min_v) != 0 else 1.0
            return float((rms_value - min_v) / rng)

        raise ValueError(f"Modo inválido: {self.processing_mode}")

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Resolve o stream LSL de entrada, cria o outlet processado
        e entra no loop de leitura/processamento/publicação.
        """
        print(f"Procurando stream LSL '{self.raw_stream_name}'...")
        streams = resolve_byprop("name", self.raw_stream_name, timeout=self.resolve_timeout)

        if not streams:
            raise RuntimeError(
                f"Stream LSL '{self.raw_stream_name}' não encontrado. "
                "Certifique-se de que o captar_Dados.py está rodando."
            )

        inlet = StreamInlet(streams[0], max_buflen=360)
        # Usa a taxa de amostragem informada pelo próprio stream, se disponível
        stream_srate = streams[0].nominal_srate()
        if stream_srate > 0 and stream_srate != self.sample_rate:
            print(
                f"Aviso: taxa do stream ({stream_srate} Hz) difere do parâmetro "
                f"configurado ({self.sample_rate} Hz). Usando {stream_srate} Hz."
            )
            self.sample_rate = stream_srate
            self._init_filters()  # Reinicializa filtros com a taxa correta

        outlet = self._create_outlet()

        print(f"Stream de entrada  : '{self.raw_stream_name}'")
        print(f"Stream de saída    : '{self.processed_stream_name}'")
        print(f"Modo               : {self.processing_mode}")
        print(f"Taxa de amostragem : {self.sample_rate} Hz")
        print(f"Filtros ativos     : bandpass={self.use_bandpass}, "
              f"notch={self.use_notch}, envelope={self.use_envelope}")
        print("Processando... (Ctrl+C para parar)\n")

        try:
            while True:
                sample, timestamp = inlet.pull_sample(timeout=1.0)

                if sample is None:
                    continue  # Timeout — aguarda nova amostra

                try:
                    raw_value = float(sample[0])
                    processed_value = self._process_sample(raw_value)
                    outlet.push_sample([processed_value], timestamp=time.time())

                    self.total_samples += 1
                    if self.total_samples % 500 == 0:
                        print(
                            f"Amostras: {self.total_samples:>8d} | "
                            f"Bruto: {raw_value:>8.4f} | "
                            f"Processado: {processed_value:>8.4f}"
                        )
                except Exception as e:
                    self.error_count += 1
                    if self.error_count % 50 == 1:
                        print(f"Erro ao processar amostra: {e}")

        except KeyboardInterrupt:
            print("\nProcessamento encerrado pelo usuário.")
        finally:
            print(f"\nResumo: {self.total_samples} amostras processadas, "
                  f"{self.error_count} erros.")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lê o stream LSL de EMG bruto, aplica pré-processamento + RMS "
            "e publica um novo stream LSL com os dados processados."
        )
    )
    parser.add_argument(
        "--raw-stream", default="EMG",
        help="Nome do stream LSL de entrada (padrão: EMG)"
    )
    parser.add_argument(
        "--processed-stream", default="EMG_Processado",
        help="Nome do stream LSL de saída (padrão: EMG_Processado)"
    )
    parser.add_argument(
        "--sample-rate", type=float, default=1500.0,
        help="Taxa de amostragem em Hz (padrão: 1500)"
    )
    parser.add_argument(
        "--mode", choices=["raw", "rms", "normalized"], default="rms",
        help="Modo de processamento (padrão: rms)"
    )
    parser.add_argument(
        "--rms-window-ms", type=float, default=50.0,
        help="Janela RMS em ms (padrão: 50)"
    )
    parser.add_argument(
        "--buffer-size", type=int, default=500,
        help="Tamanho do buffer de sinal (padrão: 500)"
    )
    parser.add_argument(
        "--resolve-timeout", type=float, default=10.0,
        help="Timeout para encontrar o stream LSL de entrada, em segundos (padrão: 10)"
    )
    parser.add_argument("--no-bandpass", action="store_true", help="Desativa filtro passa-banda")
    parser.add_argument("--no-notch",    action="store_true", help="Desativa filtro notch (60 Hz)")
    parser.add_argument("--no-envelope", action="store_true", help="Desativa extração de envelope")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    processor = EMGLSLProcessor(
        raw_stream_name=args.raw_stream,
        processed_stream_name=args.processed_stream,
        sample_rate=args.sample_rate,
        processing_mode=args.mode,
        rms_window_ms=args.rms_window_ms,
        buffer_size=args.buffer_size,
        use_bandpass=not args.no_bandpass,
        use_notch=not args.no_notch,
        use_envelope=not args.no_envelope,
        resolve_timeout=args.resolve_timeout,
    )
    try:
        processor.run()
    except RuntimeError as e:
        print(f"\nErro: {e}")
        raise


if __name__ == "__main__":
    main()