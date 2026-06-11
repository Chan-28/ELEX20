/* OBS.: RODAR ISSO SOMENTE NO ARDUINO IDE COM AS DEVIDAS DEPENDÊNCIAS INSTALADAS (Adafruit ADS1X15, LiquidCrystal_I2C, BLE) E CONFIGURAÇÕES CORRETAS DE PINAGEM E ENDEREÇOS I2C.
 * ═══════════════════════════════════════════════════════════
 * EMG via BLE — ESP32 + ADS1115 + LCD HD44780 16x2 + Simulador
 * INICIALIZAÇÃO FORÇADA DO LCD
 * ═══════════════════════════════════════════════════════════
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <LiquidCrystal_I2C.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <math.h>

// ═══════════════════════════════════════════════════════════
// CONFIGURAÇÕES
// ═══════════════════════════════════════════════════════════

#define SERIAL_BAUD             9600
#define I2C_SDA_PIN             21
#define I2C_SCL_PIN             22
#define I2C_FREQUENCY           400000
#define ADS_I2C_ADDRESS         0x48
#define ADS_CHANNEL             0
#define ADS_GAIN                GAIN_TWOTHIRDS
#define ADS_DATA_RATE           RATE_ADS1115_860SPS
#define ADS_RESOLUTION          0.1875f

#define LCD_COLS                16
#define LCD_ROWS                2
#define LCD_UPDATE_INTERVAL_MS  200

#define SAMPLE_RATE             1500
#define SAMPLING_INTERVAL_MS    (1000 / SAMPLE_RATE)

#define BLE_DEVICE_NAME         "ESP32_EMG"
#define BLE_SERVICE_UUID        "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define BLE_CHAR_UUID           "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
#define PACKET_SIZE             8

#define POT_PIN                 35

// ╔════════════════════════════════════════════════════════╗
// ║ MODO DE AMPLITUDE DO POTENCIÔMETRO                    ║
// ║ 1 = LINEAR | 2 = EXPONENCIAL (recomendado) | 3 = MULT ║
// ╚════════════════════════════════════════════════════════╝
#define AMP_MODE_LINEAR         1
#define AMP_MODE_EXPONENTIAL    2
#define AMP_MODE_MULTIPLIER     3
#define AMPLITUDE_MODE          AMP_MODE_EXPONENTIAL

#define AMPLITUDE_MIN_LINEAR    50.0f
#define AMPLITUDE_MAX_LINEAR    800.0f

#define AMPLITUDE_MIN_EXP       50.0f
#define AMPLITUDE_MAX_EXP       2000.0f

#define AMPLITUDE_BASE_MULT     100.0f
#define AMPLITUDE_MULTIPLIER    20.0f

#define POT_SMOOTH_ALPHA        0.05f
#define BURST_FREQ_HZ           80.0f
#define BURST_DURATION_S        0.3f
#define BURST_INTERVAL_S        1.0f
#define NOISE_STD_BASE          20.0f
#define MOTION_ART_FREQ_HZ      3.0f
#define BASELINE_OFFSET         2048.0f

#define DEBUG_ENABLED           true
#define DEBUG_INTERVAL          100

// ═══════════════════════════════════════════════════════════
// ESTRUTURAS
// ═══════════════════════════════════════════════════════════

struct EMGSample {
  uint32_t timestamp;
  float    voltage;
};

struct SamplingState {
  uint32_t lastSampleTime;
  uint32_t lastLcdUpdate;
  uint32_t lastPotUpdate;
  uint32_t samples_sent;
  float    offset;
  bool     isCalibrated;
  float    potRaw;
  float    potSmoothed;
  float    amplitude;
  float    lastVoltage;
};

// ═══════════════════════════════════════════════════════════
// ESTADO GLOBAL
// ═══════════════════════════════════════════════════════════

bool deviceConnected = false;
bool simulatorMode   = false;
bool lcdConnected    = false;
byte lcdAddr         = 0;

SamplingState samplingState = {
  .lastSampleTime = 0,
  .lastLcdUpdate  = 0,
  .lastPotUpdate  = 0,
  .samples_sent   = 0,
  .offset         = 0.0f,
  .isCalibrated   = false,
  .potRaw         = 0.5f,
  .potSmoothed    = 0.5f,
  .amplitude      = 100.0f,
  .lastVoltage    = 0.0f,
};

static Adafruit_ADS1115    ads;
static LiquidCrystal_I2C*  lcd = nullptr;
static BLECharacteristic*  pCharacteristic = nullptr;
static BLEServer*          pServer         = nullptr;

// ═══════════════════════════════════════════════════════════
// CALCULAR AMPLITUDE (conforme modo selecionado)
// ═══════════════════════════════════════════════════════════

float calculateAmplitude(float normalizedPot) {
  switch (AMPLITUDE_MODE) {
    case AMP_MODE_LINEAR:
      return AMPLITUDE_MIN_LINEAR + 
             normalizedPot * (AMPLITUDE_MAX_LINEAR - AMPLITUDE_MIN_LINEAR);
    
    case AMP_MODE_EXPONENTIAL: {
      float exponent = 2.5f;
      float normalized = powf(normalizedPot, exponent);
      return AMPLITUDE_MIN_EXP + 
             normalized * (AMPLITUDE_MAX_EXP - AMPLITUDE_MIN_EXP);
    }
    
    case AMP_MODE_MULTIPLIER:
      return AMPLITUDE_BASE_MULT + 
             normalizedPot * AMPLITUDE_MULTIPLIER * AMPLITUDE_BASE_MULT;
    
    default:
      return 100.0f;
  }
}

// ═══════════════════════════════════════════════════════════
// DETECÇÃO DE LCD I2C
// ═══════════════════════════════════════════════════════════

byte findLCDAddress() {
  Serial.println("\n🔍 Procurando LCD I2C (HD44780 16x2 + PCF8574)...");
  
  byte addresses[] = {0x27, 0x3F, 0x20, 0x21, 0x3E};
  
  for (byte addr : addresses) {
    Wire.beginTransmission(addr);
    byte error = Wire.endTransmission();
    
    if (error == 0) {
      Serial.printf("✓ LCD encontrado no endereço: 0x%X\n\n", addr);
      return addr;
    }
  }
  
  Serial.println("⚠ LCD não encontrado nos endereços esperados\n");
  return 0;
}

bool initLCD(byte addr) {
  if (addr == 0) return false;
  
  try {
    lcd = new LiquidCrystal_I2C(addr, LCD_COLS, LCD_ROWS);
    
    // ╔════════════════════════════════════════════════════════╗
    // ║ INICIALIZAÇÃO FORÇADA - SEQUÊNCIA CRÍTICA              ║
    // ╚════════════════════════════════════════════════════════╝
    
    Serial.printf("  → init()...");
    lcd->init();
    delay(500);  // ⚠️ DELAY IMPORTANTE!
    Serial.println(" OK");
    
    Serial.printf("  → backlight()...");
    lcd->backlight();
    delay(200);
    Serial.println(" OK");
    
    Serial.printf("  → clear()...");
    lcd->clear();
    delay(200);
    Serial.println(" OK");
    
    Serial.printf("  → setCursor(0,0)...");
    lcd->setCursor(0, 0);
    delay(100);
    Serial.println(" OK");
    
    Serial.printf("  → print('EMG')...");
    lcd->print("EMG Inicializando");
    delay(200);
    Serial.println(" OK");
    
    Serial.printf("  → setCursor(0,1)...");
    lcd->setCursor(0, 1);
    delay(100);
    Serial.println(" OK");
    
    Serial.printf("  → print('HD44780')...");
    lcd->print("HD44780 16x2");
    delay(500);
    Serial.println(" OK");
    
    Serial.printf("\n✓ LCD inicializado com sucesso (0x%X)\n", addr);
    return true;
    
  } catch (...) {
    Serial.printf("❌ Erro ao inicializar LCD (0x%X)\n", addr);
    lcd = nullptr;
    return false;
  }
}

void updateLCD(const SamplingState& s) {
  if (lcd == nullptr) return;
  
  uint32_t now = millis();
  if (now - s.lastLcdUpdate < LCD_UPDATE_INTERVAL_MS) return;
  
  const_cast<SamplingState&>(s).lastLcdUpdate = now;

  // Linha 0: modo + contador + status BLE
  lcd->setCursor(0, 0);
  char line0[17];
  snprintf(line0, sizeof(line0), "[%c]#%-6lu %s   ",
    simulatorMode ? 'S' : 'R',
    (unsigned long)(s.samples_sent % 1000000UL),
    deviceConnected ? "●" : "○");
  lcd->print(line0);

  // Linha 1: Potenciômetro % + Amplitude
  lcd->setCursor(0, 1);
  char line1[17];
  int potPercent = (int)(s.potSmoothed * 100.0f);
  snprintf(line1, sizeof(line1), "Pot:%3d%% A:%.0f ",
    potPercent,
    s.amplitude);
  lcd->print(line1);
}

// ═══════════════════════════════════════════════════════════
// DEBUG
// ═══════════════════════════════════════════════════════════

void printStartupBanner() {
  Serial.printf("\n\n╔════════════════════════════════════════╗\n");
  Serial.printf("║   ESP32 EMG — BLE + ADS1115 + LCD    ║\n");
  Serial.printf("║      VERSÃO 4.0 - FINAL              ║\n");
  Serial.printf("║   LCD: HD44780 16x2 + PCF8574        ║\n");
  Serial.printf("╚════════════════════════════════════════╝\n\n");
}

void printSamplingStats(const SamplingState& s) {
  int potPercent = (int)(s.potSmoothed * 100.0f);
  Serial.printf("📡 #%lu | %.3f V | Pot:%d%% | Amp:%.0f mV\n",
    (unsigned long)s.samples_sent,
    s.lastVoltage,
    potPercent,
    s.amplitude);
}

// ═══════════════════════════════════════════════════════════
// BLE CALLBACKS
// ═══════════════════════════════════════════════════════════

class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    deviceConnected = true;
    Serial.printf("✓ Cliente BLE conectado\n");
  }
  void onDisconnect(BLEServer*) override {
    deviceConnected = false;
    Serial.printf("⚠ Cliente BLE desconectado\n");
    BLEDevice::startAdvertising();
  }
};

// ═══════════════════════════════════════════════════════════
// BLE INIT
// ═══════════════════════════════════════════════════════════

bool initBLE() {
  BLEDevice::init(BLE_DEVICE_NAME);
  Serial.printf("✓ BLE Device inicializado\n");

  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService* pService = pServer->createService(BLEUUID(BLE_SERVICE_UUID));
  pCharacteristic = pService->createCharacteristic(
    BLEUUID(BLE_CHAR_UUID),
    BLECharacteristic::PROPERTY_READ   |
    BLECharacteristic::PROPERTY_NOTIFY |
    BLECharacteristic::PROPERTY_INDICATE
  );
  pCharacteristic->addDescriptor(new BLE2902());
  pCharacteristic->setNotifyProperty(true);

  pService->start();
  Serial.printf("✓ BLE Service criado\n");
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
}

void floatToBytes(float value, uint8_t* bytes) {
  uint32_t bits;
  memcpy(&bits, &value, 4);
  bytes[0] = (bits >>  0) & 0xFF;
  bytes[1] = (bits >>  8) & 0xFF;
  bytes[2] = (bits >> 16) & 0xFF;
  bytes[3] = (bits >> 24) & 0xFF;
}

void createEMGPacket(const EMGSample& sample, uint8_t* packet) {
  uint32_t ts = sample.timestamp;
  packet[0] = (ts >>  0) & 0xFF;
  packet[1] = (ts >>  8) & 0xFF;
  packet[2] = (ts >> 16) & 0xFF;
  packet[3] = (ts >> 24) & 0xFF;
  floatToBytes(sample.voltage, &packet[4]);
}

void sendBLENotification(const uint8_t* packet) {
  if (pCharacteristic != nullptr) {
    pCharacteristic->setValue(const_cast<uint8_t*>(packet), PACKET_SIZE);
    pCharacteristic->notify();
  }
}

// ═══════════════════════════════════════════════════════════
// ADS1115
// ═══════════════════════════════════════════════════════════

bool initADS1115() {
  if (!ads.begin(ADS_I2C_ADDRESS)) {
    Serial.printf("⚠ ADS1115 não encontrado → Modo SIMULADO\n");
    return false;
  }

  ads.setGain(ADS_GAIN);
  ads.setDataRate(ADS_DATA_RATE);
  Serial.printf("✓ ADS1115 inicializado\n");
  return true;
}

float readEMGVoltage(const SamplingState& s) {
  int16_t rawADC = ads.readADC_SingleEnded(ADS_CHANNEL);
  return (rawADC * ADS_RESOLUTION / 1000.0f) - s.offset;
}

// ═══════════════════════════════════════════════════════════
// SIMULADOR EMG SINTÉTICO
// ═══════════════════════════════════════════════════════════

float gaussianNoise(float std) {
  static bool  hasSpare = false;
  static float spare;
  if (hasSpare) { hasSpare = false; return std * spare; }
  float u, v, s;
  do {
    u = (random(10000) / 5000.0f) - 1.0f;
    v = (random(10000) / 5000.0f) - 1.0f;
    s = u * u + v * v;
  } while (s >= 1.0f || s == 0.0f);
  s = sqrtf(-2.0f * logf(s) / s);
  spare    = v * s;
  hasSpare = true;
  return std * u * s;
}

void updatePotentiometer(SamplingState& s) {
  uint32_t now = millis();
  if (now - s.lastPotUpdate < 50) return;
  s.lastPotUpdate = now;
  
  float rawValue = (float)analogRead(POT_PIN);
  s.potRaw = rawValue / 4095.0f;
  s.potSmoothed = POT_SMOOTH_ALPHA * s.potRaw + 
                  (1.0f - POT_SMOOTH_ALPHA) * s.potSmoothed;
  s.amplitude = calculateAmplitude(s.potSmoothed);
  
  static int counter = 0;
  if (++counter >= 20) {
    int potPercent = (int)(s.potSmoothed * 100.0f);
    Serial.printf("  [POT] %d%% → Amplitude: %.1f mV\n", 
      potPercent,
      s.amplitude);
    counter = 0;
  }
}

float generateSimulatedEMG(float t, float amplitude) {
  float cyclePos = fmod(t, BURST_INTERVAL_S);
  float halfDur  = BURST_DURATION_S / 2.0f;
  float sigma    = halfDur / 2.5f;
  float envelope = (cyclePos < BURST_DURATION_S)
    ? expf(-0.5f * powf((cyclePos - halfDur) / sigma, 2.0f))
    : 0.0f;

  float emg  = amplitude * envelope * sinf(2.0f * M_PI * BURST_FREQ_HZ * t);
  emg       += 0.3f * amplitude * envelope * sinf(4.0f * M_PI * BURST_FREQ_HZ * t);

  float noiseStd = NOISE_STD_BASE * (amplitude / 1000.0f) + 5.0f;
  emg += gaussianNoise(noiseStd);

  emg += (amplitude * 0.05f) * sinf(2.0f * M_PI * MOTION_ART_FREQ_HZ * t);

  float adcVal = constrain(emg + BASELINE_OFFSET, 0.0f, 4095.0f);
  return (adcVal / 4095.0f) * 3.3f;
}

// ═══════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(1500);
  Serial.flush();
  printStartupBanner();

  // I2C
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(I2C_FREQUENCY);
  delay(200);

  // Detecta LCD
  lcdAddr = findLCDAddress();
  if (lcdAddr != 0) {
    lcdConnected = initLCD(lcdAddr);
    delay(1000);
  } else {
    Serial.println("⚠ LCD não encontrado. Continuando sem LCD...\n");
  }

  // ADC
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  // ADS1115
  simulatorMode = !initADS1115();
  
  if (simulatorMode) {
    Serial.printf("✓ Modo SIMULADO ativado\n");
    if (lcd) {
      lcd->clear();
      lcd->setCursor(0, 0);
      lcd->print("[SIM] Modo");
      lcd->setCursor(0, 1);
      lcd->print("Simulado");
      delay(2000);
    }
  } else {
    Serial.printf("✓ Modo REAL (ADS1115)\n");
    if (lcd) {
      lcd->clear();
      lcd->setCursor(0, 0);
      lcd->print("[REAL] ADS1115");
      delay(2000);
    }
  }

  // BLE
  if (!initBLE()) {
    Serial.printf("❌ Erro na inicialização BLE\n");
    while (1) delay(500);
  }
  startBLEAdvertising();

  delay(500);
  if (lcd) {
    lcd->clear();
  }

  Serial.printf("\n▶ Sistema PRONTO!\n");
  Serial.printf("  Taxa: %d Hz\n", SAMPLE_RATE);
  Serial.printf("  Potenciômetro: GPIO %d\n\n", POT_PIN);
}

// ═══════════════════════════════════════════════════════════
// LOOP PRINCIPAL
// ═══════════════════════════════════════════════════════════

void loop() {
  uint32_t now = millis();

  if (simulatorMode) {
    updatePotentiometer(samplingState);
  }

  updateLCD(samplingState);

  if (now - samplingState.lastSampleTime < SAMPLING_INTERVAL_MS) {
    delay(1);
    return;
  }
  samplingState.lastSampleTime = now;

  float voltage = simulatorMode
    ? generateSimulatedEMG(now / 1000.0f, samplingState.amplitude)
    : readEMGVoltage(samplingState);

  samplingState.lastVoltage = voltage;

  if (deviceConnected) {
    EMGSample sample = { .timestamp = now, .voltage = voltage };
    uint8_t packet[PACKET_SIZE];
    createEMGPacket(sample, packet);
    sendBLENotification(packet);
  }

  samplingState.samples_sent++;

  if (DEBUG_ENABLED && (samplingState.samples_sent % DEBUG_INTERVAL == 0)) {
    printSamplingStats(samplingState);
  }
}
