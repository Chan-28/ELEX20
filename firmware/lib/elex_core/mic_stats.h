// Estatística de um canal de microfone num período, sem dependência de hardware.
// Usada pelo firmware de debug (debug/firmware) para o teste de qualidade dos microfones.
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace elex {

struct MicReport {
    uint32_t samples = 0;
    float dc = 0.f;            // média (offset DC), em unidades de amostra
    float rms_dbfs = -120.f;   // RMS sem o DC, em dB relativos ao fundo de escala
    float peak_dbfs = -120.f;  // maior |amostra|, em dBFS
    float clip_pct = 0.f;      // % de amostras no limite (saturadas)
    float zero_pct = 0.f;      // % de amostras exatamente 0 (canal morto)
    float hum_db = -120.f;     // energia em 50/60 Hz e harmônicos, relativa ao RMS (dB)
};

class MicStats {
public:
    explicit MicStats(uint32_t sample_rate = 16000);

    void add(const int16_t* x, size_t n);

    // Fecha o período e zera os acumuladores.
    MicReport take();

private:
    // Zumbido: Goertzel em 50, 60, 100, 120, 150 e 180 Hz (rede elétrica e harmônicos).
    // Em blocos de 100 ms (número inteiro de ciclos de cada frequência) e em float: o
    // ESP32-S3 só tem FPU de precisão simples, e um bloco curto não acumula erro.
    static constexpr int kHumBins = 6;
    void close_block();

    uint32_t rate_;
    uint32_t block_len_;
    float coeff_[kHumBins];
    float s1_[kHumBins] = {};
    float s2_[kHumBins] = {};
    uint32_t in_block_ = 0;
    uint32_t blocks_ = 0;
    double hum_power_ = 0.0;  // soma das potências por bloco (uma conta por bloco)

    // Somas inteiras: exatas e baratas na placa
    uint32_t n_ = 0;
    int64_t sum_ = 0;
    int64_t sum_sq_ = 0;
    int32_t peak_ = 0;
    uint32_t clipped_ = 0;
    uint32_t zeros_ = 0;
};

// dBFS de um valor em unidades de amostra de 16 bits; 0 vira -120.
float to_dbfs(double amplitude);

}  // namespace elex
