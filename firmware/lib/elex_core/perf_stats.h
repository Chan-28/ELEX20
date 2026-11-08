// Estatística de tempo entre dois heartbeats (média e máximo), sem dependência de hardware.
//
// Quem mede chama add(); a tarefa de rede chama take() a cada status, o que zera a
// contagem. A classe não tem trava: em main.cpp as duas chamadas ficam numa seção crítica.
#pragma once

#include <stdint.h>

namespace elex {

struct PerfWindow {
    uint32_t count = 0;  // medições no período; 0 = nada a publicar
    float avg_ms = 0.f;
    float max_ms = 0.f;
};

class PerfStats {
public:
    // Medições negativas ou não finitas (relógio errado) são ignoradas.
    void add(float ms);

    // Devolve o período atual e começa outro.
    PerfWindow take();

private:
    uint32_t count_ = 0;
    double sum_ms_ = 0.0;
    float max_ms_ = 0.f;
};

// Arredonda para uma casa decimal, para o JSON do status não levar "123.456789".
float round1(float v);

}  // namespace elex
