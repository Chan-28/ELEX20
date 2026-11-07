<!-- markdownlint-disable MD033 -->

# Guia completo do ELEX20

Este guia traz os detalhes que ficam fora do [README](../README.md).

## Sobre

O ELEX20 é um wearable de percepção sonora. Quatro microfones captam o ambiente, um ESP32-S3 reconhece no próprio aparelho sons como sirenes, buzinas e tiros, e estima a direção deles. Quatro motores vibram para indicar essa direção, com mais força quanto maior a urgência do som.

### Recursos

- **Classificação no aparelho:** o modelo Edge Impulse roda no ESP32-S3, sem depender da nuvem.
- **Direção do som:** quatro microfones indicam frente, trás, direita, esquerda e diagonais.
- **Feedback motor:** a intensidade da vibração cresce com a urgência.
- **Histórico e painéis:** o TimescaleDB guarda as detecções, e o Grafana as exibe.
- **Assistente:** o Hermes responde no Telegram ou no Discord, envia alertas e ajusta o sensor.
- **Instalador multiplataforma:** sobe o servidor no Windows, no macOS e no Linux.

### Arquitetura

O sensor é a parte principal do projeto:

```text
4 microfones INMP441 → ESP32-S3 (classificação + direção) → motor de vibração
```

O servidor é um complemento, executado no seu computador, para o histórico e os alertas:

```text
Sensor → [MQTT / Wi-Fi] → Mosquitto → n8n → TimescaleDB → Grafana (painéis)
                                                        → Hermes (chat, alertas e comandos)
```

