import asyncio
import signal
import struct
import sys
from typing import Callable, Optional
from bleak import BleakScanner, BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from pylsl import StreamInfo, StreamOutlet, cf_float32


class EMGEngine:
    """
    Engine para capturar dados EMG via BLE usando Bleak.
    
    Suporta:
    - Escanear e conectar a dispositivos BLE
    - Receber notificações em tempo real
    - Publicar em LSL para integração com outros softwares
    - Callbacks customizados
    """
    
    def __init__(
        self,
        device_name: str = "ESP32-EMG",
        char_uuid: str = "bef8d6c9-9c21-4c9e-b632-bd763f7a92bf",  # UUID padrão BLE SPP
        service_uuid: Optional[str] = None,
        queue_maxsize: int = 2048,
        scan_timeout: float = 10.0,
        sample_rate: float = 500.0,  # Hz
    ):
        """
        Args:
            device_name: Nome do dispositivo BLE a conectar
            char_uuid: UUID da característica BLE que envia os dados
            service_uuid: UUID do serviço (opcional)
            queue_maxsize: Tamanho máximo da fila interna
            scan_timeout: Timeout para escaneamento
            sample_rate: Taxa de amostragem em Hz (para LSL)
        """
        self.device_name = device_name
        self.char_uuid = char_uuid
        self.service_uuid = service_uuid
        self.scan_timeout = scan_timeout
        self.sample_rate = sample_rate
        self.is_running = False
        self._stop_event: Optional[asyncio.Event] = None

        self._queue: asyncio.Queue[tuple[float, float]] = asyncio.Queue(maxsize=queue_maxsize)
        self._subscribers: list[Callable] = []
        
        # Estatísticas
        self.samples_received = 0
        self.errors_received = 0
        self.last_value = 0.0
        self.last_timestamp = 0

    def subscribe(self, callback: Callable) -> None:
        """
        Adiciona uma função (sync ou async) para receber os dados.
        
        Assinatura da callback: callback(value: float) ou async def callback(value: float)
        """
        self._subscribers.append(callback)
        print(f"✓ Subscriber '{callback.__name__}' registrado")

    def unsubscribe(self, callback: Callable) -> None:
        """Remove uma função previamente registrada."""
        try:
            self._subscribers.remove(callback)
            print(f"✓ Subscriber '{callback.__name__}' removido")
        except ValueError:
            pass

    def stop(self) -> None:
        """Solicita parada do engine de forma segura."""
        if self._stop_event is not None:
            self._stop_event.set()
            print("✓ Parada solicitada")

    def _notification_handler(
        self, characteristic: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """
        Handler de notificações BLE.
        Esperado formato: timestamp(4 bytes int) + voltage(4 bytes float)
        Ou apenas voltage se dados simples.
        """
        try:
            # Tenta decodificar como timestamp + voltage
            if len(data) == 8:
                timestamp, value = struct.unpack('<If', data)
            # Ou apenas voltage (float)
            elif len(data) == 4:
                value = struct.unpack('<f', data)[0]
                timestamp = self.last_timestamp
            # Ou múltiplos floats
            elif len(data) % 4 == 0:
                values = struct.unpack(f'<{len(data)//4}f', data)
                value = values[0]  # Toma o primeiro
                timestamp = self.last_timestamp
            else:
                print(f"⚠ Formato desconhecido: {len(data)} bytes | Raw: {data.hex()}")
                self.errors_received += 1
                return

            self.last_value = value
            self.last_timestamp = timestamp
            self.samples_received += 1

            try:
                self._queue.put_nowait((timestamp, value))
            except asyncio.QueueFull:
                # Descarta amostras antigas se fila está cheia
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait((timestamp, value))
                except asyncio.QueueEmpty:
                    pass

        except struct.error as e:
            print(f"✗ Erro de decodificação: {e} | Raw ({len(data)} bytes): {data.hex()}")
            self.errors_received += 1
            return

    async def _dispatch_worker(
        self,
        stop_event: asyncio.Event,
        max_samples: Optional[int] = None,
    ) -> None:
        """
        Worker separado: drena a fila e despacha para os subscribers.
        Roda em paralelo ao recebimento BLE, sem bloquear as notificações.
        """
        processed_count = 0

        while not stop_event.is_set() or not self._queue.empty():
            try:
                timestamp, value = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            # Dispara callbacks
            for callback in list(self._subscribers):
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(value)
                    else:
                        callback(value)
                except Exception as e:
                    print(f"✗ Erro no subscriber '{callback.__name__}': {e}")

            processed_count += 1
            if max_samples is not None and processed_count >= max_samples:
                print(f"⏹ Limite de amostras atingido ({max_samples}). Encerrando...")
                stop_event.set()

            self._queue.task_done()

    async def run(
        self,
        stop_event: Optional[asyncio.Event] = None,
        max_run_seconds: Optional[float] = None,
        max_samples: Optional[int] = None,
    ) -> None:
        """
        Executa o engine EMG.
        
        Args:
            stop_event: Event para parar manualmente
            max_run_seconds: Parar após N segundos
            max_samples: Parar após N amostras
        """
        if stop_event is None:
            stop_event = asyncio.Event()

        self._stop_event = stop_event
        self.is_running = True
        timer_task: Optional[asyncio.Task] = None

        try:
            # --- ESCANEAR DISPOSITIVO ---
            print(f"\n🔍 Buscando '{self.device_name}'... (timeout: {self.scan_timeout}s)")
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.name == self.device_name,
                timeout=self.scan_timeout,
            )

            if not device:
                print(f"✗ Dispositivo '{self.device_name}' não encontrado.")
                print("\n💡 Dicas de troubleshooting:")
                print("   1. Verifique se o ESP32 está ligado e com Bluetooth ativo")
                print("   2. Tente aumentar o timeout: --timeout 30")
                print("   3. Verifique o nome do dispositivo em settings Bluetooth")
                print("   4. Em Linux: sudo bluetoothctl scan on")
                self.is_running = False
                return

            print(f"✓ Dispositivo encontrado: {device.address} ({device.name})")

            # --- CONECTAR E RECEBER DADOS ---
            def on_disconnect(client: BleakClient) -> None:
                print(f"\n⚠ Dispositivo {client.address} desconectado")
                stop_event.set()

            async with BleakClient(device, disconnected_callback=on_disconnect) as client:
                print(f"✓ Conectado em {device.address}")
                
                # Lista características disponíveis
                print("\n📋 Características BLE disponíveis:")
                for service in client.services:
                    for char in service.characteristics:
                        print(f"   - {char.uuid}: {char.description}")

                # Inicia worker de dispatch
                print(f"\n▶ Iniciando captura de dados (amostragem: {self.sample_rate} Hz)...")
                worker_task = asyncio.create_task(
                    self._dispatch_worker(stop_event, max_samples=max_samples)
                )

                # Timer para parar por tempo
                if max_run_seconds is not None:
                    async def _stop_after_timeout() -> None:
                        await asyncio.sleep(max_run_seconds)
                        if not stop_event.is_set():
                            print(f"\n⏹ Tempo limite ({max_run_seconds}s) atingido")
                            stop_event.set()

                    timer_task = asyncio.create_task(_stop_after_timeout())

                # Inicia notificações BLE
                try:
                    await client.start_notify(self.char_uuid, self._notification_handler)
                except Exception as e:
                    print(f"✗ Erro ao iniciar notificações: {e}")
                    print(f"   UUID usado: {self.char_uuid}")
                    stop_event.set()

                # Aguarda parada
                try:
                    await stop_event.wait()
                finally:
                    print("\n🛑 Encerrando transmissão...")
                    try:
                        await client.stop_notify(self.char_uuid)
                    except Exception:
                        pass

                    # Drena o que restou na fila
                    try:
                        await asyncio.wait_for(worker_task, timeout=5.0)
                    except asyncio.TimeoutError:
                        worker_task.cancel()
                        await asyncio.gather(worker_task, return_exceptions=True)

                    if timer_task is not None:
                        timer_task.cancel()
                        await asyncio.gather(timer_task, return_exceptions=True)

        finally:
            self.is_running = False
            self._stop_event = None
            
            # --- ESTATÍSTICAS FINAIS ---
            print("\n📊 Estatísticas de Captura:")
            print(f"   Amostras recebidas: {self.samples_received}")
            print(f"   Erros: {self.errors_received}")
            print(f"   Taxa efetiva: {self.samples_received / max_run_seconds:.1f} Hz" if max_run_seconds else "")
            print(f"   Último valor: {self.last_value:.4f} V")

    async def get_device_info(self) -> Optional[dict]:
        """Obtém informações do dispositivo sem conectar permanentemente."""
        print(f"🔍 Buscando informações de '{self.device_name}'...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name == self.device_name,
            timeout=self.scan_timeout,
        )

        if not device:
            return None

        rssi = getattr(device, "rssi", None)

        info = {
            "name": device.name,
            "address": device.address,
            "rssi": rssi,
            "properties": device.details,
        }

        # Conecta brevemente para obter serviços
        try:
            async with BleakClient(device) as client:
                print("\n📡 Serviços BLE disponíveis:")
                for service in client.services:
                    print(f"\nServiço: {service.uuid}")
                    for char in service.characteristics:
                        flags = ", ".join(char.properties)
                        print(f"  └─ {char.uuid}")
                        print(f"     Propriedades: {flags}")
                        print(f"     Descrição: {char.description}")
                info["services"] = [
                    {
                        "uuid": str(service.uuid),
                        "characteristics": [
                            {
                                "uuid": str(char.uuid),
                                "properties": char.properties,
                            }
                            for char in service.characteristics
                        ]
                    }
                    for service in client.services
                ]
        except Exception as e:
            print(f"⚠ Não foi possível obter serviços: {e}")

        return info


