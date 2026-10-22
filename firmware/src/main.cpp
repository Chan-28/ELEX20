/**
 * ELEX20 — ESP32-S3 · Classificação de Som Ambiente
 *
 * Fluxo:
 *   Microfone I2S → buffer PCM 16-bit 16 kHz
 *   → Edge Impulse classifier (MFCC/MFE no dispositivo)
 *   → resultado JSON → MQTT → Mosquitto → n8n → TimescaleDB
 *
 * Tópicos publicados (Mosquitto local):
 *   emg/inference/<DEVICE_ID>
 *     {"label":"chuva","confidence":0.92,"ts":12345,"device":"..."}
 *   emg/status/<DEVICE_ID>
 *     {"uptime_s":60,"heap":200000,"rssi":-52}
 *
 * Hardware testado:
 *   - ESP32-S3-DevKitC-1
 *   - Microfone INMP441 (I2S, mono, 16-bit)
 *     WS  → GPIO 42  |  SCK → GPIO 40  |  SD → GPIO 41
 *
 * Para integrar o modelo Edge Impulse:
 *   1. Exportar projeto EI → Deployment → Arduino library → .zip
 *   2. Extrair em firmware/lib/ei-model/
 *   3. Ajustar EI_MODEL_HEADER em platformio.ini
 *   4. Descomentar as linhas marcadas com "// EI:"
 *   5. Remover runInferenceMock()
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <driver/i2s.h>

// EI: descomente e ajuste ao nome do header exportado pelo Edge Impulse
// #include EI_MODEL_HEADER

// ── Pinos I2S (configuráveis em platformio.ini) ──────────────
#ifndef I2S_WS_PIN
#  define I2S_WS_PIN  42
#endif
#ifndef I2S_SCK_PIN
#  define I2S_SCK_PIN 40
#endif
#ifndef I2S_SD_PIN
#  define I2S_SD_PIN  41
#endif

// ── Parâmetros de áudio ───────────────────────────────────────
#ifndef AUDIO_SAMPLE_RATE
#  define AUDIO_SAMPLE_RATE 16000
#endif
#ifndef AUDIO_WINDOW_MS
#  define AUDIO_WINDOW_MS   1000
#endif

// Número de amostras na janela de inferência
static constexpr size_t AUDIO_WINDOW_SAMPLES =
    (AUDIO_SAMPLE_RATE * AUDIO_WINDOW_MS) / 1000;

// ── Credenciais (via platformio.ini build_flags) ─────────────
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
#  define DEVICE_ID "esp32s3-sound-01"
#endif

static const char TOPIC_INFERENCE[] = MQTT_TOPIC_INFERENCE "/" DEVICE_ID;
static const char TOPIC_STATUS[]    = MQTT_TOPIC_STATUS    "/" DEVICE_ID;

// ── Objetos ──────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// Buffer de áudio — alocado em PSRAM se disponível
static int16_t* audioBuf = nullptr;
static size_t   audioIdx = 0;
static bool     bufferFull = false;

// ── I2S ──────────────────────────────────────────────────────
static void i2sInit() {
    i2s_config_t cfg = {
        .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate          = AUDIO_SAMPLE_RATE,
        .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
        .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count        = 8,
        .dma_buf_len          = 512,
        .use_apll             = false,
        .tx_desc_auto_clear   = false,
        .fixed_mclk           = 0,
    };
    i2s_pin_config_t pins = {
        .bck_io_num   = I2S_SCK_PIN,
        .ws_io_num    = I2S_WS_PIN,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num  = I2S_SD_PIN,
    };
    ESP_ERROR_CHECK(i2s_driver_install(I2S_NUM_0, &cfg, 0, nullptr));
    ESP_ERROR_CHECK(i2s_set_pin(I2S_NUM_0, &pins));
    Serial.println("[I2S] Microfone inicializado");
}

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
        Serial.printf("\n[WiFi] IP: %s  RSSI: %d dBm\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
        Serial.println("\n[WiFi] Falha. Reiniciando...");
        ESP.restart();
    }
}

// ── MQTT ─────────────────────────────────────────────────────
static void mqttReconnect() {
    for (uint8_t i = 0; i < 5 && !mqtt.connected(); i++) {
        Serial.printf("[MQTT] Conectando a %s:%d ...\n", MQTT_HOST, MQTT_PORT);
        if (mqtt.connect(DEVICE_ID)) {
            Serial.println("[MQTT] Conectado.");
        } else {
            Serial.printf("[MQTT] rc=%d — aguardando 2s\n", mqtt.state());
            delay(2000);
        }
    }
}

// ── Publicar resultado ────────────────────────────────────────
static void publishInference(const char* label, float confidence) {
    StaticJsonDocument<128> doc;
    doc["label"]      = label;
    doc["confidence"] = confidence;
    doc["ts"]         = millis();
    doc["device"]     = DEVICE_ID;

    char payload[128];
    serializeJson(doc, payload, sizeof(payload));
    mqtt.publish(TOPIC_INFERENCE, payload, false);

    Serial.printf("[INF] %s  %.2f%%\n", label, confidence * 100.f);
}

static void publishStatus() {
    StaticJsonDocument<128> doc;
    doc["uptime_s"] = millis() / 1000;
    doc["heap"]     = ESP.getFreeHeap();
    doc["rssi"]     = WiFi.RSSI();
    doc["device"]   = DEVICE_ID;

    char payload[128];
    serializeJson(doc, payload, sizeof(payload));
    mqtt.publish(TOPIC_STATUS, payload, true);
}

// ── Inferência Edge Impulse ───────────────────────────────────
// EI: descomente este bloco inteiro quando o modelo estiver em lib/ei-model/
/*
static int getMicData(size_t offset, size_t length, float* out) {
    for (size_t i = 0; i < length; i++)
        out[i] = (float)audioBuf[offset + i] / 32768.f;
    return 0;
}

static void runInference() {
    signal_t signal;
    signal.total_length = AUDIO_WINDOW_SAMPLES;
    signal.get_data     = &getMicData;

    ei_impulse_result_t result = {0};
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    if (err != EI_IMPULSE_OK) {
        Serial.printf("[EI] Erro: %d\n", err);
        return;
    }

    // Encontra a classe com maior confiança
    uint8_t best = 0;
    for (uint8_t i = 1; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        if (result.classification[i].value > result.classification[best].value)
            best = i;
    }
    publishInference(result.classification[best].label,
                     result.classification[best].value);
}
*/