> [!IMPORTANT]
> O modelo que reconhece os sons **não vem neste repositório**. Sem ele, o sensor conecta e informa o próprio estado, mas não classifica nem vibra. Veja [Usar um modelo real](#usar-um-modelo-real).

> [!NOTE]
> O firmware foi feito para seguir classificando, estimando a direção e vibrando sem Wi-Fi ou Mosquitto, e para reconectar sozinho, com intervalos crescentes. Só o histórico, os alertas e os comandos dependem da rede. As detecções feitas sem conexão são descartadas, e os comandos enviados nesse período se perdem. O campo `offline_dropped`, no status do sensor, conta as detecções que não chegaram ao servidor. Esse comportamento ainda não foi validado em hardware.

## Início rápido

Com o [Docker](#instale-o-docker), o Git e o Python 3 instalados:

```bash
git clone https://github.com/Chan-28/ELEX20.git
cd ELEX20
./install.sh
```

No Windows, use `install.bat` no lugar de `./install.sh`. Depois abra o Grafana em <http://localhost:3000> e faça o [teste sem sensor](#teste-sem-sensor).

Para gravar a placa, siga para [Build e gravação do firmware](#build-e-gravação-do-firmware).

## Requisitos

| Parte                      | O que faz                                             | O que você precisa                                                                                               |
| -------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Sensor** (o wearable)    | Capta o som, classifica e vibra indicando a direção   | O [hardware](#hardware), o repositório clonado, o [PlatformIO](https://platformio.org/) e um modelo Edge Impulse |
| **Servidor** (complemento) | Guarda o histórico, mostra os painéis e envia alertas | Windows, macOS ou Linux com Docker e alguns GB livres para as imagens                                            |

## Instalação

O instalador sobe todos os serviços e configura o n8n sozinho, e as senhas internas são geradas automaticamente. Você não precisa saber programar.

### Instale o Docker

O Docker é o único programa obrigatório para usar o executável.

<details>
<summary><strong>Windows</strong></summary>

Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/), deixando marcada a opção **WSL 2**. Reinicie se pedir. Depois, abra o Docker Desktop e espere ele iniciar.

</details>

<details>
<summary><strong>macOS</strong></summary>

Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/) ou rode:

```bash
brew install --cask docker
```

Depois, abra o Docker Desktop e espere ele iniciar.

</details>

<details>
<summary><strong>Linux</strong></summary>

Instale conforme a sua distribuição:

```bash
# Ubuntu, Debian, Linux Mint, Fedora, RHEL e Rocky
curl -fsSL https://get.docker.com | sudo sh

# Arch e Manjaro
sudo pacman -S docker docker-compose

# openSUSE
sudo zypper install docker docker-compose
```

Guias oficiais: [Ubuntu](https://docs.docker.com/engine/install/ubuntu/), [Debian](https://docs.docker.com/engine/install/debian/) e [Fedora](https://docs.docker.com/engine/install/fedora/).

Depois, ligue o serviço e dê permissão ao seu usuário. Saia da sessão e entre de novo para valer:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

</details>

Confira a instalação. Se faltar algo, o instalador também explica o que fazer.

```bash
docker compose version
```

### Opção 1: pelo repositório (recomendada para gravar o sensor)

Este caminho precisa de Git e Python 3. O repositório vira a própria pasta de instalação, e o instalador pode gerar o `firmware/.env`.

```bash
git clone https://github.com/Chan-28/ELEX20.git
cd ELEX20
./install.sh    # Windows: install.bat
```

### Opção 2: pelo executável (só o servidor)

O executável dispensa Python e instala em `~/ELEX20` (no Windows, `C:\Users\<você>\ELEX20`), mas não traz a pasta `firmware/`.

Baixe o arquivo do seu sistema na página de [Releases](https://github.com/Chan-28/ELEX20/releases):

| Sistema                             | Arquivo                             |
| ----------------------------------- | ----------------------------------- |
| Windows                             | `elex-installer-windows-x86_64.exe` |
| macOS (Apple Silicon: M1, M2, ...)  | `elex-installer-macos-arm64`        |
| macOS (Intel)                       | `elex-installer-macos-x86_64`       |
| Linux (PC comum)                    | `elex-installer-linux-x86_64`       |
| Linux (ARM: Raspberry Pi 4/5, etc.) | `elex-installer-linux-arm64`        |

> [!NOTE]
> Os nomes acima valem a partir da próxima release. A v1.0.0 ainda traz `elex-instalador-*` no lugar de `elex-installer-*`. O mesmo arquivo serve para qualquer distribuição Linux; para saber se o seu sistema é x86_64 ou ARM, rode `uname -m`.

Depois, execute:

<details>
<summary><strong>Windows</strong></summary>

Dê dois cliques no arquivo. Se o SmartScreen avisar "O Windows protegeu seu computador", clique em **Mais informações** e depois em **Executar assim mesmo**. O executável não tem assinatura paga da Microsoft; veja [como verificar o download](#verificar-o-download).

</details>

<details>
<summary><strong>macOS</strong></summary>

Abra o Terminal na pasta do download e rode (em Macs Intel, troque `arm64` por `x86_64`):

```bash
chmod +x elex-installer-macos-arm64
xattr -d com.apple.quarantine elex-installer-macos-arm64
./elex-installer-macos-arm64
```

</details>

<details>
<summary><strong>Linux</strong></summary>

```bash
chmod +x elex-installer-linux-x86_64
./elex-installer-linux-x86_64
```

</details>

### Siga o assistente

O instalador abre um assistente em inglês, em tela cheia, e só muda algo depois da tela de revisão:

1. **Pasta:** escolha onde instalar, digitando o caminho ou com **Browse…**. O assistente também confere o Docker aqui.
2. **Serviços:** ligue o que for usar: sensor na rede, OpenRouter, Telegram, Discord e modelo local de IA (cerca de 2 GB). Veja [Telegram](#telegram).
3. **Aparelho:** nome e senha do Wi-Fi e IP do computador, para gerar o `firmware/.env`. Só aparece se a pasta tiver `firmware/`.
4. **Revisão:** confira tudo, com os segredos ocultos, e confirme.

Use `Tab` para mudar de campo, `Esc` para voltar e `Ctrl+Q` para sair. O assistente recusa dados inválidos, como um IP no campo do Wi-Fi.

Ao final, o instalador mostra os endereços e os logins. Na primeira vez, o Docker baixa alguns GB de imagens, o que pode levar vários minutos.

> [!WARNING]
> Guarde o arquivo `.env` da pasta de instalação e não o compartilhe.

Pode rodar o instalador de novo a qualquer momento: ele carrega o que já existe na pasta e só grava o que você mudar. Deixe um segredo em branco para manter o valor atual.

Só uma instalação cabe em cada computador, porque os nomes dos containers são fixos. Se já houver uma em outra pasta, o assistente aponta para ela.

Sem Python, sem internet para baixar a biblioteca [Textual](https://textual.textualize.io/) ou com `--no-tui`, o instalador usa perguntas em texto simples. No Debian e no Ubuntu, instale `python3-venv` para ter a tela cheia pelo `./install.sh`.

| Opção                | Efeito                                                         |
| -------------------- | -------------------------------------------------------------- |
| `--dir PASTA`        | Define a pasta e pula a escolha                                |
| `--non-interactive`  | Não pergunta nada; usa os padrões e os `--set`                 |
| `--skip-model`       | Não baixa o modelo local do Ollama                             |
| `--ei-model ARQUIVO` | Coloca um modelo do Edge Impulse (`.zip` ou pasta) no firmware |
| `--set KEY=VALUE`    | Define uma variável do `.env`                                  |
| `--dry-run`          | Cria os arquivos, mas só mostra os comandos do Docker          |
| `--no-tui`           | Usa perguntas em texto simples                                 |

### Abra os serviços

| Serviço                              | Endereço                    | Usuário             | Senha                            |
| ------------------------------------ | --------------------------- | ------------------- | -------------------------------- |
| **Grafana** — painéis e métricas     | <http://localhost:3000>     | `admin`             | `password` (placeholder, troque) |
| **n8n** — automação de fluxos        | <http://localhost:5678>     | criado no 1º acesso | —                                |
| **Hermes Dashboard** — assistente IA | <http://localhost:9119>     | `admin`             | `password` (placeholder, troque) |
| **Mosquitto** — broker MQTT (sensor) | `mqtt://localhost:1883`     | `device` / `n8n`    | gerada sozinha                   |
| **TimescaleDB** — banco de dados     | interno (sem porta exposta) | `postgres`          | `POSTGRES_PASSWORD` (no `.env`)  |

> [!CAUTION]
> Os logins `admin` / `password` servem só para uso na sua máquina. [Troque-os](#trocar-senhas) antes de qualquer outro uso.

### Teste sem sensor

Para confirmar o caminho inteiro antes de gravar o firmware, publique uma detecção de teste. Rode na pasta de instalação, em um terminal Linux, macOS, Git Bash ou WSL2:

```bash
docker compose exec mosquitto sh -c 'mosquitto_pub -h localhost -u device -P "$(cat /run/secrets/mqtt_device/value)" -t sound/inference/teste-01 -m "{\"label\":\"siren\",\"confidence\":0.9}"'
```

Depois abra o painel **Sons Urbanos — ELEX20** no Grafana: um evento `siren` do dispositivo `teste-01` deve aparecer. Como `siren` tem urgência 3, o alerta também segue para o chat configurado no Hermes. Esse evento de teste fica no histórico.

Se nada aparecer, veja [Solução de problemas](#solução-de-problemas).

### Instalação manual

<details>
<summary>Subir a stack sem o instalador (avançado)</summary>

1. Crie o `.env`:

   ```bash
   cp .env.example .env
   ```

   O `.env` é opcional: sem ele, a stack sobe com os padrões (logins `admin` / `password`). Nenhuma senha precisa ser criada à mão, porque o serviço `secrets-init` gera os segredos internos na primeira subida. Veja [Configuração](#configuração).

2. Suba os serviços e espere de 30 a 60 s. Todos devem ficar `running` ou `healthy`:

   ```bash
   docker compose up -d
   docker compose ps
   ```

3. Importe os workflows no n8n:

   ```bash
   docker compose exec n8n n8n import:workflow --separate --input=/workflows
   ```

4. Veja as senhas das credenciais do n8n:

   ```bash
   docker compose exec n8n cat /run/secrets/n8n_db/value
   docker compose exec n8n cat /run/secrets/mqtt_n8n/value
   ```

5. No n8n, crie as duas credenciais e ative os dois workflows:

   | Credencial                           | Host          | Dados                                                  |
   | ------------------------------------ | ------------- | ------------------------------------------------------ |
   | **Postgres** `TimescaleDB (n8n_app)` | `timescaledb` | Banco `POSTGRES_DB`, usuário `n8n_app`, senha `n8n_db` |
   | **MQTT** `Mosquitto (usuário n8n)`   | `mosquitto`   | Porta 1883, usuário `n8n`, senha `mqtt_n8n`            |

6. Baixe a reserva local do Hermes:

   ```bash
   docker compose exec ollama ollama pull qwen2.5:3b
   ```

</details>

## Configuração

As configurações ficam no `.env` da pasta de instalação. Preencha só o que for seu; o resto já tem padrão.

| Variável                                                                | Para que serve                                                                   |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `MQTT_BIND`                                                             | IP do computador na rede. O padrão `127.0.0.1` só aceita conexões locais         |
| `OPENROUTER_API_KEY`                                                    | IA na nuvem para o Hermes. Sem ela, ele usa o modelo local                       |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL` | Token do bot, IDs atendidos e chat que recebe os alertas                         |
| `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL`    | O mesmo para o Discord                                                           |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`                          | Login do Grafana                                                                 |
| `HERMES_DASHBOARD_USER`, `HERMES_DASHBOARD_PASS`                        | Login do painel do Hermes                                                        |
| `COMPOSE_PROFILES`                                                      | `logs` no Linux; vazio no macOS e no Windows (a coleta de logs só roda no Linux) |

### Telegram

1. Crie o bot com o [@BotFather](https://t.me/BotFather) e coloque o token em `TELEGRAM_BOT_TOKEN`.
2. Abra o seu bot no Telegram, toque em **Iniciar** e mande uma mensagem. Sem o Hermes rodando, o bot não responde, mas a mensagem chega.
3. Com o Hermes parado, consulte o ID do chat na pasta de instalação:

   ```bash
   curl -s "https://api.telegram.org/bot$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)/getUpdates" | python3 -m json.tool | grep -A3 '"chat"'
   ```

4. Copie o `"id"` para `TELEGRAM_HOME_CHANNEL`. Em conversa privada, ele também é o seu ID em `TELEGRAM_ALLOWED_USERS`. Em grupo, o ID é negativo.

## Build e gravação do firmware

### Hardware

- 1 ESP32-S3 com 16 MB de flash e 8 MB de PSRAM (N16R8);
- 4 microfones I2S INMP441;
- 4 motores de vibração, cada um acionado por um MOSFET;
- cabo USB e rede Wi-Fi de **2,4 GHz**, a mesma do computador ou com rota até ele.

### Ligações

Alimente os microfones com **3,3 V** e GND. Eles compartilham os sinais de clock, e o pino L/R define o canal de cada um:

| Posição  | SCK    | WS     | SD     | L/R   | Motor (via MOSFET) |
| -------- | ------ | ------ | ------ | ----- | ------------------ |
| Frente   | GPIO 4 | GPIO 5 | GPIO 6 | GND   | GPIO 18            |
| Trás     | GPIO 4 | GPIO 5 | GPIO 6 | 3,3 V | GPIO 16            |
| Direita  | GPIO 4 | GPIO 5 | GPIO 7 | GND   | GPIO 17            |
| Esquerda | GPIO 4 | GPIO 5 | GPIO 7 | 3,3 V | GPIO 15            |

Os pinos ficam em `firmware/platformio.ini`. O firmware assume os microfones a 9 cm do centro (`MIC_RADIUS_M`). Ajuste esse valor se o seu arranjo for diferente, porque ele entra no cálculo da direção.

### Ambientes de build

| Ambiente        | Quando usar                                                                                    |
| --------------- | ---------------------------------------------------------------------------------------------- |
| `esp32s3`       | Testar a conexão. O sensor conecta e informa o estado, mas não classifica                      |
| `esp32s3_model` | Uso real, com a biblioteca do Edge Impulse em `firmware/lib/ei-model/`                         |
| `esp32s3_debug` | Testar Wi-Fi e MQTT com detecções simuladas, que [não chegam ao Grafana](#detecções-simuladas) |

### Compile e grave

1. Instale o [PlatformIO](https://platformio.org/install/cli).

2. Libere o MQTT na rede. Se você respondeu "sim" à pergunta do sensor no instalador, pule este passo. Caso contrário, coloque o IP do computador em `MQTT_BIND`, no `.env`, e aplique:

   ```bash
   docker compose up -d mosquitto
   ```

   Use o IP real da rede, nunca `0.0.0.0`. No Windows, libere também a porta **1883** no Firewall.

3. Prepare as credenciais. Se o instalador já gerou o `firmware/.env`, pule este passo.

   ```bash
   cd firmware
   cp .env.example .env
   ```

   Preencha `WIFI_SSID`, `WIFI_PASS`, `MQTT_HOST` (o IP do computador) e `MQTT_PASS`. Você não cria essa senha: a stack a gera na primeira subida. Para vê-la, rode na pasta de instalação:

   ```bash
   docker compose exec mosquitto cat /run/secrets/mqtt_device/value
   ```

4. Conecte a placa pela USB e, na pasta `firmware/`, compile, grave e acompanhe o log:

   ```bash
   pio run -e esp32s3              # só compila
   pio run -e esp32s3 -t upload    # compila e grava
   pio device monitor              # mostra o log
   ```

   O build falha de propósito se alguma credencial estiver vazia.

5. Confira o log:

   ```text
   [WiFi] IP: 192.168.x.x  RSSI: -55 dBm
   [MQTT] Conectado.
   [EI] Sem modelo em lib/ei-model/: janelas descartadas (use esp32s3_debug para o mock)
   ```

   A última linha é esperada enquanto não houver modelo: o sensor já aparece como conectado, mas ainda não envia detecções.

### Usar um modelo real

O ELEX20 usa uma biblioteca exportada do [Edge Impulse](https://edgeimpulse.com/). Treine ou escolha um projeto com janela de áudio de 975 ms a 16 kHz.

Num clone do repositório, o instalador faz os passos 2 e 3: na etapa do dispositivo, ligue **Add an Edge Impulse sound model to the firmware** e informe o `.zip` exportado (ou use `--ei-model ARQUIVO`). Ele recusa modelos que não sejam de 16 kHz, troca o modelo anterior e avisa sobre rótulos que o ELEX20 não conhece. Para fazer à mão:

1. No Edge Impulse, exporte em **Deployment → Arduino library**.
2. Extraia o `.zip` em `firmware/lib/ei-model/`, pasta que não é versionada.
3. Se a pasta extraída tiver outro nome que não `ELEX20_Categorias_inferencing`:
   - em `firmware/platformio.ini`, troque o valor de `EI_MODEL_HEADER` pelo header gerado e o nome da pasta nas linhas do ambiente `esp32s3_model`;
   - em `firmware/src/main.cpp`, troque o include desativado no início do arquivo.
4. Grave:

   ```bash
   pio run -e esp32s3_model -t upload
   ```

5. Confirme que a mensagem `[EI] Sem modelo` sumiu do log.

> [!WARNING]
> Sem o include desativado, ou mudando só o header no ambiente `esp32s3`, o build passa, mas **sem** o modelo.

### Rótulos e urgência

Os rótulos publicados e gravados são em inglês. Urgência e alertas dependem deles. A tabela conhece estes:

| Urgência | Rótulos                                                             |
| -------- | ------------------------------------------------------------------- |
| 3 (alta) | `siren`, `horn`, `alarm`, `gunshot_explosion`, `scream`             |
| 2        | `impact`, `train`                                                   |
| 1        | `power_tool`, `vehicle`                                             |
| 0        | `aircraft`, `animal`, `weather`, `speech_crowd`, `music`, `silence` |

Um rótulo fora da tabela é gravado sem urgência e não gera alerta, direção nem vibração.

Modelos treinados antes da troca devolvem os nomes em português (`sirene`, `tiro_explosao`...). O firmware os traduz antes de publicar, e a subida do banco traduz os eventos já gravados. O nome antigo de cada categoria está em `rotulo_legado`.

Para usar outros nomes, altere `classes/sound_classes.json`, as tabelas em `firmware/lib/elex_core/settings.cpp` e `sound_classes` em `timescaledb/db-init.sql`. A cada subida o banco volta a ter exatamente a lista e as urgências do seed.

### Detecções simuladas

O ambiente `esp32s3_debug` envia detecções marcadas com `mock`, e **a ingestão as descarta de propósito**: elas nunca aparecem no Grafana. Para vê-las, observe o tráfego do broker:

```bash
docker compose exec mosquitto sh -c 'mosquitto_sub -h localhost -u n8n -P "$(cat /run/secrets/mqtt_n8n/value)" -t "sound/#" -v'
```

## Uso

### Sensor

Com o modelo gravado, quando o sensor reconhece um som com urgência acima de 0, ele estima a direção e aciona o motor daquele lado (frente, direita, trás ou esquerda), ou os dois motores vizinhos nas diagonais. A intensidade cresce com a urgência. Os ajustes de sensibilidade e vibração estão em [Hermes](#hermes).

A cada 5 s o sensor publica em `sound/status/<DEVICE_ID>` um heartbeat com o próprio desempenho, gravado em `device_status` (a view `device_last_status` traz o último de cada sensor):

| Campo                            | O que mede                                                                    |
| -------------------------------- | ----------------------------------------------------------------------------- |
| `win_ms_avg`, `win_ms_max`       | Tempo para processar cada janela de áudio (média e pior caso nos últimos 5 s) |
| `dsp_ms`, `nn_ms`                | Extração de features e classificação do Edge Impulse (média, só com modelo)   |
| `heap`, `heap_min`               | Memória livre agora e a menor desde o boot                                    |
| `psram_free`                     | PSRAM livre                                                                   |
| `stack_min`                      | Menor folga de pilha entre as tarefas, em bytes (`stack_task` diz qual)       |
| `dropped`                        | Janelas descartadas porque a anterior ainda estava sendo classificada         |
| `offline_dropped`                | Detecções descartadas sem rede                                                |
| `wifi_connects`, `mqtt_connects` | Conexões desde o boot: crescer rápido indica rede instável                    |
| `temp_c`                         | Temperatura do chip                                                           |

A janela tem 975 ms: com `win_ms_max` acima disso, a placa não acompanha o áudio e `dropped` sobe.

### Grafana

1. Acesse <http://localhost:3000>.
2. Entre com `admin` / `password` (ou `GRAFANA_ADMIN_USER` e `GRAFANA_ADMIN_PASSWORD` do `.env`) e troque a senha.
3. Abra **Dashboards → Sons Urbanos — ELEX20**.

### n8n

O n8n pede a criação de uma conta **apenas na primeira abertura**:

1. Acesse <http://localhost:5678>.
2. Preencha nome, e-mail e senha (qualquer valor: a conta é local).
3. Clique em **Get started**.

Os workflows **ELEX20 - Ingestão MQTT** e **ELEX20 - Comando ao dispositivo** já ficam importados e ativos pelo instalador. Você não precisa mexer neles para usar o sistema.

### Hermes

1. Acesse <http://localhost:9119> e entre com `admin` / `password` (ou `HERMES_DASHBOARD_USER` e `HERMES_DASHBOARD_PASS` do `.env`).
2. Fale com o bot no Telegram ou no Discord. Só os IDs de `TELEGRAM_ALLOWED_USERS` e `DISCORD_ALLOWED_USERS` são atendidos.
3. Os alertas de urgência alta chegam ao chat de `TELEGRAM_HOME_CHANNEL`.

O Hermes consulta o banco só para leitura e nunca fala direto com o sensor: os comandos passam pelo n8n, que valida chave e faixa.

| Pergunte sobre          | Ferramenta usada                       |
| ----------------------- | -------------------------------------- |
| Sensores conectados     | `sensores_status`                      |
| Últimos sons            | `eventos_recentes`                     |
| Resumo por período      | `resumo_sons`                          |
| De onde vêm os sons     | `direcao_predominante`                 |
| Urgência de cada rótulo | `classes_urgencia`                     |
| Ajustes do sensor       | `enviar_comando`, com as chaves abaixo |

| Chave           | Valor       | O que ajusta                                                             |
| --------------- | ----------- | ------------------------------------------------------------------------ |
| `threshold`     | 0,30 a 0,99 | Confiança mínima para uma detecção                                       |
| `doa_enabled`   | 0 ou 1      | Estimativa de direção                                                    |
| `motor_enabled` | 0 ou 1      | Vibração                                                                 |
| `motor_max_ms`  | 100 a 2000  | Duração máxima da vibração                                               |
| `port1_skew`    | -8 a 8      | Atraso, em amostras, do segundo par de microfones em relação ao primeiro |

Sem chave do OpenRouter, o Hermes usa o modelo local `qwen2.5:3b`. As alternativas estão comentadas em `hermes/config.yaml`.

## Manutenção

Rode os comandos desta seção na pasta de instalação.

### Parar e reiniciar

```bash
docker compose stop              # pausa tudo (dados preservados)
docker compose start             # retoma
docker compose restart grafana   # reinicia um serviço
docker compose down              # remove os containers (os dados nos volumes ficam)
```

> [!CAUTION]
> Os dados ficam em volumes do Docker e não se perdem ao parar ou remover containers. Só `docker compose down -v` apaga os volumes. **Nunca use esse comando** sem backup: ele apaga o histórico e as senhas internas, e o sensor precisaria ser regravado.

### Atualizar

```bash
docker compose pull
docker compose up -d
```

### Desinstalar

Pela tela: rode o instalador e, na primeira tela, escolha **Uninstall ELEX20…**. Ou vá direto:

```bash
./install.sh --uninstall
```

Sem nenhuma outra escolha, só os containers saem, e os dados continuam nos volumes do Docker. O resto é opcional:

| Opção na tela                 | Flag              | O que apaga                                                |
| ----------------------------- | ----------------- | ---------------------------------------------------------- |
| Delete all data               | `--delete-data`   | Histórico, painéis, conta do n8n, dados do Hermes e senhas |
| Delete downloaded images      | `--delete-images` | Imagens do Docker, liberando vários GB                     |
| Delete installed files / .env | `--delete-files`  | Arquivos que o instalador criou e o `.env`                 |

A tela pede que você digite `delete` antes de apagar dados ou arquivos. Em um clone, o repositório fica: só `.env` e `firmware/.env` saem. Em outra pasta, só somem os arquivos criados pelo instalador; o que for seu continua lá. Se os dados ficarem, o `.env` também fica, porque a senha do banco está nele.

Sem interface, as flags valem como confirmação. Por exemplo, para remover tudo:

```bash
./install.sh --uninstall -y --delete-data --delete-images --delete-files
```

> [!CAUTION]
> Dados apagados não podem ser recuperados. Depois disso, o sensor precisa ser gravado de novo, porque as senhas internas mudam.

### Trocar senhas

Os logins do Grafana e do Hermes ficam no `.env`. Edite e reinicie os serviços afetados:

```bash
docker compose up -d grafana hermes-agent timescaledb
```

> [!NOTE]
> `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` e a conta do n8n só valem na primeira criação dos dados. Mudar depois exige trocar a senha dentro do próprio serviço.
>
> Os segredos internos (banco, MQTT e tokens entre n8n e Hermes) são gerados uma vez e ficam em volumes do Docker. Para fixar um valor, defina a variável no `.env` (por exemplo, `MQTT_DEVICE_PASS=...`): ela sobrescreve o volume.

## Solução de problemas

<details>
<summary><strong>O instalador diz que o Docker não está rodando</strong></summary>

Abra o Docker Desktop (Windows e macOS) e espere o ícone ficar verde. No Linux:

```bash
sudo systemctl start docker
```

Se aparecer "permission denied", rode `sudo usermod -aG docker $USER` e entre de novo na sessão.

</details>

<details>
<summary><strong>O sensor não conecta ao MQTT</strong></summary>

- Confira se o log do monitor mostra `[WiFi] IP:`. O ESP32 só usa Wi-Fi de **2,4 GHz**.
- A falta de rede não reinicia o sensor: ele tenta de novo sozinho, a cada 15 s a 2 min no Wi-Fi e a cada 2 s a 1 min no MQTT.
- Confira se `MQTT_BIND` no `.env` é o IP atual do computador e igual a `MQTT_HOST` no `firmware/.env`. O IP pode mudar: reserve-o no roteador.
- Depois de mudar `MQTT_BIND`, rode `docker compose up -d mosquitto`. Depois de mudar `firmware/.env`, grave o firmware de novo.
- `rc=4` ou `rc=5` no log indicam senha ou usuário errado. No Windows, libere a porta **1883** no Firewall.

</details>

<details>
<summary><strong>O sensor conecta, mas nada aparece no Grafana</strong></summary>

- `[EI] Sem modelo` no log: o firmware foi gravado sem modelo; veja [Usar um modelo real](#usar-um-modelo-real).
- Firmware `esp32s3_debug`: as leituras simuladas são descartadas de propósito.
- Workflows inativos: abra o n8n e confira, ou rode o instalador de novo.
- Workflow ativo, mas sem execuções: se o Mosquitto estava fora do ar quando o n8n subiu, o gatilho MQTT falha (`EAI_AGAIN mosquitto` no log do n8n) e não tenta de novo. Rode o instalador de novo ou destrave à mão:

  ```bash
  docker compose exec n8n n8n unpublish:workflow --id=elex-ingestao-mqtt
  docker compose exec n8n n8n publish:workflow --id=elex-ingestao-mqtt
  docker compose restart n8n
  ```

</details>

<details>
<summary><strong>Os alertas não chegam</strong></summary>

Confira `TELEGRAM_HOME_CHANNEL` no `.env`, se os workflows do n8n estão ativos e se o rótulo tem urgência 3 na tabela. Rótulos fora da tabela não geram alerta.

</details>

<details>
<summary><strong><code>docker compose up -d</code> falha com "port already in use"</strong></summary>

Outra aplicação está usando a mesma porta. Identifique qual, trocando `3000` pelo número da porta:

```bash
sudo ss -tlnp | grep 3000     # Linux
netstat -ano | findstr :3000  # Windows
```

</details>

<details>
<summary><strong>Um container aparece como "Restarting"</strong></summary>

```bash
docker logs <nome-do-container> --tail 30
```

</details>

<details>
<summary><strong>O n8n mostra erro de banco de dados</strong></summary>

O n8n usa um banco dedicado (`n8n`) no TimescaleDB, criado pelo serviço `db-init` a cada `docker compose up`. Veja o que ele registrou:

```bash
docker compose logs db-init
```

</details>

<details>
<summary><strong>O Hermes continua reiniciando</strong></summary>

```bash
docker logs hermes-agent --tail 20
```

Se aparecer `The token ... was rejected`, o token do Telegram ou do Discord está inválido. Corrija no `.env` e rode:

```bash
docker compose restart hermes-agent
```

</details>

## Referência

### Verificar o download

Cada release traz um `.sigstore.json` por arquivo e os hashes: um `.sha256` por arquivo na v1.0.0 e um `SHA256SUMS` único nas versões seguintes. Com o hash na mesma pasta do download, rode o comando da sua versão:

```bash
# v1.0.0
sha256sum --check elex-instalador-linux-x86_64.sha256

# versões seguintes
sha256sum --check --ignore-missing SHA256SUMS
```

Para conferir a origem, use o [cosign](https://docs.sigstore.dev/cosign/system_config/installation/):

```bash
cosign verify-blob \
  --bundle elex-installer-linux-x86_64.sigstore.json \
  --certificate-identity "https://github.com/Chan-28/ELEX20/.github/workflows/release.yml@refs/tags/<versão>" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  elex-installer-linux-x86_64
```

### O que o instalador faz

1. Confere se o Docker está instalado e ligado.
2. Copia os arquivos da stack para a pasta de instalação.
3. Cria o `.env` com os padrões (nunca troca um `.env` que já existe). As senhas internas são geradas pela própria stack na primeira subida (serviço `secrets-init`) e ficam em volumes do Docker.
4. Executa `docker compose up -d` e espera o n8n e o Grafana responderem.
5. Baixa o modelo local do Ollama (opcional).
6. Cria no n8n as credenciais do Postgres e do MQTT, importa os workflows e os ativa.
7. Gera o `firmware/.env` (opcional, se houver a pasta `firmware/`).

### Compatibilidade

| Recurso                         | Linux | macOS             | Windows                                                           |
| ------------------------------- | ----- | ----------------- | ----------------------------------------------------------------- |
| Instalador (executável)         | ✅    | ✅                | ✅                                                                |
| Docker Compose (stack completa) | ✅    | ✅ Docker Desktop | ✅ Docker Desktop + WSL2                                          |
| Coleta de logs (Alloy)          | ✅    | ➖ desligada      | ➖ desligada (ligue com `COMPOSE_PROFILES=logs` se quiser testar) |
| Python / uv / firmware          | ✅    | ✅                | ✅                                                                |
| direnv (`.envrc`)               | ✅    | ✅                | ⚠️ não disponível — use `set DOCKER_HOST=...` no WSL2 ou ignore   |
| Commits com Husky               | ✅    | ✅                | ✅ Git Bash ou WSL2                                               |

A coleta de logs (Alloy) lê caminhos do Docker que só existem no Linux; por isso o instalador a liga apenas lá. O restante da stack é igual nos três sistemas.

## Desenvolvimento

Para mexer no código, você precisa de Python 3.11+, [uv](https://docs.astral.sh/uv/), Git e, para o firmware, [PlatformIO](https://platformio.org/). A estrutura do repositório, os comandos e as convenções estão em [AGENTS.md](../AGENTS.md).

Para testar o hardware na bancada (qualidade dos microfones, ordem dos canais, gravação em WAV, motores), simular sensores no MQTT ou avaliar a saúde dos sensores pelos heartbeats, veja [debug/README.md](../debug/README.md).

Instale o uv e as dependências:

```bash
# Linux e macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
uv sync --group dev --frozen
```

Rode os testes e o lint:

```bash
uv run pytest            # testes
uv run ruff check .      # lint
```

Teste e compile o firmware, a partir de `firmware/`, com `firmware/.env` preenchido:

```bash
pio test -e native       # testes sem hardware (direção do som, comandos)
pio run -e esp32s3       # build
```

Use `uv add` e `uv remove` para mudar dependências; eles atualizam o `uv.lock`, que nunca deve ser editado à mão.

Para gerar o executável do instalador localmente:

```bash
uvx --from "pyinstaller>=6.11" --with "textual==8.2.8" pyinstaller installer/elex_installer.spec
```

## Saúde do código

[![CodeScene Average Code Health](https://codescene.io/projects/83420/status-badges/average-code-health)](https://codescene.io/projects/83420)
[![CodeScene Hotspot Code Health](https://codescene.io/projects/83420/status-badges/hotspot-code-health)](https://codescene.io/projects/83420)
[![CodeScene System Mastery](https://codescene.io/projects/83420/status-badges/system-mastery)](https://codescene.io/projects/83420)
[![CodeScene general](https://codescene.io/images/analyzed-by-codescene-badge.svg)](https://codescene.io/projects/83420)

## Star History

<!-- markdownlint-disable MD033 -->
<a href="https://www.star-history.com/?repos=Chan-28%2FELEX20.git&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=Chan-28/ELEX20.git&type=date&theme=dark&legend=top-left&sealed_token=NR-lIw07qnsnl0b8_AmOpAHvwOIoG9rXi3WJ0sUY1kw50Z4gu6blbDXnK9FLCnocezkv7Td2qNNOr2Mde_2teQCzJBz7wTwnrF3v38U8ULQuh9HL2hfM9U6ajRIjAhs89t8RKPBVoSfMFzICESpxk027ugaYM8pYsH-SyTOQJ-6Oyf6eapu62_8XP09c" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=Chan-28/ELEX20.git&type=date&legend=top-left&sealed_token=NR-lIw07qnsnl0b8_AmOpAHvwOIoG9rXi3WJ0sUY1kw50Z4gu6blbDXnK9FLCnocezkv7Td2qNNOr2Mde_2teQCzJBz7wTwnrF3v38U8ULQuh9HL2hfM9U6ajRIjAhs89t8RKPBVoSfMFzICESpxk027ugaYM8pYsH-SyTOQJ-6Oyf6eapu62_8XP09c" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=Chan-28/ELEX20.git&type=date&legend=top-left&sealed_token=NR-lIw07qnsnl0b8_AmOpAHvwOIoG9rXi3WJ0sUY1kw50Z4gu6blbDXnK9FLCnocezkv7Td2qNNOr2Mde_2teQCzJBz7wTwnrF3v38U8ULQuh9HL2hfM9U6ajRIjAhs89t8RKPBVoSfMFzICESpxk027ugaYM8pYsH-SyTOQJ-6Oyf6eapu62_8XP09c" />
 </picture>
</a>
<!-- markdownlint-enable MD033 -->
