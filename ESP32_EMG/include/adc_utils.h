#ifndef ADC_UTILS_H
#define ADC_UTILS_H

#include <stdint.h>
#include <Adafruit_ADS1X15.h>
#include "config.h"
#include "structs.h"

// ═══════════════════════════════════════════════════════════
// ADC UTILITIES
// ═══════════════════════════════════════════════════════════

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
