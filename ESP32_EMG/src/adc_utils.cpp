#include "adc_utils.h"
#include <Arduino.h>
#include <Wire.h>

// ─────────────────────────────────────────────────────────
// Global ADS1115 instance
// ─────────────────────────────────────────────────────────
static Adafruit_ADS1115 ads;

bool initADS1115() {
  // Initialize I2C
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(I2C_FREQUENCY);

  // Initialize ADS1115
  if (!ads.begin(ADS_I2C_ADDRESS)) {
    Serial.printf("❌ ERRO: ADS1115 não encontrado no endereço 0x%X!\n", ADS_I2C_ADDRESS);
    return false;
  }

  ads.setGain(ADS_GAIN);
  ads.setDataRate(ADS_DATA_RATE);
  
  Serial.printf("✓ ADS1115 inicializado\n");
  Serial.printf("  - Endereço: 0x%X\n", ADS_I2C_ADDRESS);
  Serial.printf("  - Taxa de dados: 860 SPS\n");
  Serial.printf("  - Ganho: 1x (±6.144V)\n");
  
  return true;
}

float readEMGVoltage(const SamplingState& samplingState) {
  int16_t rawADC = ads.readADC_SingleEnded(ADS_CHANNEL);
  float voltage = (rawADC * ADS_RESOLUTION / 1000.0f) - samplingState.offset;
  return voltage;
}

void performCalibration(SamplingState& samplingState) {
  Serial.printf("⏳ Calibrando (%.1fms)... mantenha eletrodo ESTÁVEL\n", (float)CALIB_DURATION_MS);
  
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

  Serial.printf("✓ Calibração completa\n");
  Serial.printf("  - Offset: %.4f V\n", samplingState.offset);
  Serial.printf("  - Amostras coletadas: %d\n", samples);
}

Adafruit_ADS1115& getADS1115Instance() {
  return ads;
}
