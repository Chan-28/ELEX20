// Parâmetros ajustáveis por comando MQTT e urgência por rótulo, sem dependência de hardware.
#pragma once

#include <stdint.h>

namespace elex {

struct Settings {
    float threshold = 0.6f;         // confiança mínima da classificação para publicar/vibrar
    bool doa_enabled = true;        // calcula a direção do som
    bool motor_enabled = true;      // aciona os motores
    float port1_skew = 0.f;         // atraso do I2S1 em relação ao I2S0, em amostras
    uint16_t motor_max_ms = 600;    // duração máxima de uma vibração
};

// Aplica um comando {key, value} depois de validar nome e faixa.
// Retorna false (sem alterar nada) para chave desconhecida ou valor fora da faixa.
bool settings_apply(Settings& s, const char* key, float value);

// Urgência do rótulo: 0 nenhuma, 1 baixa, 2 média, 3 alta. Rótulo desconhecido = 0.
// Mantenha igual ao seed de sound_classes em timescaledb/db-init.sql.
uint8_t urgency_for_label(const char* label);

// Intensidade PWM (0-255) para a urgência dada
uint8_t motor_duty_for_urgency(uint8_t urgency);

}  // namespace elex
