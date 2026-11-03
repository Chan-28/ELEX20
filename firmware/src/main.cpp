/**
 * ELEX20 — ESP32-S3 · Percepção sonora háptica
 *
 * Fluxo:
 *   4 microfones INMP441 (I2S0 mestre + I2S1 escravo, clock compartilhado)
 *   → mistura mono 16 kHz → Edge Impulse (YAMNet) → classe + confiança
 *   → direção por GCC-PHAT (8 setores) quando há som de alerta
 *   → motor do setor + JSON MQTT → Mosquitto → n8n → TimescaleDB
 *
 * Tópicos (Mosquitto local):
 *   sound/inference/<DEVICE_ID>  {"label","confidence","ts","device",
 *                                  "direction_deg","sector","doa_confidence"[,"mock"]}
 *   sound/status/<DEVICE_ID>     {"uptime_s","heap","rssi","device",+ ajustes atuais}
 *   sound/cmd/<DEVICE_ID>        (assinado) {"key":"threshold","value":0.7}
 *
 * Microfones (cada INMP441 em formato I2S, 32 bits, 16 kHz):
 *   I2S0: esquerdo = frente (L/R em GND), direito = trás (L/R em VDD)
 *   I2S1: esquerdo = direita (L/R em GND), direito = esquerda (L/R em VDD)
 *   I2S1 escuta o mesmo BCLK/WS que o I2S0 gera; só o pino SD é próprio.
 *
 * Para integrar o modelo Edge Impulse:
 *   1. Exportar projeto EI → Deployment → Arduino library → .zip
 *   2. Extrair em firmware/lib/ei-model/
 *   3. Ajustar EI_MODEL_HEADER em platformio.ini
 *   Com o header presente, a inferência real é compilada sozinha.
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <driver/gpio.h>
#include <driver/i2s.h>

#include "doa.h"
#include "settings.h"

#ifndef ESP_ARDUINO_VERSION_MAJOR
#  define ESP_ARDUINO_VERSION_MAJOR 2
#endif

#if defined(EI_MODEL_HEADER) && __has_include(EI_MODEL_HEADER)
#  include EI_MODEL_HEADER
#  define ELEX_HAS_EI_MODEL 1
#endif

// ── Pinos (configuráveis em platformio.ini) ──────────────────
#ifndef I2S_WS_PIN
#  define I2S_WS_PIN  42
#endif
#ifndef I2S_SCK_PIN
#  define I2S_SCK_PIN 40
#endif
#ifndef I2S_SD_PIN
#  define I2S_SD_PIN  41   // I2S0: frente + trás
#endif
#ifndef I2S1_SD_PIN
#  define I2S1_SD_PIN 39   // I2S1: direita + esquerda
#endif
// Motores de vibração (MOSFET por PWM): frente, direita, trás, esquerda.
// Evite GPIO 26-37 (flash/PSRAM octal).
#ifndef MOTOR_PIN_FRONT
#  define MOTOR_PIN_FRONT 4
#endif
#ifndef MOTOR_PIN_RIGHT
#  define MOTOR_PIN_RIGHT 5
#endif
#ifndef MOTOR_PIN_BACK
#  define MOTOR_PIN_BACK  6
#endif
#ifndef MOTOR_PIN_LEFT
#  define MOTOR_PIN_LEFT  7
#endif

// ── Parâmetros de áudio ───────────────────────────────────────
#ifndef AUDIO_SAMPLE_RATE
#  define AUDIO_SAMPLE_RATE 16000
#endif
#ifndef AUDIO_WINDOW_MS
#  define AUDIO_WINDOW_MS   975
#endif
#ifndef MIC_RADIUS_M
#  define MIC_RADIUS_M 0.09f
#endif

// A janela vem do modelo quando ele existe; senão da configuração
#ifdef ELEX_HAS_EI_MODEL
static_assert(static_cast<int>(EI_CLASSIFIER_FREQUENCY) == AUDIO_SAMPLE_RATE,
              "AUDIO_SAMPLE_RATE deve coincidir com a frequência do projeto Edge Impulse");
static constexpr size_t AUDIO_WINDOW_SAMPLES = EI_CLASSIFIER_RAW_SAMPLE_COUNT;
#else
static constexpr size_t AUDIO_WINDOW_SAMPLES = (AUDIO_SAMPLE_RATE * AUDIO_WINDOW_MS) / 1000;
#endif
static_assert(AUDIO_WINDOW_SAMPLES >= elex::kDoaWindow, "janela menor que a usada na direção");

// ── Credenciais (via load_env.py / platformio.ini) ───────────
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
#ifndef MQTT_USER
#  define MQTT_USER "device"
#endif
#ifndef MQTT_PASS
#  define MQTT_PASS ""
#endif
#ifndef DEVICE_ID
#  define DEVICE_ID "esp32s3-sound-01"
#endif

static const char TOPIC_INFERENCE[] = MQTT_TOPIC_INFERENCE "/" DEVICE_ID;
static const char TOPIC_STATUS[]    = MQTT_TOPIC_STATUS    "/" DEVICE_ID;
static const char TOPIC_CMD[]       = MQTT_TOPIC_CMD       "/" DEVICE_ID;

// ── Objetos ──────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);
static elex::Settings settings;

// Janela de áudio: 4 canais + mistura mono. Duas janelas (ping-pong): a captura
// continua enquanto a inferência processa a outra; se a inferência atrasa, a
// janela nova substitui a antiga em vez de bloquear o microfone.
struct AudioWindow {
    int16_t* ch[elex::kNumMics] = {nullptr, nullptr, nullptr, nullptr};
    int16_t* mono = nullptr;
};
static AudioWindow windows[2];
static volatile int writeWin  = 0;     // janela em preenchimento
static volatile int readyWin  = -1;    // janela completa aguardando inferência
static volatile bool inferBusy = false;
static volatile uint32_t droppedWindows = 0;

static int16_t* allocSamples(size_t n) {
    const size_t bytes = n * sizeof(int16_t);
    int16_t* p = static_cast<int16_t*>(psramFound() ? ps_malloc(bytes) : malloc(bytes));
    return p;
}

static bool allocWindows() {
    for (auto& w : windows) {
        for (auto& c : w.ch) {
            c = allocSamples(AUDIO_WINDOW_SAMPLES);
            if (!c) return false;
        }
        w.mono = allocSamples(AUDIO_WINDOW_SAMPLES);
        if (!w.mono) return false;
    }
    return true;
}

// ── I2S ──────────────────────────────────────────────────────
static constexpr size_t kBlockFrames = 256;

static void i2sInstall(i2s_port_t port, bool slave, int data_in) {
    i2s_config_t cfg = {};
    cfg.mode                 = static_cast<i2s_mode_t>((slave ? I2S_MODE_SLAVE : I2S_MODE_MASTER) | I2S_MODE_RX);
    cfg.sample_rate          = AUDIO_SAMPLE_RATE;
    cfg.bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT;
    cfg.channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT;
    cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    cfg.intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1;
    cfg.dma_buf_count        = 8;
    cfg.dma_buf_len          = kBlockFrames;
    cfg.use_apll             = false;
    cfg.tx_desc_auto_clear   = false;
    cfg.fixed_mclk           = 0;

    i2s_pin_config_t pins = {};
    pins.mck_io_num   = I2S_PIN_NO_CHANGE;
    pins.bck_io_num   = I2S_SCK_PIN;
    pins.ws_io_num    = I2S_WS_PIN;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num  = data_in;

    ESP_ERROR_CHECK(i2s_driver_install(port, &cfg, 0, nullptr));
    ESP_ERROR_CHECK(i2s_set_pin(port, &pins));
}

static void i2sInit() {
    i2sInstall(I2S_NUM_0, false, I2S_SD_PIN);
    i2sInstall(I2S_NUM_1, true, I2S1_SD_PIN);
    // O escravo configura BCLK/WS como entrada e cortaria a saída do mestre
    // no mesmo pino: devolve o modo entrada+saída.
    gpio_set_direction(static_cast<gpio_num_t>(I2S_SCK_PIN), GPIO_MODE_INPUT_OUTPUT);
    gpio_set_direction(static_cast<gpio_num_t>(I2S_WS_PIN), GPIO_MODE_INPUT_OUTPUT);
    i2s_zero_dma_buffer(I2S_NUM_0);
    i2s_zero_dma_buffer(I2S_NUM_1);
    Serial.println("[I2S] 4 microfones inicializados (I2S0 mestre + I2S1 escravo)");
}

// INMP441: 24 bits justificados à esquerda em 32; >>14 dá ganho de 4x em 16 bits, com saturação
static inline int16_t toSample16(int32_t raw) {
    int32_t v = raw >> 14;
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    return static_cast<int16_t>(v);
}

// Tarefa de captura: lê blocos das duas portas e enche a janela atual
static void captureTask(void*) {
    static int32_t b0[kBlockFrames * 2];
    static int32_t b1[kBlockFrames * 2];
    size_t idx = 0;
    for (;;) {
        size_t n0 = 0, n1 = 0;
        i2s_read(I2S_NUM_0, b0, sizeof(b0), &n0, pdMS_TO_TICKS(1000));
        i2s_read(I2S_NUM_1, b1, sizeof(b1), &n1, pdMS_TO_TICKS(1000));
        const size_t frames = min(n0, n1) / (2 * sizeof(int32_t));
        if (frames == 0) continue;  // microfone parado: o heartbeat segue no loop()

        AudioWindow& w = windows[writeWin];
        for (size_t f = 0; f < frames; f++) {
            const int16_t front = toSample16(b0[2 * f]);
            const int16_t back  = toSample16(b0[2 * f + 1]);
            const int16_t right = toSample16(b1[2 * f]);
            const int16_t left  = toSample16(b1[2 * f + 1]);
            w.ch[0][idx] = front;
            w.ch[1][idx] = right;
            w.ch[2][idx] = back;
            w.ch[3][idx] = left;
            w.mono[idx]  = static_cast<int16_t>((static_cast<int32_t>(front) + right + back + left) / 4);
            if (++idx >= AUDIO_WINDOW_SAMPLES) {
                idx = 0;
                if (!inferBusy && readyWin < 0) {
                    readyWin = writeWin;
                    writeWin = 1 - writeWin;
                } else {
                    droppedWindows = droppedWindows + 1;  // reaproveita a janela atual
                }
                break;  // o restante do bloco vai para a próxima janela no ciclo seguinte
            }
        }
    }
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

// ── Comandos MQTT ────────────────────────────────────────────
// Payload: {"key":"threshold","value":0.7}. Chave e faixa são validadas em settings_apply.
static void onMqttMessage(char* topic, byte* payload, unsigned int length) {
    if (strcmp(topic, TOPIC_CMD) != 0 || length == 0 || length > 128) return;
    JsonDocument doc;
    if (deserializeJson(doc, payload, length) != DeserializationError::Ok) {
        Serial.println("[CMD] JSON inválido, ignorado");
        return;
    }
    const char* key = doc["key"] | static_cast<const char*>(nullptr);
    if (key == nullptr || !doc["value"].is<float>()) {
        Serial.println("[CMD] sem key/value numérico, ignorado");
        return;
    }
    const float value = doc["value"].as<float>();
    if (elex::settings_apply(settings, key, value)) {
        Serial.printf("[CMD] %s = %.3f\n", key, value);
    } else {
        Serial.printf("[CMD] %s=%.3f recusado (chave ou faixa inválida)\n", key, value);
    }
}

// ── MQTT ─────────────────────────────────────────────────────
static void mqttReconnect() {
    for (uint8_t i = 0; i < 5 && !mqtt.connected(); i++) {
        Serial.printf("[MQTT] Conectando a %s:%d ...\n", MQTT_HOST, MQTT_PORT);
        if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS)) {
            Serial.println("[MQTT] Conectado.");
            mqtt.subscribe(TOPIC_CMD, 1);
        } else {
            Serial.printf("[MQTT] rc=%d — aguardando 2s\n", mqtt.state());
            delay(2000);
        }
    }
}

// ── Motores (PWM) ────────────────────────────────────────────
static const uint8_t kMotorPins[elex::kNumMics] = {MOTOR_PIN_FRONT, MOTOR_PIN_RIGHT, MOTOR_PIN_BACK, MOTOR_PIN_LEFT};
static uint32_t motorOffAtMs   = 0;
static uint32_t motorFreeAtMs  = 0;  // intervalo mínimo entre vibrações
static bool     motorActive    = false;

static void motorWrite(uint8_t m, uint8_t duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(kMotorPins[m], duty);
#else
    ledcWrite(m, duty);
#endif
}

static void motorsInit() {
    for (uint8_t m = 0; m < elex::kNumMics; m++) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
        ledcAttach(kMotorPins[m], 20000, 8);
#else
        ledcSetup(m, 20000, 8);
        ledcAttachPin(kMotorPins[m], m);
#endif
        motorWrite(m, 0);
    }
}

static void motorsOff() {
    for (uint8_t m = 0; m < elex::kNumMics; m++) motorWrite(m, 0);
    motorActive = false;
}

// Setor cardinal aciona o motor correspondente; diagonal aciona os dois vizinhos.
static void motorTrigger(uint8_t sector, uint8_t urgency) {
    const uint8_t duty = elex::motor_duty_for_urgency(urgency);
    const uint32_t now = millis();
    if (!settings.motor_enabled || duty == 0 || now < motorFreeAtMs) return;
    motorsOff();
    if (sector % 2 == 0) {
        motorWrite(sector / 2, duty);
    } else {
        motorWrite((sector - 1) / 2, duty);
        motorWrite(((sector + 1) / 2) % elex::kNumMics, duty);
    }
    motorActive  = true;
    motorOffAtMs = now + settings.motor_max_ms;
    motorFreeAtMs = motorOffAtMs + 300;  // evita vibração contínua
}

static void motorsTick() {
    if (motorActive && static_cast<int32_t>(millis() - motorOffAtMs) >= 0) motorsOff();
}

// ── Publicar resultado ────────────────────────────────────────
// mock=true marca leituras simuladas, para nunca se misturarem às reais no banco
static void publishInference(const char* label, float confidence, const elex::DoaResult* doa, bool mock = false) {
    JsonDocument doc;
    doc["label"]      = label;
    doc["confidence"] = confidence;
    doc["ts"]         = millis();
    doc["device"]     = DEVICE_ID;
    if (doa != nullptr && doa->valid) {
        doc["direction_deg"]  = static_cast<int>(doa->azimuth_deg + 0.5f) % 360;
        doc["sector"]         = elex::sector_name(doa->sector);
        doc["doa_confidence"] = doa->confidence;
    }
    if (mock) doc["mock"] = true;

    char payload[256];
    const size_t n = serializeJson(doc, payload, sizeof(payload));
    if (n == 0 || n >= sizeof(payload)) return;
    mqtt.publish(TOPIC_INFERENCE, payload, false);

    Serial.printf("[INF] %s  %.1f%%", label, confidence * 100.f);
    if (doa != nullptr && doa->valid) Serial.printf("  %s (%.0f°)", elex::sector_name(doa->sector), doa->azimuth_deg);
    Serial.println();
}

static void publishStatus() {
    JsonDocument doc;
    doc["uptime_s"]      = millis() / 1000;
    doc["heap"]          = ESP.getFreeHeap();
    doc["rssi"]          = WiFi.RSSI();
    doc["device"]        = DEVICE_ID;
    doc["dropped"]       = droppedWindows;
    doc["threshold"]     = settings.threshold;
    doc["doa_enabled"]   = settings.doa_enabled;
    doc["motor_enabled"] = settings.motor_enabled;
    doc["port1_skew"]    = settings.port1_skew;

    char payload[320];
    const size_t n = serializeJson(doc, payload, sizeof(payload));
    if (n == 0 || n >= sizeof(payload)) return;
    mqtt.publish(TOPIC_STATUS, payload, true);
}

// ── Direção e resposta háptica de uma detecção ───────────────
static void handleDetection(const AudioWindow& w, const char* label, float confidence, bool mock) {
    if (confidence < settings.threshold) return;
    const uint8_t urgency = elex::urgency_for_label(label);

    elex::DoaResult doa;
    if (!mock && settings.doa_enabled && urgency > 0) {
        const size_t start = elex::doa_loudest_window(w.mono, AUDIO_WINDOW_SAMPLES);
        const int16_t* mics[elex::kNumMics] = {w.ch[0] + start, w.ch[1] + start, w.ch[2] + start, w.ch[3] + start};
        elex::DoaConfig cfg;
        cfg.sample_rate = AUDIO_SAMPLE_RATE;
        cfg.radius_m = MIC_RADIUS_M;
        cfg.port1_skew_samples = settings.port1_skew;
        doa = elex::doa_estimate(mics, cfg);
        if (doa.valid) motorTrigger(doa.sector, urgency);
    }
    publishInference(label, confidence, &doa, mock);
}

// ── Inferência Edge Impulse ───────────────────────────────────
#ifdef ELEX_HAS_EI_MODEL
static const int16_t* eiBuffer = nullptr;

static int eiGetData(size_t offset, size_t length, float* out) {
    for (size_t i = 0; i < length; i++) out[i] = static_cast<float>(eiBuffer[offset + i]) / 32768.f;
    return 0;
}

static void runInference(const AudioWindow& w) {
    eiBuffer = w.mono;
    signal_t signal;
    signal.total_length = AUDIO_WINDOW_SAMPLES;
    signal.get_data     = &eiGetData;

    ei_impulse_result_t result = {};
    const EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    if (err != EI_IMPULSE_OK) {
        Serial.printf("[EI] Erro: %d\n", err);
        return;
    }
    size_t best = 0;
    for (size_t i = 1; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        if (result.classification[i].value > result.classification[best].value) best = i;
    }
    handleDetection(w, result.classification[best].label, result.classification[best].value, false);
}
#elif defined(ELEX_MOCK_INFERENCE)
// Simulador — só compilado com -DELEX_MOCK_INFERENCE (env esp32s3_debug).
// Não vai para o firmware de produção: publicaria rótulos aleatórios no banco.
static void runInference(const AudioWindow& w) {
    static const char* sounds[] = {"siren", "car_horn", "dog_bark", "drilling", "street_music", "air_conditioner"};
    static uint8_t idx = 0;
    const float conf = 0.75f + (random(0, 25) / 100.f);
    handleDetection(w, sounds[idx++ % 6], conf, true);
}
#else
static void runInference(const AudioWindow&) {
    static bool warned = false;
    if (!warned) {
        Serial.println("[EI] Sem modelo em lib/ei-model/: janelas descartadas (use esp32s3_debug para o mock)");
        warned = true;
    }
}
#endif

// ── Setup ─────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[ELEX20] Boot — percepção sonora háptica");

    if (!allocWindows()) {
        Serial.println("[MEM] ERRO: sem memória para os buffers de áudio!");
        ESP.restart();
    }
    Serial.printf("[MEM] 2 janelas de %u amostras x 5 canais (%s)\n",
                  static_cast<unsigned>(AUDIO_WINDOW_SAMPLES), psramFound() ? "PSRAM" : "heap");

    motorsInit();
    i2sInit();
    xTaskCreatePinnedToCore(captureTask, "capture", 6144, nullptr, 5, nullptr, 0);
    connectWiFi();

    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setBufferSize(512);
    mqtt.setKeepAlive(30);
    mqtt.setCallback(onMqttMessage);
    mqttReconnect();
}

// ── Loop ──────────────────────────────────────────────────────
static uint32_t lastStatusMs = 0;

void loop() {
    if (WiFi.status() != WL_CONNECTED) connectWiFi();
    if (!mqtt.connected())             mqttReconnect();
    mqtt.loop();
    motorsTick();

    // Janela completa: classifica, estima direção e publica
    const int ready = readyWin;
    if (ready >= 0) {
        inferBusy = true;
        runInference(windows[ready]);
        readyWin  = -1;
        inferBusy = false;
    }

    // Heartbeat a cada 5 s
    if (millis() - lastStatusMs >= 5000UL) {
        lastStatusMs = millis();
        publishStatus();
    }
}
