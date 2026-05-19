#ifndef STRUCTS_H
#define STRUCTS_H

#include <stdint.h>

// ═══════════════════════════════════════════════════════════
// DATA STRUCTURES
// ═══════════════════════════════════════════════════════════

/**
 * @struct SamplingState
 * @brief Estado geral da amostragem e transmissão de dados
 */
struct SamplingState {
  uint32_t lastSampleTime;    // Timestamp da última amostra (ms)
  float offset;               // Offset de calibração (V)
  bool isCalibrated;          // Flag de calibração completa
  uint32_t samples_sent;      // Contador de amostras enviadas
};

/**
 * @struct EMGSample
 * @brief Estrutura de uma amostra EMG
 */
struct EMGSample {
  uint32_t timestamp;         // Timestamp em ms (4 bytes)
  float voltage;              // Tensão em V (4 bytes)
};

#endif // STRUCTS_H
