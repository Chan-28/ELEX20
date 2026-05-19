#ifndef CONFIG_H
#define CONFIG_H

// ═══════════════════════════════════════════════════════════
// CONFIGURAÇÕES DO PROJETO - ESP32 EMG via BLE
// ═══════════════════════════════════════════════════════════

// ── BLE Configuration ─────────────────────────────────────
#define BLE_DEVICE_NAME "ESP32-EMG"
#define BLE_SERVICE_UUID "180D"  // Health Thermometer Service
#define BLE_CHAR_UUID "bef8d6c9-9c21-4c9e-b632-bd763f7a92bf"

// ── I2C Configuration ────────────────────────────────────
#define I2C_SDA_PIN 21
#define I2C_SCL_PIN 22
#define I2C_FREQUENCY 400000  // Hz
#define ADS_I2C_ADDRESS 0x48

// ── ADS1115 Configuration ───────────────────────────────
#define ADS_CHANNEL 0
#define ADS_RESOLUTION 0.125f  // mV/bit
#define ADS_GAIN GAIN_ONE
#define ADS_DATA_RATE RATE_ADS1115_860SPS

// ── Sampling Configuration ──────────────────────────────
#define SAMPLE_RATE 500        // Hz
#define SAMPLING_INTERVAL_MS (1000 / SAMPLE_RATE)
#define PACKET_SIZE 8          // [timestamp (4B) + voltage (4B)]

// ── Calibration Configuration ───────────────────────────
#define CALIB_DURATION_MS 2000 // 2 seconds

// ── Serial Configuration ────────────────────────────────
#define SERIAL_BAUD 115200

// ── Debug Configuration ─────────────────────────────────
#define DEBUG_INTERVAL 100     // Print debug every N samples
#define DEBUG_ENABLED 1

#endif // CONFIG_H
