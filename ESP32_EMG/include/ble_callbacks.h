#ifndef BLE_CALLBACKS_H
#define BLE_CALLBACKS_H

#include <BLEServer.h>

// ═══════════════════════════════════════════════════════════
// BLE SERVER CALLBACKS
// ═══════════════════════════════════════════════════════════

/**
 * @class MyServerCallbacks
 * @brief Callbacks para eventos do servidor BLE
 */
class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override;
  void onDisconnect(BLEServer* pServer) override;
};

#endif // BLE_CALLBACKS_H
