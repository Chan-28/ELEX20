/**
 * ELEX20 — ESP32-S3 · Percepção sonora háptica
 *
 * Fluxo:
 *   4 microfones INMP441 (I2S0 mestre + I2S1 escravo, clock compartilhado)
 *   → mistura mono 16 kHz → Edge Impulse (YAMNet) → classe + confiança
 *   → direção por GCC-PHAT (8 setores) quando há som de alerta
 *   → motor do setor + JSON MQTT → Mosquitto → n8n → TimescaleDB
 *
 * Tarefas (a rede nunca bloqueia captura, inferência nem motor):
 *   capture  (núcleo 0, prio 5)  lê os microfones e enche as janelas
 *   loop()   (núcleo 1, prio 1)  classifica, estima a direção e pede a vibração
 *   motor    (núcleo 1, prio 4)  liga e desliga os motores; preempta a inferência
 *   net      (núcleo 0, prio 1)  Wi-Fi, MQTT, comandos, publicação e heartbeat
 *
 * Sem rede, o sensor segue vibrando. As detecções feitas nesse período são
 * descartadas, não guardadas: o banco data cada evento pela chegada, então um
 * reenvio tardio ficaria com a hora errada. O total sai em "offline_dropped".
 * Só escapa o que ainda está na fila (poucas detecções recentes) quando a conexão volta.
 * Comandos enviados sem o sensor conectado se perdem (sessão limpa, sem retain).
 *
 * Tópicos (Mosquitto local):
 *   sound/inference/<DEVICE_ID>  {"label","confidence","ts","device",
 *                                  "direction_deg","sector","doa_confidence"[,"mock"]}
 *   sound/status/<DEVICE_ID>     {"uptime_s","heap","rssi","device","dropped",
 *                                  "offline_dropped",+ ajustes atuais,
 *                                  + desempenho: "win_ms_avg","win_ms_max","dsp_ms",
 *                                  "nn_ms","heap_min","psram_free","stack_min",
 *                                  "stack_task","wifi_connects","mqtt_connects","temp_c"}
 *     Tempos em ms, média e máximo dos últimos 5 s; ausentes se nada foi medido.
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
#include <atomic>
#include <driver/gpio.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <freertos/queue.h>

#include "backoff.h"
#include "doa.h"
#include "motor_timer.h"
#include "perf_stats.h"
#include "settings.h"

#ifndef ESP_ARDUINO_VERSION_MAJOR
#  define ESP_ARDUINO_VERSION_MAJOR 2
#endif

// O LDF do PlatformIO lê o texto dos includes, não expande EI_MODEL_HEADER nem avalia #if.
// Sem esta linha, esp32s3_model compila com sucesso, mas sem o modelo.
#if 0
#  include <ELEX20_Categorias_inferencing.h>
#endif
#if defined(EI_MODEL_HEADER) && __has_include(EI_MODEL_HEADER)
#  include EI_MODEL_HEADER
#  define ELEX_HAS_EI_MODEL 1
#endif

// ── Pinos (configuráveis em platformio.ini) ──────────────────
#ifndef I2S_WS_PIN
#  define I2S_WS_PIN  5
#endif
#ifndef I2S_SCK_PIN
#  define I2S_SCK_PIN 4
#endif
#ifndef I2S_SD_PIN
#  define I2S_SD_PIN  6   // I2S0: frente + trás
#endif
#ifndef I2S1_SD_PIN
#  define I2S1_SD_PIN 7   // I2S1: direita + esquerda
#endif
// Motores de vibração (MOSFET por PWM): frente, direita, trás, esquerda.
// Evite GPIO 26-37 (flash/PSRAM octal).
#ifndef MOTOR_PIN_FRONT
#  define MOTOR_PIN_FRONT 18
#endif
#ifndef MOTOR_PIN_RIGHT
#  define MOTOR_PIN_RIGHT 17
#endif
#ifndef MOTOR_PIN_BACK
#  define MOTOR_PIN_BACK  16
#endif
#ifndef MOTOR_PIN_LEFT
#  define MOTOR_PIN_LEFT  15
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

// A tarefa de rede é a única que escreve em settings (comandos MQTT). As demais
// leem uma cópia com settingsSnapshot(): os campos mudam juntos sob a trava.
static elex::Settings settings;
static portMUX_TYPE settingsLock = portMUX_INITIALIZER_UNLOCKED;

static elex::Settings settingsSnapshot() {
    portENTER_CRITICAL(&settingsLock);
    const elex::Settings copy = settings;
    portEXIT_CRITICAL(&settingsLock);
    return copy;
}

// Detecção a publicar: vai do laço principal à tarefa de rede por uma fila curta
struct Detection {
    char label[32];
    float confidence;
    uint32_t ts;
    elex::DoaResult doa;
    bool mock;
};
static constexpr size_t kDetectionQueueLen = 8;
static QueueHandle_t detectionQueue = nullptr;
static std::atomic<uint32_t> offlineDropped{0};  // detecções sem rede ou com a fila cheia

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

// ── Desempenho (vai no status a cada 5 s) ────────────────────
// Medido no loop() (núcleo 1) e lido pela tarefa de rede (núcleo 0): sempre sob perfLock.
static portMUX_TYPE perfLock = portMUX_INITIALIZER_UNLOCKED;
static elex::PerfStats windowStats;  // janela inteira: inferência + direção + fila
static elex::PerfStats dspStats;     // extração de features do Edge Impulse
static elex::PerfStats nnStats;      // classificação do Edge Impulse

static void perfAdd(elex::PerfStats& s, float ms) {
    portENTER_CRITICAL(&perfLock);
    s.add(ms);
    portEXIT_CRITICAL(&perfLock);
}

static elex::PerfWindow perfTake(elex::PerfStats& s) {
    portENTER_CRITICAL(&perfLock);
    const elex::PerfWindow w = s.take();
    portEXIT_CRITICAL(&perfLock);
    return w;
}

// Tarefas cuja folga de pilha vai no status (o loop() registra a própria ao rodar)
static TaskHandle_t netTaskHandle = nullptr;
static TaskHandle_t motorTaskHandle = nullptr;
static TaskHandle_t captureTaskHandle = nullptr;
static TaskHandle_t loopTaskHandle = nullptr;

// Reconexões desde o boot; só a tarefa de rede escreve e lê
static uint32_t wifiConnects = 0;
static uint32_t mqttConnects = 0;

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
        if (frames == 0) continue;  // microfone parado: a tarefa de rede segue com o heartbeat

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
    // Só esta tarefa escreve em settings: lê sem trava e troca tudo de uma vez
    elex::Settings next = settings;
    if (elex::settings_apply(next, key, value)) {
        portENTER_CRITICAL(&settingsLock);
        settings = next;
        portEXIT_CRITICAL(&settingsLock);
        Serial.printf("[CMD] %s = %.3f\n", key, value);
    } else {
        Serial.printf("[CMD] %s=%.3f recusado (chave ou faixa inválida)\n", key, value);
    }
}

// ── Motores (PWM) ────────────────────────────────────────────
static const uint8_t kMotorPins[elex::kNumMics] = {MOTOR_PIN_FRONT, MOTOR_PIN_RIGHT, MOTOR_PIN_BACK, MOTOR_PIN_LEFT};

// Pedido de vibração. Só a tarefa do motor toca nos motores e no temporizador.
struct MotorRequest {
    uint8_t sector;
    uint8_t duty;
    uint16_t duration_ms;
};
static QueueHandle_t motorQueue = nullptr;  // uma posição: vale o pedido mais recente
static elex::MotorTimer motorTimer;

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
}

// Setor cardinal aciona o motor correspondente; diagonal aciona os dois vizinhos.
static void motorsOn(const MotorRequest& req) {
    if (!motorTimer.start(millis(), req.duration_ms)) return;  // vibrando ou em descanso
    motorsOff();
    if (req.sector % 2 == 0) {
        motorWrite(req.sector / 2, req.duty);
    } else {
        motorWrite((req.sector - 1) / 2, req.duty);
        motorWrite(((req.sector + 1) / 2) % elex::kNumMics, req.duty);
    }
}

static void motorsTick() {
    if (motorTimer.expired(millis())) motorsOff();
}

// Chamado pelo laço principal: só pede a vibração, nunca espera
static void motorTrigger(uint8_t sector, uint8_t urgency, const elex::Settings& cfg) {
    const uint8_t duty = elex::motor_duty_for_urgency(urgency);
    if (!cfg.motor_enabled || duty == 0) return;
    const MotorRequest req = {sector, duty, cfg.motor_max_ms};
    xQueueOverwrite(motorQueue, &req);
}

// Dorme até o próximo pedido ou até a hora de desligar. Roda acima do laço principal
// para o desligamento não esperar a inferência, que pode durar mais que a vibração.
static void motorTask(void*) {
    for (;;) {
        const TickType_t wait = motorTimer.active()
                                    ? pdMS_TO_TICKS(motorTimer.remaining_ms(millis()))
                                    : portMAX_DELAY;
        MotorRequest req;
        if (xQueueReceive(motorQueue, &req, wait) == pdTRUE) motorsOn(req);
        motorsTick();
    }
}

// ── Publicar resultado ────────────────────────────────────────
// mock=true marca leituras simuladas, para nunca se misturarem às reais no banco
static bool publishInference(const Detection& d) {
    JsonDocument doc;
    doc["label"]      = d.label;
    doc["confidence"] = d.confidence;
    doc["ts"]         = d.ts;
    doc["device"]     = DEVICE_ID;
    if (d.doa.valid) {
        doc["direction_deg"]  = static_cast<int>(d.doa.azimuth_deg + 0.5f) % 360;
        doc["sector"]         = elex::sector_name(d.doa.sector);
        doc["doa_confidence"] = d.doa.confidence;
    }
    if (d.mock) doc["mock"] = true;

    char payload[256];
    const size_t n = serializeJson(doc, payload, sizeof(payload));
    if (n == 0 || n >= sizeof(payload)) return false;
    return mqtt.publish(TOPIC_INFERENCE, payload, false);
}

// Menor folga de pilha, em bytes, entre as tarefas (no ESP-IDF a função já devolve bytes)
static uint32_t minStackFree(const char** name) {
    const struct {
        TaskHandle_t h;
        const char* name;
    } tasks[] = {{netTaskHandle, "net"}, {motorTaskHandle, "motor"}, {captureTaskHandle, "capture"},
                 {loopTaskHandle, "loop"}};
    uint32_t best = UINT32_MAX;
    *name = "";
    for (const auto& t : tasks) {
        if (t.h == nullptr) continue;
        const uint32_t free = uxTaskGetStackHighWaterMark(t.h);
        if (free < best) {
            best = free;
            *name = t.name;
        }
    }
    return best == UINT32_MAX ? 0 : best;
}

static void putPerf(JsonDocument& doc, const char* avgKey, const char* maxKey, elex::PerfStats& s) {
    const elex::PerfWindow w = perfTake(s);
    if (w.count == 0) return;  // sem medição no período: o campo fica de fora (NULL no banco)
    doc[avgKey] = elex::round1(w.avg_ms);
    if (maxKey) doc[maxKey] = elex::round1(w.max_ms);
}

static void publishStatus() {
    JsonDocument doc;
    doc["uptime_s"]        = millis() / 1000;
    doc["heap"]            = ESP.getFreeHeap();
    doc["rssi"]            = WiFi.RSSI();
    doc["device"]          = DEVICE_ID;
    doc["dropped"]         = droppedWindows;
    doc["offline_dropped"] = offlineDropped.load();
    doc["threshold"]       = settings.threshold;
    doc["doa_enabled"]     = settings.doa_enabled;
    doc["motor_enabled"]   = settings.motor_enabled;
    doc["port1_skew"]      = settings.port1_skew;

    // Desempenho: tempos do período, memória, pilha, rede e temperatura
    putPerf(doc, "win_ms_avg", "win_ms_max", windowStats);
    putPerf(doc, "dsp_ms", nullptr, dspStats);
    putPerf(doc, "nn_ms", nullptr, nnStats);
    doc["heap_min"]   = esp_get_minimum_free_heap_size();
    doc["psram_free"] = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    const char* stackTask = "";
    doc["stack_min"]      = minStackFree(&stackTask);
    doc["stack_task"]     = stackTask;
    doc["wifi_connects"]  = wifiConnects;
    doc["mqtt_connects"]  = mqttConnects;
    doc["temp_c"]         = elex::round1(temperatureRead());

    char payload[640];
    const size_t n = serializeJson(doc, payload, sizeof(payload));
    if (n == 0 || n >= sizeof(payload)) return;
    // Sem retain: o broker reentregaria o último status a cada nova assinatura do n8n,
    // que o gravaria com a hora atual, como heartbeat de um sensor talvez desligado
    mqtt.publish(TOPIC_STATUS, payload, false);
}

// ── Rede ─────────────────────────────────────────────────────
// Roda inteira na tarefa de rede: mqtt.connect() e a resolução de nomes bloqueiam
// por segundos, mas aqui isso só atrasa a própria rede. Nunca reinicia a placa.
static constexpr uint32_t kNetTickMs        = 50;
static constexpr uint32_t kStatusPeriodMs   = 5000;
static constexpr uint8_t  kMqttSocketTimeoutS = 5;  // limita a espera pelo CONNACK

// O mínimo do Wi-Fi é o tempo de uma associação: WiFi.begin() não espera por ela
static elex::Backoff wifiBackoff(15000, 120000);
static elex::Backoff mqttBackoff(2000, 60000);

static bool wifiService() {
    static bool wasUp = false;
    const bool up = WiFi.status() == WL_CONNECTED;
    if (up && !wasUp) {
        Serial.printf("[WiFi] IP: %s  RSSI: %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
        wifiConnects++;
        wifiBackoff.connected();
        mqttBackoff.connected();  // o broker pode ter ficado inalcançável só pelo Wi-Fi
    } else if (!up && wasUp) {
        Serial.println("[WiFi] Conexão perdida; o sensor segue sem rede");
        mqtt.disconnect();  // solta o socket antigo antes da próxima conexão
    }
    wasUp = up;
    if (up) return true;

    const uint32_t now = millis();
    if (wifiBackoff.due(now)) {
        wifiBackoff.attempted(now);
        Serial.printf("[WiFi] Conectando a %s (próxima em %lu s)\n", WIFI_SSID,
                      static_cast<unsigned long>(wifiBackoff.wait_ms() / 1000));
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
    return false;
}

static bool mqttService() {
    if (mqtt.connected()) return true;
    if (!mqttBackoff.due(millis())) return false;

    Serial.printf("[MQTT] Conectando a %s:%d ...\n", MQTT_HOST, MQTT_PORT);
    bool up = mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS);
    if (up) {
        // A sessão é limpa: sem assinar de novo, os comandos parariam de chegar
        up = mqtt.subscribe(TOPIC_CMD, 1);
        if (!up) mqtt.disconnect();
    }
    // Apaga o status retido por firmwares antigos (payload vazio com retain); o n8n descarta o vazio
    if (up) mqtt.publish(TOPIC_STATUS, "", true);
    mqttBackoff.attempted(millis());  // conta do fim: a tentativa pode levar segundos
    if (up) {
        Serial.println("[MQTT] Conectado.");
        mqttConnects++;
        mqttBackoff.connected();
    } else {
        Serial.printf("[MQTT] rc=%d — próxima em %lu s\n", mqtt.state(),
                      static_cast<unsigned long>(mqttBackoff.wait_ms() / 1000));
    }
    return up;
}

static void netTask(void*) {
    WiFi.persistent(false);         // credenciais vêm do build; não grava a flash a cada tentativa
    WiFi.setAutoReconnect(false);   // quem reconecta é wifiBackoff, com recuo
    WiFi.mode(WIFI_STA);
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setBufferSize(768);  // o status com as métricas passa de 400 bytes
    mqtt.setKeepAlive(30);
    mqtt.setSocketTimeout(kMqttSocketTimeoutS);
    mqtt.setCallback(onMqttMessage);

    uint32_t lastStatusMs = 0;
    for (;;) {
        const bool online = wifiService() && mqttService() && mqtt.loop();

        // A fila dá o ritmo da tarefa: acorda na hora quando chega uma detecção
        Detection d;
        if (xQueueReceive(detectionQueue, &d, pdMS_TO_TICKS(kNetTickMs)) == pdTRUE) {
            if (!online || !publishInference(d)) offlineDropped.fetch_add(1);
        }

        if (online && millis() - lastStatusMs >= kStatusPeriodMs) {
            lastStatusMs = millis();
            publishStatus();
        }
    }
}

// ── Direção e resposta háptica de uma detecção ───────────────
static void handleDetection(const AudioWindow& w, const char* modelLabel, float confidence, bool mock) {
    const elex::Settings cfg = settingsSnapshot();
    if (confidence < cfg.threshold) return;
    const char* label = elex::canonical_label(modelLabel);
    const uint8_t urgency = elex::urgency_for_label(label);

    Detection d = {};
    strlcpy(d.label, label, sizeof(d.label));
    d.confidence = confidence;
    d.ts = millis();
    d.mock = mock;
    if (!mock && cfg.doa_enabled && urgency > 0) {
        const size_t start = elex::doa_loudest_window(w.mono, AUDIO_WINDOW_SAMPLES);
        const int16_t* mics[elex::kNumMics] = {w.ch[0] + start, w.ch[1] + start, w.ch[2] + start, w.ch[3] + start};
        elex::DoaConfig doaCfg;
        doaCfg.sample_rate = AUDIO_SAMPLE_RATE;
        doaCfg.radius_m = MIC_RADIUS_M;
        doaCfg.port1_skew_samples = cfg.port1_skew;
        d.doa = elex::doa_estimate(mics, doaCfg);
        if (d.doa.valid) motorTrigger(d.doa.sector, urgency, cfg);
    }

    Serial.printf("[INF] %s  %.1f%%", label, confidence * 100.f);
    if (d.doa.valid) Serial.printf("  %s (%.0f°)", elex::sector_name(d.doa.sector), d.doa.azimuth_deg);
    Serial.println();

    // A tarefa de rede publica ou, sem conexão, descarta. Nunca espera aqui.
    if (xQueueSend(detectionQueue, &d, 0) != pdTRUE) offlineDropped.fetch_add(1);
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
    perfAdd(dspStats, static_cast<float>(result.timing.dsp));
    perfAdd(nnStats, static_cast<float>(result.timing.classification));
    handleDetection(w, result.classification[best].label, result.classification[best].value, false);
}
#elif defined(ELEX_MOCK_INFERENCE)
// Simulador — só compilado com -DELEX_MOCK_INFERENCE (env esp32s3_debug).
// Não vai para o firmware de produção: publicaria rótulos aleatórios no banco.
static void runInference(const AudioWindow& w) {
    static const char* sounds[] = {"siren", "horn", "impact", "power_tool", "music", "weather"};
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

    detectionQueue = xQueueCreate(kDetectionQueueLen, sizeof(Detection));
    motorQueue     = xQueueCreate(1, sizeof(MotorRequest));
    if (detectionQueue == nullptr || motorQueue == nullptr) {
        Serial.println("[MEM] ERRO: sem memória para as filas!");
        ESP.restart();
    }

    motorsInit();
    i2sInit();
    xTaskCreatePinnedToCore(motorTask, "motor", 4096, nullptr, 4, &motorTaskHandle, 1);
    xTaskCreatePinnedToCore(captureTask, "capture", 6144, nullptr, 5, &captureTaskHandle, 0);
    xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 1, &netTaskHandle, 0);
}

// ── Loop ──────────────────────────────────────────────────────
// Só áudio: rede e motores têm tarefas próprias
void loop() {
    if (loopTaskHandle == nullptr) loopTaskHandle = xTaskGetCurrentTaskHandle();
    const int ready = readyWin;
    if (ready < 0) {
        delay(1);  // sem janela pronta, libera o núcleo
        return;
    }

    // Janela completa: classifica, estima a direção e pede a vibração
    inferBusy = true;
    const int64_t t0 = esp_timer_get_time();
    runInference(windows[ready]);
    perfAdd(windowStats, static_cast<float>(esp_timer_get_time() - t0) / 1000.f);
    readyWin  = -1;
    inferBusy = false;
}
