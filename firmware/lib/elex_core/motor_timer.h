// Tempo de uma vibração: quando desligar e quando pode vibrar de novo.
// Sem dependência de hardware; a virada do millis() é tratada por diferença de uint32_t.
#pragma once

#include <stdint.h>

namespace elex {

constexpr uint32_t kMotorRestMs = 300;  // intervalo mínimo entre vibrações

class MotorTimer {
public:
    // Inicia uma vibração. Retorna false se ainda estiver vibrando ou em descanso.
    bool start(uint32_t now_ms, uint32_t duration_ms);

    // true uma única vez, quando a vibração atinge a duração: hora de desligar.
    bool expired(uint32_t now_ms);

    bool active() const { return active_; }

    // Milissegundos até o desligamento; 0 se parado ou já vencido.
    uint32_t remaining_ms(uint32_t now_ms) const;

private:
    bool active_ = false;
    bool resting_ = false;  // há um intervalo a respeitar desde started_ms_
    uint32_t started_ms_ = 0;
    uint32_t duration_ms_ = 0;
};

}  // namespace elex