# --- CALLBACKS DE EXEMPLO ---

def print_callback(value: float) -> None:
    """Imprime cada valor recebido."""
    print(f"EMG: {value:.4f} V")


async def async_print_callback(value: float) -> None:
    """Versão assíncrona (mais lenta, não recomendada para alto throughput)."""
    print(f"EMG (async): {value:.4f} V")


# --- EXEMPLO DE USO COM LSL ---
async def example_with_lsl():
    """Exemplo: capturar dados e enviar para LSL."""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # Handler de sinais para parada graciosa
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    else:
        # Windows: Ctrl+C dispara KeyboardInterrupt
        pass

    # --- CRIAR ENGINE ---
    engine = EMGEngine(
        device_name="ESP32-EMG",  # Ajuste para seu dispositivo
        char_uuid="bef8d6c9-9c21-4c9e-b632-bd763f7a92bf",  # UUID BLE SPP
        sample_rate=500.0,
    )

    # --- SETUP LSL ---
    lsl_info = StreamInfo(
        name="EMG",
        type="EMG",
        channel_count=1,
        nominal_srate=engine.sample_rate,
        channel_format=cf_float32,
        source_id="emg-esp32-ble",
    )
    lsl_outlet = StreamOutlet(lsl_info, chunk_size=1)
    print("✓ LSL stream criada: 'EMG' (1 canal, 500 Hz)")

    # --- REGISTRAR CALLBACKS ---
    # Callback 1: Enviar para LSL
    def lsl_publisher(value: float) -> None:
        lsl_outlet.push_sample([value])

    # Callback 2: Imprimir valores (descomente para debug)
    # engine.subscribe(print_callback)

    engine.subscribe(lsl_publisher)

    # --- RODAR ---
    try:
        await engine.run(stop_event, max_run_seconds=None)  # Roda indefinidamente
    except KeyboardInterrupt:
        print("\n✓ Interrupção do usuário (Ctrl+C)")
    finally:
        engine.stop()


