#include "debug.h"

void printStartupBanner() {
  Serial.printf("\n\n╔════════════════════════════════════════╗\n");
  Serial.printf("║   ESP32 EMG — BLE + ADS1115          ║\n");
  Serial.printf("║      (Bleak + LSL compatible)        ║\n");
  Serial.printf("╚════════════════════════════════════════╝\n\n");
}

void printComponentInit(const char* component) {
  Serial.printf("✓ %s inicializado\n", component);
}

void printSamplingStats(float voltage, uint32_t samples_sent) {
  Serial.print("📡 ");
  Serial.print(samples_sent);
  Serial.print(" amostras | Último: ");
  Serial.print(voltage, 4);
  Serial.printf(" V\n");
}

void printBLEStats(const SamplingState& samplingState) {
  Serial.printf("\n╔═══════════════════════════════╗\n");
  Serial.printf("║   Estatísticas BLE            ║\n");
  Serial.printf("║ Amostras enviadas: %lu       ║\n", samplingState.samples_sent);
  Serial.printf("║ Calibrado: %s                ║\n", samplingState.isCalibrated ? "Sim" : "Não");
  Serial.printf("║ Offset: %.4f V            ║\n", samplingState.offset);
  Serial.printf("╚═══════════════════════════════╝\n\n");
}
