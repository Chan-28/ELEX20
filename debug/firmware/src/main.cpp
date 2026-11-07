/*
 * ELEX20 — firmware de bancada (debug/firmware)
 *
 * Captura os 4 microfones como o firmware principal (mesmos pinos, formato e
 * conversão de 32 para 16 bits) e, pela serial:
 *   - a cada 1 s, uma linha JSON com a qualidade de cada canal;
 *   - com "rec 4" ou "rec 1", transmite o áudio em quadros binários (4 canais ou
 *     a mistura mono que vai para o modelo) até "stop";
 *   - com "motor <0-3> <0-255> <ms>" ou "motors", aciona os motores.
 *
 * Quadro binário: "ELXA", canais (u8), 0 (u8), quadros (u16 LE), amostras int16 LE
 * intercaladas, soma de verificação (u16 LE, soma dos bytes das amostras).
 * Durante a gravação as linhas de relatório param, para não misturar texto ao áudio.
 */

#include <Arduino.h>
#include <driver/gpio.h>
#include <driver/i2s.h>
#include <freertos/semphr.h>
#include <freertos/stream_buffer.h>

#include "mic_stats.h"

#ifndef DEBUG_BAUD
#  define DEBUG_BAUD 2000000
#endif

static constexpr int kNumMics = 4;
static const char* const kChannelNames[kNumMics] = {"front", "right", "back", "left"};
static const uint8_t kMotorPins[kNumMics] = {MOTOR_PIN_FRONT, MOTOR_PIN_RIGHT, MOTOR_PIN_BACK, MOTOR_PIN_LEFT};
static constexpr size_t kBlockFrames = 256;

// ── Estado compartilhado entre a captura (núcleo 0) e o loop() (núcleo 1) ──
// Mutex e não spinlock: a estatística de um bloco leva ~100 µs, tempo demais com interrupções desligadas
static SemaphoreHandle_t statsLock = nullptr;
static elex::MicStats stats[kNumMics] = {elex::MicStats(AUDIO_SAMPLE_RATE), elex::MicStats(AUDIO_SAMPLE_RATE),
                                         elex::MicStats(AUDIO_SAMPLE_RATE), elex::MicStats(AUDIO_SAMPLE_RATE)};
static volatile uint32_t shortReads = 0;      // leituras em que as duas portas vieram desiguais
static volatile uint32_t streamOverflow = 0;  // quadros perdidos porque a serial não deu conta
static volatile uint8_t recChannels = 0;      // 0 = sem gravação; 1 = mono; 4 = canais
static StreamBufferHandle_t audioStream = nullptr;

// ── I2S (igual a firmware/src/main.cpp) ─────────────────────
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
    gpio_set_direction(static_cast<gpio_num_t>(I2S_SCK_PIN), GPIO_MODE_INPUT_OUTPUT);
    gpio_set_direction(static_cast<gpio_num_t>(I2S_WS_PIN), GPIO_MODE_INPUT_OUTPUT);
    i2s_zero_dma_buffer(I2S_NUM_0);
    i2s_zero_dma_buffer(I2S_NUM_1);
}

static inline int16_t toSample16(int32_t raw) {
    int32_t v = raw >> 14;
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    return static_cast<int16_t>(v);
}

// ── Captura: estatística sempre; áudio para a serial só durante a gravação ──
static void captureTask(void*) {
    static int32_t b0[kBlockFrames * 2];
    static int32_t b1[kBlockFrames * 2];
    static int16_t ch[kNumMics][kBlockFrames];
    static int16_t out[kBlockFrames * kNumMics];
    for (;;) {
        size_t n0 = 0, n1 = 0;
        i2s_read(I2S_NUM_0, b0, sizeof(b0), &n0, pdMS_TO_TICKS(1000));
        i2s_read(I2S_NUM_1, b1, sizeof(b1), &n1, pdMS_TO_TICKS(1000));
        if (n0 != n1) shortReads = shortReads + 1;
        const size_t frames = min(n0, n1) / (2 * sizeof(int32_t));
        if (frames == 0) continue;

        for (size_t f = 0; f < frames; f++) {
            ch[0][f] = toSample16(b0[2 * f]);      // frente
            ch[2][f] = toSample16(b0[2 * f + 1]);  // trás
            ch[1][f] = toSample16(b1[2 * f]);      // direita
            ch[3][f] = toSample16(b1[2 * f + 1]);  // esquerda
        }
        xSemaphoreTake(statsLock, portMAX_DELAY);
        for (int c = 0; c < kNumMics; c++) stats[c].add(ch[c], frames);
        xSemaphoreGive(statsLock);

        const uint8_t rec = recChannels;
        if (rec == 0) continue;
        size_t n = 0;
        for (size_t f = 0; f < frames; f++) {
            if (rec == 1) {
                out[n++] = static_cast<int16_t>((static_cast<int32_t>(ch[0][f]) + ch[1][f] + ch[2][f] + ch[3][f]) / 4);
            } else {
                for (int c = 0; c < kNumMics; c++) out[n++] = ch[c][f];
            }
        }
        const size_t bytes = n * sizeof(int16_t);
        if (xStreamBufferSpacesAvailable(audioStream) < bytes) {
            streamOverflow = streamOverflow + 1;  // a serial atrasou: perde o bloco inteiro
        } else {
            xStreamBufferSend(audioStream, out, bytes, 0);
        }
    }
}

