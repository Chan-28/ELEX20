# Debug do ELEX20

Guia para quem já conhece o projeto e precisa achar onde algo quebrou. Ele tem duas partes:

- **[Parte 1 — Hardware](#parte-1--hardware):** firmware, microfones, motores, modelo e desempenho da placa.
- **[Parte 2 — Software](#parte-2--software):** MQTT, n8n, banco, Grafana, Hermes e Docker.

Para instalar do zero, veja o [guia de instalação](install.md). A referência completa está em [reference.md](reference.md), e as convenções do código em [AGENTS.md](../AGENTS.md).

## Por onde começar

O caminho de um som é: **microfone → firmware → MQTT → n8n → TimescaleDB → Grafana/Hermes**. Ache o primeiro ponto em que o dado some:

| Pergunta                                  | Como responder                                                    |
| ----------------------------------------- | ----------------------------------------------------------------- |
| Os microfones captam?                     | [`mic_check.py report`](#12-microfones) com o firmware de bancada |
| O firmware classifica?                    | `[INF]` no [log serial](#11-log-serial)                           |
| A mensagem chega ao broker?               | [`mosquitto_sub`](#21-mqtt)                                       |
| O n8n processa?                           | [Executions do n8n](#22-n8n)                                      |
| Foi gravado?                              | [Grafana Explore](#23-banco)                                      |
| O sensor está saudável ao longo do tempo? | [`sensor_health.py`](#15-desempenho-da-placa)                     |

Nos comandos com `docker` no Linux, garanta antes que o Docker é o do sistema, e não o Docker Desktop (o `.envrc` faz isso com o direnv):

```bash
export DOCKER_HOST=unix:///var/run/docker.sock
```

Sem isso, `docker ps` pode voltar vazio com a stack rodando.

---

## Parte 1 — Hardware

### 1.1 Log serial

```bash
cd firmware && pio device monitor
```

| Linha                              | Significado                                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `[MEM] 2 janelas de … (PSRAM)`     | Buffers de áudio alocados. Com `(heap)` no lugar de `PSRAM`, a PSRAM não foi detectada: confira `memory_type` e a placa (N16R8) |
| `[MEM] ERRO: …`                    | Sem memória: a placa reinicia em loop                                                                                           |
| `[WiFi] Conectando a …`            | Tentando; o recuo vai de 15 s a 2 min                                                                                           |
| `[WiFi] IP: …  RSSI: …`            | Conectado. Abaixo de -80 dBm a conexão é instável                                                                               |
| `[MQTT] rc=-2`                     | Broker inalcançável: IP errado em `MQTT_HOST`, `MQTT_BIND` em loopback ou firewall                                              |
| `[MQTT] rc=4` / `rc=5`             | Usuário ou senha errados                                                                                                        |
| `[EI] Sem modelo em lib/ei-model/` | Firmware gravado sem modelo (ambiente `esp32s3`). Use `esp32s3_model`                                                           |
| `[EI] Erro: N`                     | `run_classifier` falhou                                                                                                         |
| `[INF] siren  91.0%  E (90°)`      | Detecção acima do limiar, com direção quando a urgência é maior que 0                                                           |
| `[CMD] chave = valor`              | Comando aplicado; `recusado` indica chave ou faixa inválida                                                                     |

Ambientes de build (`firmware/platformio.ini`):

| Ambiente        | Uso                                                                         |
| --------------- | --------------------------------------------------------------------------- |
| `esp32s3`       | Sem modelo: conecta e manda heartbeat, não classifica. É o que o CI compila |
| `esp32s3_model` | Uso real, com `firmware/lib/ei-model/<nome>_inferencing`                    |
| `esp32s3_debug` | Log detalhado e detecções simuladas com `"mock":true` (o n8n as descarta)   |
| `native`        | `pio test -e native`: testes do `lib/elex_core` sem hardware                |

Arquitetura: o `loop()` só classifica e estima a direção; a tarefa `net` cuida de Wi-Fi, MQTT e publicação; a tarefa `motor` é a única que aciona os motores; a `capture` lê o I2S. Sem rede, as detecções são descartadas (`offline_dropped`), mas a vibração continua.

### 1.2 Microfones

O firmware de bancada (`debug/firmware`) lê os microfones exatamente como o principal, sem Wi-Fi nem modelo. Detalhes em [debug/README.md](../debug/README.md).

```bash
cd debug/firmware && pio run -t upload && cd ../..
uv run --group debug python debug/mic_check.py report --port /dev/ttyUSB0 --quiet-room
```

A escala é a do firmware: 0 dBFS é o limite do int16 depois do ganho de 4x (`>>14`). Valores de referência:

| Medida                 | Esperado                                   | Fora disso                                       |
| ---------------------- | ------------------------------------------ | ------------------------------------------------ |
| RMS em silêncio        | -75 a -65 dBFS                             | Acima de -50: interferência; -120: canal morto   |
| Zeros                  | perto de 0%                                | Acima de 90%: SD solto, L/R errado ou sem 3,3 V  |
| Saturação              | 0%                                         | Acima de 0,1%: som alto demais ou ganho alto     |
| Offset DC              | perto de 0 (o INMP441 tem passa-alta)      | Acima de 500: defeito ou ruído elétrico          |
| Zumbido                | abaixo de -10 dB                           | 50/60 Hz da fonte ou do aterramento              |
| Diferença entre canais | até 6 dB, com o mesmo som chegando a todos | Microfone fraco ou furo tampado: piora a direção |

`short_reads` crescendo indica que as duas portas I2S entregam blocos desiguais: confira BCLK (GPIO 4) e WS (GPIO 5) e a configuração mestre/escravo.

Outros modos: `tap` confere a ordem dos canais; `record` grava WAV (4 canais ou a mistura mono que vai para o modelo, `--channels 1`); `analyze` analisa um WAV. A transmissão usa 2 Mbaud; com quadros corrompidos, use `--channels 1` ou um baud menor.

### 1.3 Direção e motores

- **Direção errada sempre do mesmo jeito:** canais trocados. Rode `mic_check.py tap`.
- **Direção imprecisa:** confira `MIC_RADIUS_M` (padrão 0,09 m) e calibre o atraso entre as portas I2S com o comando `port1_skew` (de -8 a 8 amostras), tocando um som de frente.
- **Motor não vibra:** `mic_check.py motors` testa sem o modelo. No monitor do firmware de bancada, `motor <0-3> <0-255> <ms>` aciona um motor só.
- **Vibra pouco ou demais:** a intensidade vem da urgência do rótulo; a duração máxima é `motor_max_ms` (100 a 2000 ms).

Comandos aceitos pelo sensor em `sound/cmd/<DEVICE_ID>` (o Hermes e o n8n validam as mesmas faixas):

| Chave           | Faixa       |
| --------------- | ----------- |
| `threshold`     | 0,30 a 0,99 |
| `doa_enabled`   | 0 ou 1      |
| `motor_enabled` | 0 ou 1      |
| `port1_skew`    | -8 a 8      |
| `motor_max_ms`  | 100 a 2000  |

### 1.4 Modelo e rótulos

- **Colocar um modelo:** `./install.sh --ei-model modelo.zip`, ou a opção no assistente. O instalador recusa modelos fora de 16 kHz e avisa sobre rótulos desconhecidos.
- **Rótulos:** a fonte é `classes/sound_classes.json`. Publicados e gravados em inglês (`siren`, `horn`…). Modelos antigos devolvem português (`sirene`), e o firmware traduz (`kLegacyLabels`, campo `rotulo_legado`). Rótulo fora da tabela vira urgência 0: sem vibração nem alerta, e `NULL` no banco.
- **Janela:** `AUDIO_SAMPLE_RATE` (16000) e `AUDIO_WINDOW_MS` (975) precisam bater com o projeto do Edge Impulse. O build falha se a frequência não bater.
- **Desempenho do modelo:** a sensibilidade atual nos sons de urgência 3 está longe da meta. O histórico está em [model-refinement](model-refinement/README.md).

### 1.5 Desempenho da placa

A cada 5 s, o heartbeat em `sound/status/<DEVICE_ID>` traz as métricas, gravadas em `device_status`. O status não é retido no broker: um sensor desligado para de gerar linhas, mesmo quando o n8n reconecta. Se `device_status` ganhar uma linha de um sensor desligado logo após reiniciar o n8n, sobrou um status retido de firmware antigo; regrave o sensor ou apague o retido com `mosquitto_pub -r -n -t sound/status/<DEVICE_ID>` (usuário `device`).

| Campo                            | Alerta quando                                                   |
| -------------------------------- | --------------------------------------------------------------- |
| `win_ms_avg`, `win_ms_max`       | Acima de 975 ms: a placa não acompanha o áudio e `dropped` sobe |
| `dsp_ms`, `nn_ms`                | Tempo do Edge Impulse; mostra qual etapa pesa                   |
| `heap_min`                       | Caindo ao longo das horas: vazamento                            |
| `stack_min`, `stack_task`        | Abaixo de 512 bytes: risco de estouro na tarefa indicada        |
| `wifi_connects`, `mqtt_connects` | Crescendo rápido: rede instável                                 |
| `dropped`, `offline_dropped`     | Janelas descartadas por lentidão; detecções perdidas sem rede   |
| `temp_c`                         | Acima de 80 °C: ventilação                                      |

Para um teste de longa duração, deixe o sensor ligado e rode:

```bash
uv run python debug/sensor_health.py --hours 24
```

Ele aponta reinícios, quedas, lentidão, vazamento, pilha, rede e calor, e sai com código 1 se houver problema.

---

## Parte 2 — Software

### 2.1 MQTT

Para ver as mensagens chegando, com o usuário `n8n` (o único que lê `sound/#`):

```bash
docker exec mosquitto sh -c 'mosquitto_sub -h localhost -u n8n -P "$(cat /run/secrets/mqtt_n8n/value)" -t "sound/#" -v'
```

Para mandar um comando direto ao sensor, sem passar pelo Hermes:

```bash
docker exec mosquitto sh -c 'mosquitto_pub -h localhost -u n8n -P "$(cat /run/secrets/mqtt_n8n/value)" -t sound/cmd/esp32s3-sound-01 -m "{\"key\":\"threshold\",\"value\":0.7}"'
```

- **ACL** (`mosquitto/acl`): `device` só publica em `sound/inference/+` e `sound/status/+`; `n8n` lê `sound/#` e é o único que escreve em `sound/cmd/+`; cada sensor só lê `sound/cmd/<client id>`. O client id do firmware é o `DEVICE_ID`.
- **Porta 1883** publicada só em `MQTT_BIND`. Com `127.0.0.1`, a placa não alcança o broker. Nunca use `0.0.0.0`.
- **Broker em loop de reinício** com `File exists` no log: versão antiga do `mosquitto/entrypoint.sh` (corrigida na v1.2.0). Na hora, resolva com `docker compose up -d --force-recreate mosquitto`.

### 2.2 n8n

Abra <http://localhost:5678> → **Executions**. Cada mensagem MQTT vira uma execução de **ELEX20 - Ingestão MQTT**, com a entrada e a saída de cada nó. Mensagens inválidas param em **Validar mensagem**: campos opcionais ruins viram `NULL`, e payloads quebrados são descartados.

**Workflow ativo, mas sem execuções:** se o Mosquitto estava fora quando o n8n subiu, o gatilho MQTT falha (`EAI_AGAIN mosquitto` no log) e não tenta de novo. Rode o instalador de novo ou:

```bash
docker compose exec n8n n8n unpublish:workflow --id=elex-ingestao-mqtt
docker compose exec n8n n8n publish:workflow --id=elex-ingestao-mqtt
docker compose restart n8n
```

O estado de cada gatilho fica na tabela `workflow_publication_trigger_status`, no banco `n8n`.

### 2.3 Banco

O TimescaleDB não expõe porta, de propósito. Para consultar:

- **Grafana → Explore → TimescaleDB:** SQL livre com o papel `grafana_ro`, só leitura.
- **Terminal:**

  ```bash
  docker exec -it timescaledb sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
  ```

Tabelas: `sound_events` (detecções, hypertable de 90 dias), `device_status` (heartbeats, 30 dias), `devices`, `sound_classes` (urgência por rótulo). Views: `sound_events_hourly` (agregação contínua), `device_last_status`, `sound_events_public` (sem `raw_json`, para o Hermes).

Papéis: `grafana_ro` só lê; `n8n_app` insere; `hermes_ro` lê sem `raw_json`. Nenhum é superusuário. O esquema vem de `timescaledb/init.sql` e de `timescaledb/db-init.sql`, que roda a cada subida e é idempotente: ele cria colunas novas, restaura a urgência dos rótulos e migra rótulos antigos.

Para usar o DBeaver, abra um túnel temporário, só no loopback, em vez de publicar a porta no compose:

```bash
docker run --rm --network elex20_monitoring -p 127.0.0.1:5432:5432 alpine/socat tcp-listen:5432,fork,reuseaddr tcp-connect:timescaledb:5432
```

Conecte com `grafana_ro`. A senha está em `docker exec grafana cat /run/secrets/grafana_ro/value`.

### 2.4 Grafana, logs e alertas

- **Painel:** **Sons Urbanos — ELEX20**, com eventos por hora, últimos eventos e estado dos sensores.
- **Logs dos containers:** Explore → Loki, por exemplo `{service="mosquitto"}`. Só existe com `COMPOSE_PROFILES=logs`, no Linux.
- **Alertas** (Alerting → pasta ELEX20): sensor sem heartbeat, ingestão parada e container em loop de reinício. Nenhum canal de notificação vem configurado; crie um contact point para recebê-los.

### 2.5 Hermes

O Hermes lê o banco com `hermes_ro` e pede comandos ao n8n, que valida e publica em `sound/cmd`. Ele nunca publica no MQTT. Alerta que não chega: confira `TELEGRAM_HOME_CHANNEL`, se o rótulo tem urgência 3 e a execução do n8n (nó **Alertar Hermes**). Logs:

```bash
docker compose logs -f hermes-agent
```

### 2.6 Testar o pipeline sem a placa

```bash
uv run python debug/simulate_sensor.py --devices 2 --duration 120 --invalid --listen-commands
uv run python debug/simulate_sensor.py --cleanup
```

Sensores `sim-*` publicam heartbeats e detecções como o firmware; `--invalid` mistura payloads quebrados; `--listen-commands` mostra os comandos que o Hermes manda.

### 2.7 Docker e segredos

```bash
docker compose ps
docker compose logs -f <serviço>
```

- **Segredos internos** (senhas dos papéis do banco e do MQTT, tokens entre n8n e Hermes): gerados pelo `secrets-init` em volumes `sec_*` e montados em `/run/secrets/<nome>/value`. Nenhum é obrigatório no `.env`.
- **Volumes:** `docker compose down -v` apaga os volumes, ou seja, o histórico e os segredos. Para remover, use `./install.sh --uninstall`, que só apaga dados se você pedir.
- **Infraestrutura mudou?** Rode `bash scripts/infra-smoke.sh` (papéis do banco e ACL do MQTT, em containers descartáveis).
- **Testes:** `uv run pytest` e `cd firmware && pio test -e native`.