# --- EXEMPLO: DESCOBRIR DISPOSITIVOS ---
async def example_discover():
    """Escaneia e lista todos os dispositivos BLE disponíveis."""
    print("🔍 Escaneando dispositivos BLE (10s)...\n")
    
    devices = await BleakScanner.discover(timeout=10.0)
    
    if not devices:
        print("Nenhum dispositivo encontrado")
        return
    
    print(f"✓ {len(devices)} dispositivo(s) encontrado(s):\n")
    for i, device in enumerate(devices, 1):
        rssi = getattr(device, "rssi", None)
        rssi_text = f"{rssi:4d}" if isinstance(rssi, int) else " n/d"
        print(f"{i}. {device.name or 'Desconhecido':20s} | {device.address:17s} | RSSI: {rssi_text}")


# --- EXEMPLO: EXPLORAR CARACTERÍSTICAS ---
async def example_explore():
    """Conecta a um dispositivo e lista suas características."""
    engine = EMGEngine(device_name="ESP32-EMG")
    info = await engine.get_device_info()
    
    if info:
        import json
        print("\n" + json.dumps(info, indent=2, default=str))


if __name__ == "__main__":
    print("╔═══════════════════════════════════════════╗")
    print("║  EMG Engine - BLE com Bleak + LSL         ║")
    print("╚═══════════════════════════════════════════╝\n")
    
    try:
        # Escolha o exemplo:
        asyncio.run(example_with_lsl())
        
        # Ou para descobrir dispositivos:
        # asyncio.run(example_discover())
        
        # Ou para explorar características:
        # asyncio.run(example_explore())
        
    except KeyboardInterrupt:
        print("\n✓ Aplicação encerrada")
    except Exception as e:
        print(f"\n✗ Erro: {e}")
        import traceback
        traceback.print_exc()