// ── Saída ────────────────────────────────────────────────────
static void sendFrame(uint8_t channels, const int16_t* samples, uint16_t frames) {
    const uint8_t header[8] = {'E', 'L', 'X', 'A', channels, 0, static_cast<uint8_t>(frames & 0xFF),
                               static_cast<uint8_t>(frames >> 8)};
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(samples);
    const size_t len = static_cast<size_t>(frames) * channels * sizeof(int16_t);
    uint16_t sum = 0;
    for (size_t i = 0; i < len; i++) sum = static_cast<uint16_t>(sum + bytes[i]);
    Serial.write(header, sizeof(header));
    Serial.write(bytes, len);
    const uint8_t tail[2] = {static_cast<uint8_t>(sum & 0xFF), static_cast<uint8_t>(sum >> 8)};
    Serial.write(tail, sizeof(tail));
}

static void printReport() {
    elex::MicReport r[kNumMics];
    xSemaphoreTake(statsLock, portMAX_DELAY);
    for (int c = 0; c < kNumMics; c++) r[c] = stats[c].take();
    xSemaphoreGive(statsLock);
    Serial.print("{\"t\":\"mic\",\"short_reads\":");
    Serial.print(shortReads);
    Serial.print(",\"ch\":[");
    for (int c = 0; c < kNumMics; c++) {
        Serial.printf("%s{\"name\":\"%s\",\"n\":%lu,\"dc\":%.1f,\"rms\":%.1f,\"peak\":%.1f,\"clip\":%.3f,\"zero\":%.1f,"
                      "\"hum\":%.1f}",
                      c ? "," : "", kChannelNames[c], static_cast<unsigned long>(r[c].samples), r[c].dc, r[c].rms_dbfs,
                      r[c].peak_dbfs, r[c].clip_pct, r[c].zero_pct, r[c].hum_db);
    }
    Serial.println("]}");
}

// ── Motores ──────────────────────────────────────────────────
static void motorWrite(uint8_t m, uint8_t duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWrite(kMotorPins[m], duty);
#else
    ledcWrite(m, duty);
#endif
}

static void motorsInit() {
    for (uint8_t m = 0; m < kNumMics; m++) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
        ledcAttach(kMotorPins[m], 20000, 8);
#else
        ledcSetup(m, 20000, 8);
        ledcAttachPin(kMotorPins[m], m);
#endif
        motorWrite(m, 0);
    }
}

// Bloqueia o loop() pelo tempo pedido: só para bancada, nunca com gravação ativa
static void pulse(uint8_t m, uint8_t duty, uint16_t ms) {
    Serial.printf("# motor %s duty=%u por %u ms\n", kChannelNames[m], duty, ms);
    motorWrite(m, duty);
    delay(ms);
    motorWrite(m, 0);
}

// ── Comandos ─────────────────────────────────────────────────
static void handleCommand(char* line) {
    unsigned a = 0, b = 0, c = 0;
    if (strcmp(line, "rec 4") == 0 || strcmp(line, "rec 1") == 0) {
        xStreamBufferReset(audioStream);
        streamOverflow = 0;
        Serial.printf("# rec %c\n", line[4]);
        Serial.flush();
        recChannels = static_cast<uint8_t>(line[4] - '0');
    } else if (strcmp(line, "stop") == 0) {
        recChannels = 0;
        Serial.printf("\n# stop overflow=%lu\n", static_cast<unsigned long>(streamOverflow));
    } else if (recChannels != 0) {
        return;  // durante a gravação só "stop" vale: texto quebraria o áudio
    } else if (sscanf(line, "motor %u %u %u", &a, &b, &c) == 3 && a < kNumMics && b <= 255 && c <= 3000) {
        pulse(a, b, c);
    } else if (strcmp(line, "motors") == 0) {
        for (uint8_t m = 0; m < kNumMics; m++) {
            pulse(m, 180, 400);
            delay(300);
        }
    } else {
        Serial.println("# comandos: rec 4 | rec 1 | stop | motor <0-3> <0-255> <ms> | motors");
    }
}

static void readCommands() {
    static char line[48];
    static size_t len = 0;
    while (Serial.available()) {
        const int ch = Serial.read();
        if (ch == '\n' || ch == '\r') {
            if (len == 0) continue;
            line[len] = '\0';
            len = 0;
            handleCommand(line);
        } else if (len < sizeof(line) - 1) {
            line[len++] = static_cast<char>(ch);
        }
    }
}

void setup() {
    Serial.setTxBufferSize(16384);
    Serial.begin(DEBUG_BAUD);
    delay(300);
    audioStream = xStreamBufferCreate(48 * 1024, 1);
    statsLock = xSemaphoreCreateMutex();
    if (audioStream == nullptr || statsLock == nullptr) {
        Serial.println("# ERRO: sem memória para o buffer de áudio");
        for (;;) delay(1000);
    }
    motorsInit();
    i2sInit();
    xTaskCreatePinnedToCore(captureTask, "capture", 6144, nullptr, 5, nullptr, 0);
    Serial.println("# ELEX20 bancada: canais front,right,back,left | 'help' para os comandos");
}

void loop() {
    readCommands();
    const uint8_t rec = recChannels;
    if (rec != 0) {
        static int16_t buf[kBlockFrames * kNumMics];
        const size_t got = xStreamBufferReceive(audioStream, buf, sizeof(buf), pdMS_TO_TICKS(20));
        const uint16_t frames = static_cast<uint16_t>(got / sizeof(int16_t) / rec);
        if (frames > 0) sendFrame(rec, buf, frames);
        return;
    }
    static uint32_t last = 0;
    if (millis() - last >= 1000) {
        last = millis();
        printReport();
    }
    delay(5);
}
