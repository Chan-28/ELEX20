/*
 * EMG via BLE (Bluetooth Low Energy) — ESP32 + ADS1115
 * 
 * Transmite dados via notificações BLE GATT
 * Compatível com Bleak (Python) e LSL
 *
 * Características:
 * ✓ Notificações BLE em tempo real
 * ✓ Timestamp em cada amostra
 * ✓ Calibração automática
 * ✓ Formato: [timestamp (4B) + voltage (4B float)]
 * ✓ Taxa: ~500 Hz
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ── CONFIGURAÇÕES ────────────────────────────────────────────
// BLE
const char* BLE_DEVICE_NAME = "ESP32-EMG";
const char* BLE_SERVICE_UUID = "180D";  // Health Thermometer Service
const char* BLE_CHAR_UUID = "bef8d6c9-9c21-4c9e-b632-bd763f7a92bf";

// ADS1115
const uint8_t ADS_CHANNEL = 0;
const float ADS_RESOLUTION = 0.125f; // mV/bit

// Amostragem
const uint16_t SAMPLE_RATE = 500;     // Hz
const uint32_t SAMPLING_INTERVAL_MS = 1000 / SAMPLE_RATE;

// Calibração
const uint32_t CALIB_DURATION_MS = 2000;

// ─────────────────────────────────────────────────────────────

Adafruit_ADS1115 ads;
BLECharacteristic* pCharacteristic = nullptr;
BLEServer* pServer = nullptr;
bool deviceConnected = false;

struct {
  uint32_t lastSampleTime = 0;
  float offset = 0.0f;
  bool isCalibrated = false;
  uint32_t samples_sent = 0;
} samplingState;

// ── CALLBACKS ────────────────────────────────────────────────

class MyServerCallbacks: public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) {
    deviceConnected = true;
    Serial.printf("✓ Cliente BLE conectado\n");
    Serial.printf("  Dispositivos conectados: %d\n", pServer->getConnectedCount());
  }

  void onDisconnect(BLEServer* pServer) {
    deviceConnected = false;
    Serial.printf("⚠ Cliente BLE desconectado\n");
    // Reinicia advertising
    BLEDevice::startAdvertising();
  }
};

// ── SETUP ────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.printf("\n\n╔════════════════════════════════════════╗");
  Serial.printf("║   ESP32 EMG — BLE + ADS1115          ║");
  Serial.printf("║      (Bleak + LSL compatible)        ║");
  Serial.printf("╚════════════════════════════════════════╝\n");

  // ─ I2C & ADS1115 ─
  Wire.begin(21, 22);
  Wire.setClock(400000);

  if (!ads.begin(0x48)) {
    Serial.printf("❌ ERRO: ADS1115 não encontrado!\n");
    while (1) delay(500);
  }

  ads.setGain(GAIN_ONE);
  ads.setDataRate(RATE_ADS1115_860SPS);
  Serial.printf("✓ ADS1115 inicializado\n");

  // ─ BLE Device ─
  BLEDevice::init(BLE_DEVICE_NAME);
  Serial.printf("✓ BLE Device inicializado: %s\n", BLE_DEVICE_NAME);
  Serial.printf(BLE_DEVICE_NAME);

  // ─ BLE Server ─
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  // ─ BLE Service ─
  BLEService* pService = pServer->createService(BLEUUID(BLE_SERVICE_UUID));

  // ─ BLE Characteristic ─
  pCharacteristic = pService->createCharacteristic(
    BLEUUID(BLE_CHAR_UUID),
    BLECharacteristic::PROPERTY_READ |
    BLECharacteristic::PROPERTY_NOTIFY |
    BLECharacteristic::PROPERTY_INDICATE
  );

  // ─ CCCD (Client Characteristic Configuration Descriptor) ─
  pCharacteristic->addDescriptor(new BLE2902());
  pCharacteristic->setNotifyProperty(true);

  pService->start();

  // ─ BLE Advertising ─
  BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(BLEUUID(BLE_SERVICE_UUID));
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();

  Serial.printf("✓ BLE Advertising iniciado\n");
  Serial.printf("  Aguardando conexão de cliente...\n");

  // ─ Calibração ─
  Serial.printf("⏳ Calibrando (2s)... mantenha eletrodo ESTÁVEL\n");
  performCalibration();
  Serial.printf("✓ Calibração completa\n");

  Serial.printf("▶ Pronto para transmitir dados!\n");
}

// ── LOOP PRINCIPAL ───────────────────────────────────────────

void loop() {
  // Se não há cliente conectado, apenas aguarde
  if (!deviceConnected) {
    delay(100);
    return;
  }

  // Respeita intervalo de amostragem
  uint32_t now = millis();
  if (now - samplingState.lastSampleTime < SAMPLING_INTERVAL_MS) {
    delay(1);
    return;
  }

  samplingState.lastSampleTime = now;

  // ─ Leitura do ADC ─
  int16_t rawADC = ads.readADC_SingleEnded(ADS_CHANNEL);
  float voltage = (rawADC * ADS_RESOLUTION / 1000.0f) - samplingState.offset;

  // ─ Montar pacote: [timestamp (4B) + voltage (4B float)] ─
  uint8_t data[8];
  
  // Timestamp em ms (4 bytes, little-endian)
  uint32_t timestamp = (uint32_t)now;
  data[0] = (timestamp >> 0) & 0xFF;
  data[1] = (timestamp >> 8) & 0xFF;
  data[2] = (timestamp >> 16) & 0xFF;
  data[3] = (timestamp >> 24) & 0xFF;

  // Voltage em float (4 bytes, little-endian)
  uint32_t voltage_bits = *(uint32_t*)&voltage;
  data[4] = (voltage_bits >> 0) & 0xFF;
  data[5] = (voltage_bits >> 8) & 0xFF;
  data[6] = (voltage_bits >> 16) & 0xFF;
  data[7] = (voltage_bits >> 24) & 0xFF;

  // ─ Enviar notificação ─
  if (pCharacteristic != nullptr) {
    pCharacteristic->setValue(data, 8);
    pCharacteristic->notify();  // Enviar como notificação

    samplingState.samples_sent++;

    // ─ Debug a cada 100 amostras ─
    if (samplingState.samples_sent % 100 == 0) {
      Serial.print("📡 ");
      Serial.print(samplingState.samples_sent);
      Serial.print(" amostras | Último: ");
      Serial.print(voltage, 4);
      Serial.printf(" V\n");
    }
  }
}

// ── FUNÇÕES ──────────────────────────────────────────────────

void performCalibration() {
  uint32_t calibStartTime = millis();
  float calibSum = 0.0f;
  uint16_t samples = 0;

  while (millis() - calibStartTime < CALIB_DURATION_MS) {
    int16_t rawADC = ads.readADC_SingleEnded(ADS_CHANNEL);
    float voltage = rawADC * ADS_RESOLUTION / 1000.0f;

    calibSum += voltage;
    samples++;
    delay(2);
  }

  samplingState.offset = calibSum / samples;
  samplingState.isCalibrated = true;

  Serial.printf("  Offset calibrado: %f V\n", samplingState.offset);
  Serial.print(samplingState.offset, 4);
  Serial.printf(" V");
}

// Função auxiliar para converter float para bytes
void floatToBytes(float value, uint8_t* bytes) {
  uint32_t bits = *(uint32_t*)&value;
  bytes[0] = (bits >> 0) & 0xFF;
  bytes[1] = (bits >> 8) & 0xFF;
  bytes[2] = (bits >> 16) & 0xFF;
  bytes[3] = (bits >> 24) & 0xFF;
}

// Opcional: Debug de conexão
void printBLEStats() {
  Serial.printf("\n╔═══════════════════════════════╗");
  Serial.printf("║   Estatísticas BLE            ║");
  Serial.printf("║ Conectado: ");
  Serial.printf(deviceConnected ? "Sim" : "Não");
  Serial.printf("║ Amostras enviadas: ");
  Serial.printf("%lu", samplingState.samples_sent);
  Serial.printf("╚═══════════════════════════════╝\n");
}
