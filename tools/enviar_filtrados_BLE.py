import asyncio
from pylsl import resolve_stream, StreamInlet
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "ESP32_EMG_BLE"

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CHARACTERISTIC_UUID = "abcdefab-1234-5678-1234-abcdefabcdef"

STREAM_NAME = "EMG_Processado"

BLOCK_SIZE = 20


async def find_device():
    print("Procurando ESP32...")

    devices = await BleakScanner.discover(timeout=10)

    for device in devices:
        if device.name == DEVICE_NAME:
            print(f"Encontrado: {device.address}")
            return device

    return None


async def main():

    device = await find_device()

    if device is None:
        print("ESP32 não encontrado.")
        return

    print("Conectando ao ESP32...")

    async with BleakClient(device.address) as client:

        print("BLE conectado.")

        print(f"Procurando stream LSL '{STREAM_NAME}'...")

        streams = resolve_stream('name', STREAM_NAME)
        if not streams:
            print("Stream LSL não encontrado.")
            return
        
        inlet = StreamInlet(streams[0])

        print("LSL conectado.")

        buffer = []

        while True:

            sample, timestamp = inlet.pull_sample(timeout=1.0)

            if sample is None:
                continue

            valor = float(sample[0])

            buffer.append(valor)

            if len(buffer) >= BLOCK_SIZE:

                msg = ",".join(
                    f"{x:.4f}" for x in buffer
                )

                await client.write_gatt_char(
                    CHARACTERISTIC_UUID,
                    msg.encode("utf-8")
                )

                print(f"Enviado: {msg}")

                buffer.clear()


if __name__ == "__main__":
    asyncio.run(main())