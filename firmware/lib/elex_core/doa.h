// Estimativa de direção do som (DOA) com 4 microfones, sem dependência de hardware.
//
// Geometria: microfones numa faixa circular de raio configurável, nos azimutes
// 0° (frente), 90° (direita), 180° (trás) e 270° (esquerda). O azimute 0° é a frente
// do usuário e cresce no sentido horário (visto de cima).
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace elex {

constexpr uint8_t kNumMics = 4;
constexpr uint8_t kNumSectors = 8;
constexpr size_t kDoaWindow = 512;  // amostras por canal usadas na estimativa

struct DoaConfig {
    float sample_rate = 16000.f;
    float radius_m = 0.09f;
    // Atraso (em amostras) do controlador I2S1 em relação ao I2S0; vale medir no protótipo
    float port1_skew_samples = 0.f;
    // Faixa de frequências usada no PHAT (fora dela o ruído domina)
    float f_min_hz = 300.f;
    float f_max_hz = 6000.f;
    // Abaixo desta confiança o resultado é marcado como inválido
    float min_confidence = 0.12f;
};

struct DoaResult {
    bool valid = false;
    float azimuth_deg = 0.f;  // [0, 360)
    uint8_t sector = 0;       // 0 = N (frente), 1 = NE, ... sentido horário, 45° cada
    float confidence = 0.f;   // [0, 1]
};

// mics[k] aponta para kDoaWindow amostras do microfone k (0 frente, 1 direita, 2 trás, 3 esquerda).
// Porta I2S de cada microfone: frente e trás no I2S0, direita e esquerda no I2S1.
DoaResult doa_estimate(const int16_t* const mics[kNumMics], const DoaConfig& cfg);

// Início da janela de kDoaWindow amostras com maior energia em mono[0..n); 0 se n for menor.
size_t doa_loudest_window(const int16_t* mono, size_t n);

uint8_t sector_from_azimuth(float azimuth_deg);
const char* sector_name(uint8_t sector);  // "N", "NE", "E", "SE", "S", "SO", "O", "NO"

}  // namespace elex
