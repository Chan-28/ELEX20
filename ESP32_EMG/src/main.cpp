/*
 * ═══════════════════════════════════════════════════════════
 * EMG via BLE (Bluetooth Low Energy) — ESP32 + ADS1115
 * ═══════════════════════════════════════════════════════════
 * 
 * Transmite dados via notificações BLE GATT
 * Compatível com Bleak (Python) e LSL
 *
 * CARACTERÍSTICAS:
 * ✓ Notificações BLE em tempo real
 * ✓ Timestamp em cada amostra
 * ✓ Calibração automática
 * ✓ Formato: [timestamp (4B) + voltage (4B float)]
 * ✓ Taxa: ~500 Hz
 * ✓ Código modularizado e bem documentado
 *
 * ESTRUTURA DE ARQUIVOS:
 * include/
 *   - config.h          → Constantes de configuração
 *   - structs.h         → Estruturas de dados
 *   - ble_callbacks.h   → Callbacks BLE
 *   - ble_utils.h       → Utilitários BLE
 *   - adc_utils.h       → Utilitários ADC/ADS1115
 *   - debug.h           → Funções de debug
 * src/
 *   - main.cpp          → Arquivo principal (este)
 *   - ble_callbacks.cpp → Implementação callbacks BLE
 *   - ble_utils.cpp     → Implementação utilitários BLE
 *   - adc_utils.cpp     → Implementação utilitários ADC
 *   - debug.cpp         → Implementação funções debug
 * ═══════════════════════════════════════════════════════════
 */

#include <Arduino.h>
#include "config.h"
#include "structs.h"
#include "ble_callbacks.h"
#include "ble_utils.h"
#include "adc_utils.h"
#include "debug.h"

// ═══════════════════════════════════════════════════════════
// GLOBAL STATE
// ═══════════════════════════════════════════════════════════

bool deviceConnected = false;

SamplingState samplingState = {
  .lastSampleTime = 0,
  .offset = 0.0f,
  .isCalibrated = false,
  .samples_sent = 0
};


// ═══════════════════════════════════════════════════════════
// SETUP - Inicialização do sistema
// ═══════════════════════════════════════════════════════════

void setup() {
  // Initialize Serial
  Serial.begin(SERIAL_BAUD);
  delay(1000);

  // Print startup banner
  printStartupBanner();

  // Initialize ADS1115 and I2C
  if (!initADS1115()) {
    Serial.printf("❌ ERRO: Falha na inicialização do ADS1115\n");
    while (1) delay(500);
  }

  // Initialize BLE (includes server creation and callbacks)
  if (!initBLE()) {
    Serial.printf("❌ ERRO: Falha na inicialização do BLE\n");
    while (1) delay(500);
  }

  // Start BLE Advertising
  startBLEAdvertising();
  Serial.printf("  Aguardando conexão de cliente...\n");

  // Perform calibration
  performCalibration(samplingState);

  Serial.printf("\n▶ Sistema pronto para transmitir dados!\n");
  Serial.printf("  Taxa de amostragem: %d Hz\n", SAMPLE_RATE);
  Serial.printf("  Intervalo entre amostras: %lu ms\n", SAMPLING_INTERVAL_MS);
}

// ═══════════════════════════════════════════════════════════
// LOOP PRINCIPAL - Amostragem e transmissão de dados EMG
// ═══════════════════════════════════════════════════════════

void loop() {
  // Aguarda conexão de cliente BLE
  if (!deviceConnected) {
    delay(100);
    return;
  }

  // Respeita intervalo de amostragem para não sobrecarregar
  uint32_t now = millis();
  if (now - samplingState.lastSampleTime < SAMPLING_INTERVAL_MS) {
    delay(1);
    return;
  }

  samplingState.lastSampleTime = now;

  // Realiza leitura do ADC
  float voltage = readEMGVoltage(samplingState);

  // Monta amostra EMG
  EMGSample sample = {
    .timestamp = (uint32_t)now,
    .voltage = voltage
  };

  // Cria pacote no formato BLE
  uint8_t packet[PACKET_SIZE];
  createEMGPacket(sample, packet);

  // Envia notificação BLE
  sendBLENotification(packet);

  samplingState.samples_sent++;

  // Debug a cada N amostras
  if (DEBUG_ENABLED && (samplingState.samples_sent % DEBUG_INTERVAL == 0)) {
    printSamplingStats(voltage, samplingState.samples_sent);
  }
}

// ═══════════════════════════════════════════════════════════
// FIM DO ARQUIVO
// ═══════════════════════════════════════════════════════════
// Todas as funções foram movidas para arquivos modulares:
// - adc_utils.cpp   → Funções de calibração e leitura ADC
// - ble_utils.cpp   → Funções de comunicação BLE
// - debug.cpp       → Funções de debug e printing
// ═══════════════════════════════════════════════════════════
