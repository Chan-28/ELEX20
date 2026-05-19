# Estrutura Modularizada do Projeto ESP32 EMG

## 📋 Visão Geral

Este projeto foi reorganizado em uma arquitetura modular, separando responsabilidades em diferentes módulos para melhorar manutenibilidade, testabilidade e reusabilidade do código.

## 📁 Estrutura de Diretórios

```
ESP32_EMG/
├── include/                 # Headers (.h)
│   ├── config.h            # Constantes de configuração global
│   ├── structs.h           # Estruturas de dados
│   ├── ble_callbacks.h     # Declarações de callbacks BLE
│   ├── ble_utils.h         # Interface BLE
│   ├── adc_utils.h         # Interface ADC/ADS1115
│   └── debug.h             # Interface de debug
│
├── src/                     # Implementações (.cpp)
│   ├── main.cpp            # Arquivo principal (setup + loop)
│   ├── ble_callbacks.cpp   # Implementação callbacks BLE
│   ├── ble_utils.cpp       # Implementação de funções BLE
│   ├── adc_utils.cpp       # Implementação de funções ADC
│   └── debug.cpp           # Implementação de funções debug
│
├── platformio.ini          # Configuração PlatformIO
└── README.md               # Este arquivo

```

## 🔧 Módulos

### 1. **config.h** - Configurações Globais
Centraliza todas as constantes do projeto:
- **BLE**: Nome do dispositivo, UUIDs de serviço e característica
- **I2C**: Pinos (SDA/SCL) e frequência
- **ADS1115**: Canal, resolução, ganho, taxa de dados
- **Amostragem**: Taxa de amostragem (Hz), intervalo entre amostras
- **Calibração**: Duração da calibração

**Uso**: Include em qualquer arquivo que precise de constantes
```cpp
#include "config.h"
// Acesso: SAMPLE_RATE, ADS_I2C_ADDRESS, etc.
```

### 2. **structs.h** - Estruturas de Dados
Define estruturas utilizadas em todo o projeto:

#### `SamplingState`
```cpp
struct SamplingState {
  uint32_t lastSampleTime;    // Timestamp da última amostra (ms)
  float offset;               // Offset de calibração (V)
  bool isCalibrated;          // Flag de calibração completa
  uint32_t samples_sent;      // Contador de amostras enviadas
};
```

#### `EMGSample`
```cpp
struct EMGSample {
  uint32_t timestamp;         // Timestamp em ms (4 bytes)
  float voltage;              // Tensão em V (4 bytes)
};
```

### 3. **ble_callbacks.h / ble_callbacks.cpp** - Callbacks BLE
Implementa os callbacks de eventos BLE:

- **`onConnect()`**: Chamado quando cliente BLE se conecta
- **`onDisconnect()`**: Chamado quando cliente BLE se desconecta

```cpp
class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override;
  void onDisconnect(BLEServer* pServer) override;
};
```

### 4. **ble_utils.h / ble_utils.cpp** - Utilitários BLE
Encapsula toda a lógica de BLE:

| Função | Descrição |
|--------|-----------|
| `initBLE()` | Inicializa dispositivo, serviço, característica |
| `startBLEAdvertising()` | Inicia broadcasting BLE |
| `floatToBytes()` | Converte float para bytes (little-endian) |
| `createEMGPacket()` | Monta pacote [timestamp + voltage] |
| `sendBLENotification()` | Envia notificação ao cliente |
| `isBLEConnected()` | Verifica conexão de cliente |
| `getBLECharacteristic()` | Retorna característica global |

### 5. **adc_utils.h / adc_utils.cpp** - Utilitários ADC
Encapsula interface com ADS1115:

| Função | Descrição |
|--------|-----------|
| `initADS1115()` | Inicializa I2C e ADS1115 |
| `readEMGVoltage()` | Lê tensão EMG (com offset) |
| `performCalibration()` | Calibra offset automático |
| `getADS1115Instance()` | Retorna instância global do ADS |

### 6. **debug.h / debug.cpp** - Debug
Funções de impressão formatada para serial:

| Função | Descrição |
|--------|-----------|
| `printStartupBanner()` | Banner inicial |
| `printComponentInit()` | Mensagem de componente inicializado |
| `printSamplingStats()` | Estatísticas de amostragem |
| `printBLEStats()` | Estatísticas BLE |

### 7. **main.cpp** - Arquivo Principal
Contém apenas `setup()` e `loop()`:

- **`setup()`**: Inicializa todos os componentes em ordem
- **`loop()`**: Amostragem em tempo real e transmissão BLE

## 🔄 Fluxo de Execução

```
setup()
  ├─ Serial.begin()
  ├─ printStartupBanner()
  ├─ initADS1115()          [I2C, ADS1115]
  ├─ initBLE()              [Device, Service, Characteristic, Callbacks]
  ├─ startBLEAdvertising()  [Advertising]
  ├─ performCalibration()   [Calibração]
  └─ print("Ready")

loop() [Repetido a ~500 Hz]
  ├─ if (!deviceConnected) → return
  ├─ readEMGVoltage()       [ADC leitura]
  ├─ createEMGPacket()      [Montar payload]
  ├─ sendBLENotification()  [Enviar via BLE]
  ├─ samplingState.samples_sent++
  └─ if (samples % 100 == 0) → printSamplingStats()
```

## 📊 Formato de Dados

**Pacote EMG (8 bytes)**:
```
[0-3]  : timestamp (4 bytes, uint32_t, little-endian) [ms]
[4-7]  : voltage   (4 bytes, float32, little-endian) [V]
```

## 🛠️ Como Compilar e Fazer Upload

### Com PlatformIO CLI:
```bash
# Compilar
pio run -e esp32dev

# Upload
pio run -e esp32dev --target upload

# Monitor Serial
pio device monitor --baud 115200
```

### Com VS Code:
1. Instale a extensão PlatformIO
2. Clique em `Build` (marca de visto)
3. Clique em `Upload` (seta)
4. Clique em `Monitor` (plug)

## 🔧 Configuração personalizada

### Alterar taxa de amostragem
Edite `include/config.h`:
```cpp
#define SAMPLE_RATE 500  // Altere para desejado (Hz)
```

### Alterar UUID do Serviço BLE
Edite `include/config.h`:
```cpp
#define BLE_SERVICE_UUID "YOUR-NEW-UUID"
#define BLE_CHAR_UUID "bef8d6c9-9c21-4c9e-b632-bd763f7a92bf"
```

### Habilitar/Desabilitar Debug
Edite `include/config.h`:
```cpp
#define DEBUG_ENABLED 1      // 1 = ativado, 0 = desativado
#define DEBUG_INTERVAL 100   // Print a cada N amostras
```

## ✅ Benefícios da Modularização

- ✅ **Separação de responsabilidades**: Cada módulo tem uma função clara
- ✅ **Reutilização**: Funções podem ser usadas em outros projetos
- ✅ **Testabilidade**: Mais fácil testar componentes isoladamente
- ✅ **Manutenibilidade**: Código organizado e documentado
- ✅ **Escalabilidade**: Fácil adicionar novos módulos
- ✅ **Debugging**: Erros localizados rapidamente

## 📚 Referências

- [PlatformIO Docs](https://docs.platformio.org/)
- [ESP32 Arduino Core](https://github.com/espressif/arduino-esp32)
- [NimBLE Arduino](https://github.com/h2zero/NimBLE-Arduino)
- [Adafruit ADS1X15](https://github.com/adafruit/Adafruit_ADS1X15)

---

**Versão**: 2.0 (Modularizada)  
**Data**: 2026-05-18  
**Status**: Pronto para produção
