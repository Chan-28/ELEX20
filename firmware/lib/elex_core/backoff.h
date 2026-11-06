// Agendador de reconexão com recuo exponencial, sem dependência de hardware.
//
// Decide apenas quando tentar de novo; quem chama faz a tentativa. Todas as contas
// usam diferença de uint32_t, então a virada do millis() (49,7 dias) não atrapalha.
#pragma once

#include <stdint.h>

namespace elex {

class Backoff {
public:
    // A espera começa em min_ms e dobra a cada tentativa até max_ms.
    Backoff(uint32_t min_ms, uint32_t max_ms);

    // true se já se pode tentar. A primeira tentativa é imediata.
    bool due(uint32_t now_ms) const;

    // Registra uma tentativa feita em now_ms e aumenta a próxima espera.
    void attempted(uint32_t now_ms);

    // Conexão estabelecida: a sequência recomeça do início. A espera mínima desde a
    // última tentativa continua valendo, para um enlace instável não virar laço apertado.
    void connected();

    uint32_t wait_ms() const { return wait_ms_; }

private:
    uint32_t min_ms_;
    uint32_t max_ms_;
    uint32_t last_ms_ = 0;
    uint32_t wait_ms_ = 0;  // espera atual, contada a partir de last_ms_
    uint32_t next_ms_;      // espera que vale depois da próxima tentativa
};

}  // namespace elex
