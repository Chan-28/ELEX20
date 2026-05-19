#include "ble_utils.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Arduino.h>
#include "ble_callbacks.h"

// ─────────────────────────────────────────────────────────
// Global BLE instances
// ─────────────────────────────────────────────────────────
static BLECharacteristic* pCharacteristic = nullptr;
static BLEServer* pServer = nullptr;

bool initBLE() {
  // Initialize BLE Device
  BLEDevice::init(BLE_DEVICE_NAME);
  Serial.printf("✓ BLE Device inicializado: %s\n", BLE_DEVICE_NAME);

  // Create BLE Server
  pServer = BLEDevice::createServer();
  
  // Set callbacks
  pServer->setCallbacks(new MyServerCallbacks());
  
  Serial.printf("✓ BLE Server criado\n");

  // Create BLE Service
  BLEService* pService = pServer->createService(BLEUUID(BLE_SERVICE_UUID));
  Serial.printf("✓ BLE Service criado: %s\n", BLE_SERVICE_UUID);

  // Create BLE Characteristic
  pCharacteristic = pService->createCharacteristic(
    BLEUUID(BLE_CHAR_UUID),
    BLECharacteristic::PROPERTY_READ |
    BLECharacteristic::PROPERTY_NOTIFY |
    BLECharacteristic::PROPERTY_INDICATE
  );

  // Add CCCD (Client Characteristic Configuration Descriptor)
  pCharacteristic->addDescriptor(new BLE2902());
  pCharacteristic->setNotifyProperty(true);

  pService->start();
  Serial.printf("✓ BLE Characteristic criada: %s\n", BLE_CHAR_UUID);

  return true;
}

void startBLEAdvertising() {
  BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(BLEUUID(BLE_SERVICE_UUID));
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();

  Serial.printf("✓ BLE Advertising iniciado\n");
  Serial.printf("  - Nome: %s\n", BLE_DEVICE_NAME);
  Serial.printf("  - UUID Service: %s\n", BLE_SERVICE_UUID);
}

void floatToBytes(float value, uint8_t* bytes) {
  uint32_t bits = *(uint32_t*)&value;
  bytes[0] = (bits >> 0) & 0xFF;
  bytes[1] = (bits >> 8) & 0xFF;
  bytes[2] = (bits >> 16) & 0xFF;
  bytes[3] = (bits >> 24) & 0xFF;
}

void createEMGPacket(const EMGSample& sample, uint8_t* packet) {
  // Timestamp em ms (4 bytes, little-endian)
  uint32_t timestamp = sample.timestamp;
  packet[0] = (timestamp >> 0) & 0xFF;
  packet[1] = (timestamp >> 8) & 0xFF;
  packet[2] = (timestamp >> 16) & 0xFF;
  packet[3] = (timestamp >> 24) & 0xFF;

  // Voltage em float (4 bytes, little-endian)
  floatToBytes(sample.voltage, &packet[4]);
}

void sendBLENotification(const uint8_t* packet) {
  if (pCharacteristic != nullptr) {
    pCharacteristic->setValue(const_cast<uint8_t*>(packet), PACKET_SIZE);
    pCharacteristic->notify();
  }
}

bool isBLEConnected() {
  // Check if server exists and has connected clients
  if (pServer != nullptr) {
    return pServer->getConnectedCount() > 0;
  }
  return false;
}

BLECharacteristic* getBLECharacteristic() {
  return pCharacteristic;
}
