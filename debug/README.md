# Ferramentas de debug

Programas para testar o ELEX20 por partes: o hardware do sensor na bancada e o pipeline sem a placa. Nada aqui vai para o sensor em uso nem sobe com a stack.

| Ferramenta                                 | Precisa de                          | Para quê                                                                          |
| ------------------------------------------ | ----------------------------------- | --------------------------------------------------------------------------------- |
| [`firmware/`](firmware/) + `mic_check.py`  | Placa na USB                        | Qualidade dos 4 microfones, ordem dos canais, gravação em WAV e teste dos motores |
| [`simulate_sensor.py`](simulate_sensor.py) | Stack no ar                         | Sensores falsos no MQTT para testar n8n, banco, Grafana, alertas e Hermes         |
| [`sensor_health.py`](sensor_health.py)     | Stack no ar com heartbeats gravados | Saúde de cada sensor: reinícios, latência, memória, pilha, rede e temperatura     |

Os scripts falam com o Docker da stack. Sem o direnv, exporte antes `DOCKER_HOST=unix:///var/run/docker.sock`, ou eles vão procurar os containers no Docker Desktop.

## Microfones e motores na bancada

O firmware de bancada lê os microfones exatamente como o firmware principal (mesmos pinos, formato e ganho), mas sem Wi-Fi nem modelo. Ele imprime a qualidade de cada canal a cada segundo e aceita comandos pela serial.

```bash
cd debug/firmware && pio run -t upload && cd ../..
```

```bash
uv run --group debug python debug/mic_check.py report --port /dev/ttyUSB0 --quiet-room
```

Mostra, por canal, o nível RMS e de pico em dBFS, o offset DC, a saturação, as amostras zeradas e o zumbido de 50/60 Hz, com um veredito:

- **canal morto:** tudo zero ou sem ruído nenhum. Confira solda, pino SD, pino L/R e alimentação.
- **saturando:** amostras no limite. Som alto demais ou ganho alto (`>>14` no firmware).
- **zumbido forte:** a rede elétrica entrando pela fonte ou pelo aterramento.
- **ruído alto em silêncio** (com `--quiet-room`): em sala silenciosa, um INMP441 fica perto de -75 a -65 dBFS nesta escala. Bem acima disso é interferência ou microfone ruim.
- **nível longe dos outros:** com o mesmo som chegando a todos (fale a uns 2 m, ou toque ruído), mais de 6 dB de diferença indica microfone fraco, furo tampado ou ganho diferente. Isso estraga a estimativa de direção.

```bash
uv run --group debug python debug/mic_check.py tap --port /dev/ttyUSB0
```

Pede para bater de leve em cada microfone, na ordem frente, direita, trás, esquerda, e confere se o canal certo responde. Um par trocado (pino L/R ou portas I2S invertidas) faz o motor errado vibrar.

```bash
uv run --group debug python debug/mic_check.py record bancada.wav --port /dev/ttyUSB0 --seconds 10
uv run --group debug python debug/mic_check.py record modelo.wav --port /dev/ttyUSB0 --channels 1
uv run --group debug python debug/mic_check.py analyze bancada.wav
```

Grava os 4 canais, ou a mistura mono que vai para o modelo, num WAV de 16 kHz. Serve para ouvir o que a placa ouve e para juntar gravações reais ao conjunto de treino: o modelo foi treinado com áudio da internet, e o som deste microfone, nesta caixa, é diferente. `analyze` faz a mesma análise do `report` num WAV qualquer.

A transmissão usa 2 Mbaud. Se aparecerem quadros corrompidos, grave só a mistura (`--channels 1`) ou baixe o baud em `firmware/platformio.ini` e no `--baud`.

```bash
uv run --group debug python debug/mic_check.py motors --port /dev/ttyUSB0
```

Vibra os quatro motores em sequência. No monitor serial, `motor <0-3> <0-255> <ms>` aciona um motor só.

## Sensores simulados

```bash
uv run python debug/simulate_sensor.py --devices 2 --duration 120 --invalid --listen-commands
```

Publica heartbeats (com as métricas de desempenho) e detecções com os rótulos de `classes/sound_classes.json`, como o firmware. Com urgência alta, o alerta segue para o Hermes. `--invalid` mistura payloads quebrados, que o n8n precisa descartar sem parar. `--listen-commands` mostra o que chega em `sound/cmd/<id>` quando você pede um ajuste ao Hermes.

Os ids começam com `sim-` e os dados vão para o banco de verdade. Para apagá-los:

```bash
uv run python debug/simulate_sensor.py --cleanup
```

## Saúde dos sensores

```bash
uv run python debug/sensor_health.py --hours 24
```

Resume os heartbeats de cada sensor e aponta problemas: reinícios, períodos fora do ar, janelas mais lentas que os 975 ms de áudio, menor heap livre caindo (vazamento), pouca folga de pilha, reconexões frequentes, Wi-Fi fraco e calor. Para um teste de longa duração, deixe o sensor ligado um ou mais dias e rode com `--hours` cobrindo o período. Sai com código 1 se houver problema, o que permite usá-lo num cron.
