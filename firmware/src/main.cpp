/**
 * ELEX20 — ESP32 Edge Impulse + MQTT
 *
 * Fluxo:
 *   ADS1115 (I2C) → buffer circular → Edge Impulse classifier
 *   → resultado JSON → MQTT → Mosquitto → n8n → TimescaleDB
 *
 * Tópicos publicados:
 *   emg/inference/<DEVICE_ID>  {"label":"...","confidence":0.95,"ts":12345}
 *   emg/status/<DEVICE_ID>     {"uptime_s":60,"heap":120000,"rssi":-55}
 *   emg/raw/<DEVICE_ID>        {"v":0.0012,"ts":12345}  (apenas se DEBUG_MQTT)
 *
 * Pré-requisito: exportar modelo do Edge Impulse como Arduino library,
 *   extrair em firmware/lib/ei-model/ e ajustar o include abaixo.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <LiquidCrystal_I2C.h>

// Edge Impulse — ajuste o nome do header ao modelo exportado
// Ex: se o projeto se chama "emg_classifier", o header será:
//   #include <emg_classifier_inferencing.h>
// Descomente quando o modelo estiver em lib/ei-model/
// #include <ei-model_inferencing.h>

// ── Pins ─────────────────────────────────────────────────────
#define SDA_PIN 21
#define SCL_PIN 22
#define POT_PIN 35  // potenciômetro de amplitude (opcional)

// ── Configuração (via platformio.ini build_flags) ────────────
#ifndef WIFI_SSID
#  define WIFI_SSID "YOUR_SSID"
#endif
#ifndef WIFI_PASS
#  define WIFI_PASS "YOUR_PASS"
#endif
#ifndef MQTT_HOST
#  define MQTT_HOST "192.168.1.100"
#endif
#ifndef MQTT_PORT
#  define MQTT_PORT 1883
#endif
#ifndef DEVICE_ID
#  define DEVICE_ID "esp32-emg-01"
#endif
#ifndef EI_WINDOW_SIZE
#  define EI_WINDOW_SIZE 500
#endif
#ifndef SAMPLE_RATE_HZ
#  define SAMPLE_RATE_HZ 500
#endif

// Tópicos MQTT completos (device_id sufixado)
static const char TOPIC_INFERENCE[] = MQTT_TOPIC_INFERENCE "/" DEVICE_ID;
static const char TOPIC_STATUS[]    = MQTT_TOPIC_STATUS    "/" DEVICE_ID;
#ifdef DEBUG_MQTT
static const char TOPIC_RAW[]       = MQTT_TOPIC_RAW       "/" DEVICE_ID;
#endif

// ── Objetos ──────────────────────────────────────────────────
Adafruit_ADS1115 ads;
LiquidCrystal_I2C lcd(0x27, 16, 2);  // endereço padrão PCF8574
WiFiClient        wifiClient;
PubSubClient      mqtt(wifiClient);

// Buffer circular para janela de inferência
static float     sampleBuf[EI_WINDOW_SIZE];
static uint16_t  sampleIdx   = 0;
static bool      bufferFull  = false;

// Intervalo de amostragem em µs
static const uint32_t SAMPLE_INTERVAL_US = 1000000UL / SAMPLE_RATE_HZ;
static uint32_t lastSampleUs = 0;

// Intervalo de status heartbeat (ms)
static const uint32_t STATUS_INTERVAL_MS = 5000;
static uint32_t lastStatusMs = 0;

// ── WiFi ─────────────────────────────────────────────────────
static void connectWiFi() {
    Serial.printf("[WiFi] Conectando a %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    uint8_t attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print('.');
        attempts++;
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Conectado. IP: %s  RSSI: %d dBm\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
        lcd.setCursor(0, 1);
        lcd.print(WiFi.localIP().toString());
    } else {
        Serial.println("\n[WiFi] Falha na conexão. Reiniciando...");
        ESP.restart();
    }
}

// ── MQTT ─────────────────────────────────────────────────────
static void mqttReconnect() {
    uint8_t retries = 0;
    while (!mqtt.connected() && retries < 5) {
        Serial.printf("[MQTT] Conectando a %s:%d ...\n", MQTT_HOST, MQTT_PORT);
        if (mqtt.connect(DEVICE_ID)) {
            Serial.println("[MQTT] Conectado.");
            lcd.setCursor(0, 0);
            lcd.print("MQTT OK         ");
        } else {
            Serial.printf("[MQTT] Falhou (rc=%d). Tentando em 2s...\n", mqtt.state());
            delay(2000);
            retries++;
        }
    }
    if (!mqtt.connected()) {
        Serial.println("[MQTT] Sem conexão após 5 tentativas. Verifique o broker.");
    }
}

// ── Publicar resultado de inferência ────────────────────────
static void publishInference(const char* label, float confidence) {
    StaticJsonDocument<128> doc;
    doc["label"]      = label;
    doc["confidence"] = confidence;
    doc["ts"]         = millis();
    doc["device"]     = DEVICE_ID;

    char payload[128];
    serializeJson(doc, payload, sizeof(payload));

    if (mqtt.publish(TOPIC_INFERENCE, payload, /*retained=*/false)) {
#ifdef DEBUG_MQTT
        Serial.printf("[MQTT] inference → %s\n", payload);
#endif
    }

    lcd.setCursor(0, 0);
    lcd.printf("%-10s %3d%%", label, (int)(confidence * 100));
}

