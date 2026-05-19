#ifndef DEBUG_H
#define DEBUG_H

#include <Arduino.h>
#include "config.h"
#include "structs.h"

// ═══════════════════════════════════════════════════════════
// DEBUG UTILITIES
// ═══════════════════════════════════════════════════════════

/**
 * @brief Imprime o banner de inicialização
 */
void printStartupBanner();

/**
 * @brief Imprime mensagem de sucesso na inicialização de um componente
 * @param component Nome do componente
 */
void printComponentInit(const char* component);

/**
 * @brief Imprime estatísticas de amostragem
 * @param voltage Última tensão lida
 * @param samples_sent Total de amostras enviadas
 */
void printSamplingStats(float voltage, uint32_t samples_sent);

/**
 * @brief Imprime estatísticas gerais do BLE
 * @param samplingState Estado de amostragem
 */
void printBLEStats(const SamplingState& samplingState);

#endif // DEBUG_H
