#ifndef BLE_UTILS_H
#define BLE_UTILS_H

#include <stdint.h>
#include <BLECharacteristic.h>
#include "config.h"
#include "structs.h"

// ═══════════════════════════════════════════════════════════
// BLE UTILITIES
// ═══════════════════════════════════════════════════════════

/**
 * @brief Inicializa o dispositivo BLE
 * @return true se inicializado com sucesso, false caso contrário
 */
bool initBLE();

/**
 * @brief Inicia o advertising BLE
 */
void startBLEAdvertising();

/**
 * @brief Converte um float para array de bytes (little-endian)
 * @param value Valor float a ser convertido
 * @param bytes Array de bytes (mínimo 4 bytes)
 */
void floatToBytes(float value, uint8_t* bytes);

/**
 * @brief Monta pacote EMG no formato [timestamp (4B) + voltage (4B)]
 * @param sample Amostra com timestamp e voltage
 * @param packet Array de bytes para armazenar pacote (mínimo 8 bytes)
 */
void createEMGPacket(const EMGSample& sample, uint8_t* packet);

/**
 * @brief Envia uma notificação BLE com dados EMG
 * @param packet Array com 8 bytes do pacote
 */
void sendBLENotification(const uint8_t* packet);

/**
 * @brief Verifica se há cliente BLE conectado
 * @return true se conectado, false caso contrário
 */
bool isBLEConnected();

/**
 * @brief Retorna a característica BLE global
 * @return Ponteiro para BLECharacteristic
 */
BLECharacteristic* getBLECharacteristic();

#endif // BLE_UTILS_H