// Simulador — remove ao integrar o modelo real
static void runInferenceMock() {
    static const char* sounds[] = {
        "silencio", "fala", "chuva", "transito", "musica", "alarme"
    };
    static uint8_t idx = 0;
    float conf = 0.75f + (random(0, 25) / 100.f);
    publishInference(sounds[idx++ % 6], conf);
}

// ── Setup ─────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[ELEX20] Boot — classificação de som ambiente");

    // Aloca buffer de áudio na PSRAM (preferível) ou na heap normal
    size_t bufBytes = AUDIO_WINDOW_SAMPLES * sizeof(int16_t);
    if (psramFound()) {
        audioBuf = (int16_t*)ps_malloc(bufBytes);
        Serial.printf("[MEM] Buffer %.1f KB alocado na PSRAM\n", bufBytes / 1024.f);
    } else {
        audioBuf = (int16_t*)malloc(bufBytes);
        Serial.printf("[MEM] Buffer %.1f KB alocado na heap\n", bufBytes / 1024.f);
    }
    if (!audioBuf) {
        Serial.println("[MEM] ERRO: sem memória para o buffer de áudio!");
        ESP.restart();
    }

    i2sInit();
    connectWiFi();

    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setBufferSize(512);
    mqtt.setKeepAlive(30);
    mqttReconnect();
}

// ── Loop ──────────────────────────────────────────────────────
static uint32_t lastStatusMs = 0;

void loop() {
    if (WiFi.status() != WL_CONNECTED) connectWiFi();
    if (!mqtt.connected())             mqttReconnect();
    mqtt.loop();

    // Lê amostras do microfone I2S
    // O I2S retorna 32 bits por amostra (INMP441) → shift para obter 16 bits
    int32_t rawSample32;
    size_t  bytesRead = 0;
    i2s_read(I2S_NUM_0, &rawSample32, sizeof(rawSample32),
             &bytesRead, portMAX_DELAY);

    if (bytesRead == sizeof(rawSample32) && audioIdx < AUDIO_WINDOW_SAMPLES) {
        audioBuf[audioIdx++] = (int16_t)(rawSample32 >> 14);

        if (audioIdx >= AUDIO_WINDOW_SAMPLES) {
            audioIdx   = 0;
            bufferFull = true;
        }
    }

    // Inferência quando a janela estiver cheia
    if (bufferFull) {
        bufferFull = false;
        // runInference();     // ← habilitar com modelo EI real
        runInferenceMock();    // ← remover ao integrar modelo
    }

    // Heartbeat a cada 5 s
    if (millis() - lastStatusMs >= 5000UL) {
        lastStatusMs = millis();
        publishStatus();
    }
}
