// Ordem de tentativa entre as redes Wi-Fi gravadas no firmware, sem dependência de hardware.
//
// Cada rodada tenta todas as redes uma vez, começando pela última que conectou. Quem
// chama decide o tempo: uma janela fixa entre redes da mesma rodada e o recuo
// exponencial (Backoff) entre rodadas. Com uma rede só, cada rodada é uma tentativa.
#pragma once

#include <stddef.h>

namespace elex {

class WifiRotation {
public:
    explicit WifiRotation(size_t count) : count_(count ? count : 1) {}

    // Começa uma rodada pela rede preferida.
    void start_round() { pos_ = 0; }

    // Índice da próxima rede a tentar nesta rodada.
    size_t next();

    // true enquanto falta tentar alguma rede da rodada atual.
    bool in_round() const { return pos_ > 0 && pos_ < count_; }

    // A última rede tentada conectou: ela passa a ser a preferida.
    void connected() { preferred_ = last_; pos_ = 0; }

    size_t current() const { return last_; }
    size_t count() const { return count_; }

private:
    size_t count_;
    size_t preferred_ = 0;
    size_t last_ = 0;
    size_t pos_ = 0;
};

}  // namespace elex
