#ifndef ADC_UTILS_H
#define ADC_UTILS_H

#include <cstddef>
#include <cstdint>
#include "config.h"
#include "structs.h"

// ═══════════════════════════════════════════════════════════
// ADC UTILITIES
// ═══════════════════════════════════════════════════════════

// Forward declaration to avoid pulling in Adafruit header (and its
// transitive dependency on FreeRTOS) in files that include this header.
class Adafruit_ADS1115;

/**
 * @brief Inicializa o ADS1115
 * @return true se inicializado com sucesso, false caso contrário
 */
bool initADS1115();

/**
 * @brief Realiza calibração automática do offset EMG
 * @param samplingState Referência para estrutura de estado
 */
void performCalibration(SamplingState& samplingState);

/**
 * @brief Realiza uma leitura do ADC e calcula a tensão
 * @param samplingState Referência para estrutura de estado
 * @return Tensão lida em Volts
 */
float readEMGVoltage(const SamplingState& samplingState);

/**
 * @brief Retorna a instância global do ADS1115
 * @return Referência do ADS1115
 */
Adafruit_ADS1115& getADS1115Instance();

#endif // ADC_UTILS_H
