# ELEX20 - Análise e Reconhecimento de Sons Locais

O ELEX20 é um wearable de percepção sonora. Quatro microfones captam o ambiente, um ESP32-S3 reconhece no próprio aparelho sons urbanos, como sirenes, buzinas e tiros, e estima de que direção eles vêm. Quatro motores vibram para indicar a direção, com mais força quanto maior a urgência do som.

```text
4 microfones INMP441 → ESP32-S3 (classificação + direção) → motor de vibração
```

Essa é a parte principal do projeto. O monitoramento é um complemento: o sensor envia as detecções a um servidor no seu computador, onde ficam o histórico e os alertas.

```text
Sensor → [MQTT / Wi-Fi] → Mosquitto → n8n → TimescaleDB → Grafana (painéis)
                                                        → Hermes (chat, alertas e comandos)
```

## Antes de começar

| Parte                      | O que faz                                             | O que você precisa                                                                                |
| -------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Sensor** (o wearable)    | Capta o som, classifica e vibra indicando a direção   | O hardware de [Monte o sensor](#1-monte-o-sensor), o repositório clonado e um modelo Edge Impulse |
| **Servidor** (complemento) | Guarda o histórico, mostra os painéis e envia alertas | Windows, macOS ou Linux com Docker e alguns GB livres para as imagens                             |

> **Importante:**
>
> - O modelo que reconhece os sons **não vem neste repositório**. Sem ele, o sensor conecta e informa o próprio estado, mas não classifica nem vibra. Veja [Usar um modelo real](#usar-um-modelo-real).

> **Sem rede:** o firmware foi feito para seguir classificando, estimando a direção e vibrando sem Wi-Fi ou Mosquitto, e para reconectar sozinho, com intervalos crescentes. Só o histórico, os alertas e os comandos dependem da rede. As detecções feitas sem conexão são descartadas, não reenviadas, e os comandos enviados nesse período se perdem. O campo `offline_dropped`, no status do sensor, conta as detecções que não chegaram ao servidor. Esse comportamento ainda não foi validado em hardware.

**Roteiro:**

1. [Monte o sensor](#1-monte-o-sensor).
2. [Suba o servidor](#2-suba-o-servidor).
3. [Grave o firmware](#3-grave-o-firmware).
4. [Use o sistema](#4-use-o-sistema).

---

## 1. Monte o sensor

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

Os pinos ficam em `firmware/platformio.ini`. O firmware assume os microfones a 9 cm do centro (`MIC_RADIUS_M`): ajuste esse valor se o seu arranjo for diferente, porque ele entra no cálculo da direção.

---

## 2. Suba o servidor

Você não precisa saber programar: o instalador sobe todos os serviços e configura o n8n sozinho, e as senhas internas são geradas automaticamente.

### Instale o Docker

O Docker é o único programa que precisa estar instalado antes.

| Sistema                        | Como instalar                                                                                                                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows**                    | [Docker Desktop](https://www.docker.com/products/docker-desktop/), deixando marcada a opção **WSL 2**. Reinicie se pedir.                                                 |
| **macOS**                      | [Docker Desktop](https://www.docker.com/products/docker-desktop/) (ou `brew install --cask docker`).                                                                      |
| **Ubuntu, Debian, Linux Mint** | `curl -fsSL https://get.docker.com \| sudo sh` (guia: [Ubuntu](https://docs.docker.com/engine/install/ubuntu/), [Debian](https://docs.docker.com/engine/install/debian/)) |
| **Fedora, RHEL, Rocky**        | `curl -fsSL https://get.docker.com \| sudo sh` (guia: [Fedora](https://docs.docker.com/engine/install/fedora/))                                                           |
| **Arch, Manjaro**              | `sudo pacman -S docker docker-compose`                                                                                                                                    |
| **openSUSE**                   | `sudo zypper install docker docker-compose`                                                                                                                               |

No **Linux**, depois de instalar: `sudo systemctl enable --now docker` e `sudo usermod -aG docker $USER` (saia da sessão e entre de novo). No **Windows e macOS**, abra o Docker Desktop e espere ele iniciar.

Confira com `docker compose version`. Se faltar algo, o instalador também explica o que fazer.

### Baixe o instalador

Na página de [Releases](https://github.com/Chan-28/ELEX20/releases), baixe o arquivo do seu sistema:

| Sistema                             | Arquivo                             |
| ----------------------------------- | ----------------------------------- |
| Windows                             | `elex-installer-windows-x86_64.exe` |
| macOS (Apple Silicon: M1, M2, ...)  | `elex-installer-macos-arm64`        |
| macOS (Intel)                       | `elex-installer-macos-x86_64`       |
| Linux (PC comum)                    | `elex-installer-linux-x86_64`       |
| Linux (ARM: Raspberry Pi 4/5, etc.) | `elex-installer-linux-arm64`        |

A partir da próxima release, os arquivos usam estes nomes; a v1.0.0 ainda traz `elex-instalador-*` no lugar de `elex-installer-*`. O mesmo arquivo serve para qualquer distribuição Linux. Para saber se o seu Linux é x86_64 ou ARM, rode `uname -m`.

> **Vai gravar o sensor?** Clone o repositório e rode `./install.sh` (Linux/macOS) ou `install.bat` (Windows), com o Python 3 do sistema, em vez do executável. O executável não traz a pasta `firmware/`. Clonado, o repositório vira a própria pasta de instalação, e o instalador pode gerar o `firmware/.env` para você.

### Execute

- **Windows:** dê dois cliques no arquivo. Se o SmartScreen avisar "O Windows protegeu seu computador", clique em **Mais informações** e depois em **Executar assim mesmo** (o executável não tem assinatura paga da Microsoft; veja [como verificar o download](#verificar-o-download-opcional)).
- **macOS:** abra o Terminal na pasta do download e rode (troque `arm64` por `x86_64` em Macs Intel):

  ```bash
  chmod +x elex-installer-macos-arm64
  xattr -d com.apple.quarantine elex-installer-macos-arm64
  ./elex-installer-macos-arm64
  ```

- **Linux:**

  ```bash
  chmod +x elex-installer-linux-x86_64
  ./elex-installer-linux-x86_64
  ```

### Responda às perguntas

Tudo é opcional, e você pode apertar Enter para pular:

- se vai ligar o sensor ESP32 na sua rede (ele descobre o IP do computador);
- chave do OpenRouter (IA na nuvem; sem ela o Hermes usa o modelo local);
- bot do Telegram e/ou do Discord (token, o seu ID e o chat que recebe os alertas);
- se quer baixar o modelo local de IA (cerca de 2 GB);
- se quer gerar o `firmware/.env`, quando há a pasta `firmware/`.

O executável instala em `~/ELEX20` (no Windows, `C:\Users\<você>\ELEX20`). Ao final, o instalador mostra os endereços e os logins. Na primeira vez, o Docker baixa alguns GB de imagens, o que pode levar vários minutos.

**Guarde o arquivo `.env` da pasta de instalação e não o compartilhe.**

Pode rodar o instalador de novo a qualquer momento: ele só completa o que falta. Opções de linha de comando: `--dir PASTA`, `--non-interactive`, `--skip-model`, `--set KEY=VALUE` e `--dry-run` (só mostra os comandos do Docker).

### Abra os serviços

| Serviço                              | Endereço                    | Usuário             | Senha                            |
| ------------------------------------ | --------------------------- | ------------------- | -------------------------------- |
| **Grafana** — painéis e métricas     | <http://localhost:3000>     | `admin`             | `password` (placeholder, troque) |
| **n8n** — automação de fluxos        | <http://localhost:5678>     | criado no 1º acesso | —                                |
| **Hermes Dashboard** — assistente IA | <http://localhost:9119>     | `admin`             | `password` (placeholder, troque) |
| **Mosquitto** — broker MQTT (sensor) | `mqtt://localhost:1883`     | `device` / `n8n`    | gerada sozinha                   |
| **TimescaleDB** — banco de dados     | interno (sem porta exposta) | `postgres`          | `POSTGRES_PASSWORD` (no `.env`)  |

Os logins `admin` / `password` servem só para uso na sua máquina: [troque-os](#trocar-senhas) antes de qualquer outro uso.

### Teste sem sensor

Para confirmar que o caminho inteiro funciona antes de gravar o firmware, publique uma detecção de teste. Rode na pasta de instalação, em um terminal Linux, macOS, Git Bash ou WSL2:

```bash
docker compose exec mosquitto sh -c 'mosquitto_pub -h localhost -u device -P "$(cat /run/secrets/mqtt_device/value)" -t sound/inference/teste-01 -m "{\"label\":\"siren\",\"confidence\":0.9}"'
```

Depois abra o painel **Sons Urbanos — ELEX20** no Grafana: um evento `siren` do dispositivo `teste-01` deve aparecer. Como `siren` tem urgência 3, o alerta também segue para o chat configurado no Hermes. Esse evento de teste fica no histórico.

Se nada aparecer, veja [Solução de problemas](#solução-de-problemas).

---

## 3. Grave o firmware

### Libere o MQTT na rede

Por segurança, o Mosquitto só aceita conexões do próprio computador. Se você respondeu "sim" à pergunta do sensor no instalador, isso já está feito. Caso contrário, coloque o IP do computador na rede em `MQTT_BIND`, no `.env`, e aplique:

```bash
docker compose up -d mosquitto
```

Use o IP real da rede, nunca `0.0.0.0`. No Windows, libere também a porta **1883** no Firewall.

### Grave o firmware

Instale o [PlatformIO](https://platformio.org/install/cli) e, na pasta do repositório clonado, prepare as credenciais. Se o instalador já gerou o `firmware/.env`, pule a cópia:

```bash
cd firmware
cp .env.example .env
```

Preencha `WIFI_SSID`, `WIFI_PASS`, `MQTT_HOST` (o IP do computador) e `MQTT_PASS`. Essa senha é gerada pela stack; para vê-la, rode na pasta de instalação:

```bash
docker compose exec mosquitto cat /run/secrets/mqtt_device/value
```

Conecte a placa pela USB, grave e acompanhe o log:

```bash
pio run -e esp32s3 -t upload && pio device monitor
```

O build falha de propósito se alguma credencial estiver vazia. Com tudo certo, o log mostra:

```text
[WiFi] IP: 192.168.x.x  RSSI: -55 dBm
[MQTT] Conectado.
[EI] Sem modelo em lib/ei-model/: janelas descartadas (use esp32s3_debug para o mock)
```

A última linha é esperada enquanto não houver modelo: o sensor já aparece como conectado, mas ainda não envia detecções.

### Usar um modelo real

O ELEX20 usa uma biblioteca exportada do [Edge Impulse](https://edgeimpulse.com/). Treine ou escolha um projeto com janela de áudio de 975 ms a 16 kHz e:

1. No Edge Impulse, exporte em **Deployment → Arduino library**.
2. Extraia o `.zip` em `firmware/lib/ei-model/`, pasta que não é versionada.
3. Em `firmware/platformio.ini`, troque `EI_MODEL_HEADER` pelo header gerado (por exemplo, `meu_projeto_inferencing.h`).
4. Acrescente um ambiente que inclua a biblioteca, trocando `NOME` pela pasta extraída:

   ```ini
   [env:esp32s3_model]
   extends  = env:esp32s3
   lib_deps =
       ${env:esp32s3.lib_deps}
       symlink://lib/ei-model/NOME
   build_flags =
       ${env:esp32s3.build_flags}
       -Ilib/ei-model/NOME/src/edge-impulse-sdk/porting/espressif/esp-dsp/modules/fft/include
       -I${platformio.packages_dir}/framework-arduinoespressif32-esp32s3-libs/include/xtensa/esp32s3/include
   ```

5. Grave com `pio run -e esp32s3_model -t upload` e confirme que a mensagem `[EI] Sem modelo` sumiu. Só mudar o header no ambiente `esp32s3` compila com sucesso, mas **sem** o modelo.

**Os nomes das classes precisam coincidir.** Urgência e alertas dependem do rótulo, e a tabela inicial conhece só estes:

| Urgência | Rótulos                                             |
| -------- | --------------------------------------------------- |
| 3 (alta) | `siren`, `car_horn`, `gun_shot`                     |
| 2        | `dog_bark`, `drilling`, `jackhammer`                |
| 1        | `engine_idling`, `children_playing`, `street_music` |
| 0        | `air_conditioner`                                   |

Um rótulo fora da tabela é gravado sem urgência e não gera alerta, direção nem vibração. Para usar outros nomes, altere `sound_classes` no banco com `UPDATE`/`INSERT` e a mesma tabela em `firmware/lib/elex_core/settings.cpp`.

> O ambiente `esp32s3_debug` envia detecções simuladas para testar o Wi-Fi e o MQTT sem modelo. Elas são marcadas com `mock` e **a ingestão as descarta de propósito**: nunca aparecem no Grafana. Para vê-las, observe o tráfego do broker:
>
> ```bash
> docker compose exec mosquitto sh -c 'mosquitto_sub -h localhost -u n8n -P "$(cat /run/secrets/mqtt_n8n/value)" -t "sound/#" -v'
> ```

---

## 4. Use o sistema

### Sensor — feedback motor

Com o modelo gravado, quando o sensor reconhece um som com urgência acima de 0, ele estima a direção e aciona o motor daquele lado (frente, direita, trás ou esquerda), ou os dois motores vizinhos nas diagonais. A intensidade cresce com a urgência. Os ajustes de sensibilidade e vibração estão na tabela de chaves do Hermes, mais abaixo.

### Grafana — painéis

1. Acesse <http://localhost:3000>.
2. Entre com `admin` / `password` (ou `GRAFANA_ADMIN_USER` e `GRAFANA_ADMIN_PASSWORD` do `.env`) e troque a senha.
3. Abra **Dashboards → Sons Urbanos — ELEX20**.

### n8n — automação

O n8n pede a criação de uma conta **apenas na primeira abertura**:

1. Acesse <http://localhost:5678>.
2. Preencha nome, e-mail e senha (qualquer valor: a conta é local).
3. Clique em **Get started**.

Os workflows **ELEX20 - Ingestão MQTT** e **ELEX20 - Comando ao dispositivo** já ficam importados e ativos pelo instalador. Você não precisa mexer neles para usar o sistema.

### Hermes — assistente de IA

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

Sem chave do OpenRouter, o Hermes usa o modelo local `qwen2.5:3b`; as alternativas estão comentadas em `hermes/config.yaml`.

---

## Parar, reiniciar e atualizar

Rode estes comandos na pasta de instalação:

```bash
docker compose stop      # pausa tudo (dados preservados)
docker compose start     # retoma
docker compose restart grafana   # reinicia um serviço
docker compose down      # remove os containers (os dados nos volumes ficam)
```

> **Os dados não são perdidos** ao parar ou remover containers: ficam em volumes do Docker. Só `docker compose down -v` apaga os volumes. **Nunca use esse comando** sem backup: ele apaga o histórico e as senhas internas, e o sensor precisaria ser regravado.

Para atualizar as imagens: `docker compose pull` e depois `docker compose up -d`.

### Trocar senhas

Os logins do Grafana e do Hermes ficam no `.env`. Edite e reinicie os serviços afetados:

```bash
docker compose up -d grafana hermes-agent timescaledb
```

> `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` e a conta do n8n só valem na primeira criação dos dados; mudar depois exige trocar a senha dentro do próprio serviço.
>
> Os segredos internos (banco, MQTT e tokens entre n8n e Hermes) são gerados uma vez e ficam em volumes do Docker. Para fixar um valor, defina a variável no `.env` (por exemplo, `MQTT_DEVICE_PASS=...`); ela sobrescreve o volume.

---

## Solução de problemas

### O instalador diz que o Docker não está rodando

Abra o Docker Desktop (Windows e macOS) e espere o ícone ficar verde. No Linux: `sudo systemctl start docker`. Se aparecer "permission denied", rode `sudo usermod -aG docker $USER` e entre de novo na sessão.

### O sensor não conecta ao MQTT

- Confira se o log do monitor mostra `[WiFi] IP:`. O ESP32 só usa Wi-Fi de **2,4 GHz**.
- A falta de rede não reinicia o sensor: ele tenta de novo sozinho, a cada 15 s a 2 min no Wi-Fi e a cada 2 s a 1 min no MQTT.
- Confira se `MQTT_BIND` no `.env` é o IP atual do computador e igual a `MQTT_HOST` no `firmware/.env`. O IP pode mudar: reserve-o no roteador.
- Depois de mudar `MQTT_BIND`, rode `docker compose up -d mosquitto`. Depois de mudar `firmware/.env`, grave o firmware de novo.
- `rc=4` ou `rc=5` no log indicam senha ou usuário errado. No Windows, libere a porta **1883** no Firewall.

### O sensor conecta, mas nada aparece no Grafana

- `[EI] Sem modelo` no log: o firmware foi gravado sem modelo; veja [Usar um modelo real](#usar-um-modelo-real).
- Firmware `esp32s3_debug`: as leituras simuladas são descartadas de propósito.
- Workflows inativos: abra o n8n e confira, ou rode o instalador de novo.

### Os alertas não chegam

Confira `TELEGRAM_HOME_CHANNEL` no `.env`, se os workflows do n8n estão ativos e se o rótulo tem urgência 3 na tabela. Rótulos fora da tabela não geram alerta.

### `docker compose up -d` falha com "port already in use"

Outra aplicação está usando a mesma porta. Identifique qual:

```bash
sudo ss -tlnp | grep 3000   # Linux; substitua pelo número da porta
```

No Windows: `netstat -ano | findstr :3000`.

### Um container aparece como "Restarting"

```bash
docker logs <nome-do-container> --tail 30
```

### n8n mostra erro de banco de dados

O n8n usa um banco dedicado (`n8n`) no TimescaleDB, criado pelo serviço `db-init` a cada `docker compose up`. Veja o que ele registrou: `docker compose logs db-init`.

### Hermes continua reiniciando

```bash
docker logs hermes-agent --tail 20
```

Se aparecer `The token ... was rejected`, o token do Telegram ou do Discord está inválido: corrija no `.env` e rode `docker compose restart hermes-agent`.

---

## Referência

### Verificar o download (opcional)

Cada release traz um `.sigstore.json` por arquivo e os hashes: um `.sha256` por arquivo na v1.0.0 e um `SHA256SUMS` único nas versões seguintes. Com o hash na mesma pasta do download, rode o comando que corresponde à sua versão:

```bash
sha256sum --check elex-instalador-linux-x86_64.sha256
```

```bash
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

### Compatibilidade de sistemas operacionais

| Recurso                         | Linux | macOS             | Windows                                                           |
| ------------------------------- | ----- | ----------------- | ----------------------------------------------------------------- |
| Instalador (executável)         | ✅    | ✅                | ✅                                                                |
| Docker Compose (stack completa) | ✅    | ✅ Docker Desktop | ✅ Docker Desktop + WSL2                                          |
| Coleta de logs (Alloy)          | ✅    | ➖ desligada      | ➖ desligada (ligue com `COMPOSE_PROFILES=logs` se quiser testar) |
| Python / uv / firmware          | ✅    | ✅                | ✅                                                                |
| direnv (`.envrc`)               | ✅    | ✅                | ⚠️ não disponível — use `set DOCKER_HOST=...` no WSL2 ou ignore   |
| Commits com Husky               | ✅    | ✅                | ✅ Git Bash ou WSL2                                               |

A coleta de logs (Alloy) lê caminhos do Docker que só existem no Linux; por isso o instalador a liga apenas lá. O restante da stack é igual nos três sistemas.

### Instalação manual (avançado)

Quem prefere não usar o instalador faz os mesmos passos à mão:

```bash
cp .env.example .env
```

O `.env` é opcional: sem ele a stack sobe com os padrões (logins `admin` / `password`). Nenhuma senha precisa ser criada à mão: o serviço `secrets-init` gera os segredos internos na primeira subida. Preencha o `.env` só para o que for seu: tokens dos bots, `MQTT_BIND` com o IP do computador na rede (o padrão `127.0.0.1` só aceita conexões locais, e o sensor precisa do IP da rede) e, no macOS e no Windows, `COMPOSE_PROFILES=` vazio.

```bash
docker compose up -d
docker compose ps        # espere 30–60 s: tudo deve estar running ou healthy
```

Depois, ligue o n8n ao banco e ao MQTT:

```bash
# importa os workflows (o instalador faz isto sozinho)
docker compose exec n8n n8n import:workflow --separate --input=/workflows
```

No n8n, crie as credenciais **Postgres** `TimescaleDB (n8n_app)` (host `timescaledb`, banco `POSTGRES_DB`, usuário `n8n_app`, senha em `docker compose exec n8n cat /run/secrets/n8n_db/value`) e **MQTT** `Mosquitto (usuário n8n)` (host `mosquitto`, porta 1883, usuário `n8n`, senha em `docker compose exec n8n cat /run/secrets/mqtt_n8n/value`), e ative os dois workflows. Por fim, baixe a reserva local do Hermes: `docker compose exec ollama ollama pull qwen2.5:3b`.

---

## Desenvolvimento

Para mexer no código (firmware, testes, CI) você precisa de Python 3.11+, [uv](https://docs.astral.sh/uv/), Git e, para o firmware, [PlatformIO](https://platformio.org/). A estrutura do repositório, os comandos e as convenções estão em [AGENTS.md](AGENTS.md).

```bash
# Python (uv é a única fonte de dependências: pyproject.toml + uv.lock)
curl -LsSf https://astral.sh/uv/install.sh | sh          # Linux / macOS
# Windows (PowerShell): powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv sync --group dev --frozen
uv run pytest            # testes
uv run ruff check .      # lint

# Firmware (a partir de firmware/): copie firmware/.env.example para firmware/.env e preencha
pio test -e native       # testes sem hardware (direção do som, comandos)
pio run -e esp32s3       # build
```

Use `uv add` / `uv remove` para mudar dependências (atualiza o `uv.lock`); nunca edite o `uv.lock` à mão. Para gerar o executável do instalador localmente: `uvx --from "pyinstaller>=6.11" pyinstaller installer/elex_installer.spec`.

## Flags de saúde

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