// ── Publicar heartbeat de status ────────────────────────────
static void publishStatus() {
    StaticJsonDocument<128> doc;
    doc["uptime_s"] = millis() / 1000;
    doc["heap"]     = ESP.getFreeHeap();
    doc["rssi"]     = WiFi.RSSI();
    doc["device"]   = DEVICE_ID;

    char payload[128];
    serializeJson(doc, payload, sizeof(payload));
    mqtt.publish(TOPIC_STATUS, payload, /*retained=*/true);
}

// ── Inferência (wrapper Edge Impulse) ───────────────────────
// Descomente e adapte quando o modelo estiver disponível.
// static void runInference() {
//     signal_t signal;
//     numpy::signal_from_buffer(sampleBuf, EI_WINDOW_SIZE, &signal);
//
//     ei_impulse_result_t result;
//     EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
//     if (err != EI_IMPULSE_OK) return;
//
//     // Encontra label com maior confiança
//     uint8_t bestIdx = 0;
//     for (uint8_t i = 1; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
//         if (result.classification[i].value > result.classification[bestIdx].value)
//             bestIdx = i;
//     }
//     publishInference(result.classification[bestIdx].label,
//                      result.classification[bestIdx].value);
// }

// Simulador de inferência — remove quando o modelo real estiver integrado
static void runInferenceMock() {
    static const char* labels[] = {"repouso", "contracao", "relaxamento"};
    static uint8_t     idx      = 0;
    float conf = 0.80f + (random(0, 20) / 100.0f);
    publishInference(labels[idx % 3], conf);
    idx++;
}

// ── Setup ─────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Wire.begin(SDA_PIN, SCL_PIN);

    // LCD
    lcd.init();
    lcd.backlight();
    lcd.setCursor(0, 0);
    lcd.print("ELEX20 Boot...");

    // ADS1115
    if (!ads.begin()) {
        Serial.println("[ADS1115] Não encontrado — usando simulador");
    } else {
        ads.setGain(GAIN_TWOTHIRDS);  // ±6.144 V
        ads.setDataRate(RATE_ADS1115_860SPS);
        Serial.println("[ADS1115] OK");
    }

    connectWiFi();

    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setBufferSize(512);
    mqtt.setKeepAlive(30);
    mqttReconnect();

    lastSampleUs = micros();
    lastStatusMs = millis();
}

// ── Loop ──────────────────────────────────────────────────────
void loop() {
    // Reconexão automática
    if (WiFi.status() != WL_CONNECTED) connectWiFi();
    if (!mqtt.connected())             mqttReconnect();
    mqtt.loop();

    // Coleta de amostras
    uint32_t now = micros();
    if (now - lastSampleUs >= SAMPLE_INTERVAL_US) {
        lastSampleUs = now;

        // Lê ADS1115 canal 0 (ou simula se não disponível)
        int16_t raw    = ads.readADC_SingleEnded(0);
        float   voltV  = ads.computeVolts(raw);
        float   voltUV = voltV * 1e6f;  // µV

        sampleBuf[sampleIdx++] = voltUV;

        if (sampleIdx >= EI_WINDOW_SIZE) {
            sampleIdx  = 0;
            bufferFull = true;
        }

#ifdef DEBUG_MQTT
        // Publica amostras brutas (apenas em debug — alto volume)
        StaticJsonDocument<64> raw_doc;
        raw_doc["v"]  = voltUV;
        raw_doc["ts"] = millis();
        char raw_payload[64];
        serializeJson(raw_doc, raw_payload, sizeof(raw_payload));
        mqtt.publish(TOPIC_RAW, raw_payload);
#endif
    }

    // Inferência quando o buffer estiver cheio
    if (bufferFull) {
        bufferFull = false;
        // runInference();       // ← habilitar com modelo real
        runInferenceMock();      // ← remover quando modelo real estiver pronto
    }

    // Heartbeat de status
    if (millis() - lastStatusMs >= STATUS_INTERVAL_MS) {
        lastStatusMs = millis();
        publishStatus();
    }
}
