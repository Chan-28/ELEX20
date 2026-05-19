#include "ble_callbacks.h"
#include <Arduino.h>
#include <BLEDevice.h>

// ─────────────────────────────────────────────────────────
// Global state for callbacks
// ─────────────────────────────────────────────────────────
extern bool deviceConnected;

void MyServerCallbacks::onConnect(BLEServer* pServer) {
  deviceConnected = true;
  Serial.printf("✓ Cliente BLE conectado\n");
  Serial.printf("  Dispositivos conectados: %d\n", pServer->getConnectedCount());
}

void MyServerCallbacks::onDisconnect(BLEServer* pServer) {
  deviceConnected = false;
  Serial.printf("⚠ Cliente BLE desconectado\n");
  // Restart advertising
  BLEDevice::startAdvertising();
}
