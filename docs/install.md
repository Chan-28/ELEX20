# Instalação do ELEX20

Guia para quem vai montar e usar o ELEX20. Ele tem duas partes:

- **[Parte 1 — Hardware](#parte-1--hardware):** montar o sensor, testar os microfones e os motores e gravar o firmware.
- **[Parte 2 — Software](#parte-2--software):** instalar o servidor no computador e conferir que os dados chegam.

O sensor funciona sozinho: ele ouve, reconhece o som e vibra o motor do lado de onde o som veio, mesmo sem Wi-Fi. O servidor é um complemento, que guarda o histórico, mostra painéis e manda alertas pelo Telegram ou pelo Discord.

> [!WARNING]
> O ELEX20 **não é um dispositivo de segurança**. O modelo atual reconhece só parte dos sons urgentes, como sirenes e buzinas. Não dependa dele para perceber um perigo.

## Ordem dos passos

1. [Montar o sensor](#11-o-que-você-precisa) e [testar na bancada](#13-testar-microfones-e-motores) (Parte 1).
2. [Instalar o servidor](#21-instalar-o-docker) (Parte 2). O instalador gera as configurações que o sensor precisa.
3. [Gravar o firmware final](#14-gravar-o-firmware-do-sensor) (Parte 1).
4. [Conferir tudo funcionando](#25-conferir-se-os-dados-chegam) (Parte 2).

Para gravar o sensor você precisa do repositório clonado. O executável da página de Releases instala só o servidor.

---

## Parte 1 — Hardware

### 1.1 O que você precisa

- 1 placa **ESP32-S3 N16R8** (16 MB de flash e 8 MB de PSRAM), como a ESP32-S3-DevKitC-1;
- 4 microfones **INMP441**;
- 4 motores de vibração, cada um ligado por um **MOSFET**;
- cabo USB com dados (não só de carga);
- rede Wi-Fi de **2,4 GHz**, a mesma do computador que vai rodar o servidor. Em rede de universidade ou empresa, com usuário e senha pessoais (como o eduroam), veja [Wi-Fi institucional](reference.md#wi-fi-institucional).

No computador:

- [Git](https://git-scm.com/downloads), [Python 3.11 ou mais novo](https://www.python.org/downloads/) e [uv](https://docs.astral.sh/uv/getting-started/installation/);
- [PlatformIO](https://platformio.org/install/cli), para gravar a placa.

Baixe o projeto:

```bash
git clone https://github.com/Chan-28/ELEX20.git
cd ELEX20
uv sync --group debug
```

### 1.2 Ligações

Alimente os microfones com **3,3 V** e GND. Os quatro compartilham SCK e WS. O pino **L/R** define o canal de cada um, e trocar um L/R troca a direção que vibra.

| Posição  | SCK    | WS     | SD     | L/R   | Motor (pelo MOSFET) |
| -------- | ------ | ------ | ------ | ----- | ------------------- |
| Frente   | GPIO 4 | GPIO 5 | GPIO 6 | GND   | GPIO 18             |
| Trás     | GPIO 4 | GPIO 5 | GPIO 6 | 3,3 V | GPIO 16             |
| Direita  | GPIO 4 | GPIO 5 | GPIO 7 | GND   | GPIO 17             |
| Esquerda | GPIO 4 | GPIO 5 | GPIO 7 | 3,3 V | GPIO 15             |

Monte os microfones a cerca de **9 cm** do centro, um em cada direção. Se a sua distância for outra, avise quem configura o firmware (valor `MIC_RADIUS_M`), porque ela entra no cálculo da direção.

Ligue a placa pela porta USB-C marcada **COM** (ou **UART**).

### 1.3 Testar microfones e motores

Antes do firmware final, grave o firmware de bancada. Ele só testa o hardware: não usa Wi-Fi nem o modelo.

```bash
cd debug/firmware
pio run -t upload
cd ../..
```

Descubra a porta da placa: `/dev/ttyUSB0` ou `/dev/ttyACM0` no Linux, `/dev/cu.usbserial-…` no macOS e `COM3` (ou outro número) no Windows. Troque nos comandos abaixo.

**1. Os microfones estão vivos?** Fique num lugar silencioso e rode:

```bash
uv run --group debug python debug/mic_check.py report --port /dev/ttyUSB0 --quiet-room
```

Todos os canais devem aparecer como `ok`. Depois fale a uns 2 metros: os quatro níveis devem subir juntos. Saia com `Ctrl+C`.

| Se aparecer              | Faça                                                                          |
| ------------------------ | ----------------------------------------------------------------------------- |
| `canal morto`            | Confira a solda, o fio SD, o L/R e a alimentação daquele microfone            |
| `ruído alto em silêncio` | Afaste fontes e carregadores; teste com outro cabo ou outra fonte             |
| `zumbido`                | Problema de fonte ou de aterramento; teste alimentando pela USB do computador |
| `nível longe dos outros` | Microfone fraco ou furo tampado; confira a montagem                           |

**2. Os microfones estão no lugar certo?**

```bash
uv run --group debug python debug/mic_check.py tap --port /dev/ttyUSB0
```

O programa pede para você bater de leve com o dedo em cada microfone: frente, direita, trás e esquerda. No final, deve dizer `Ordem dos canais correta.`. Se disser que os canais estão trocados, inverta o L/R ou o fio SD dos microfones apontados.

**3. Os motores vibram?**

```bash
uv run --group debug python debug/mic_check.py motors --port /dev/ttyUSB0
```

Cada motor deve vibrar uma vez, na ordem frente, direita, trás e esquerda.

Com os três testes certos, o hardware está pronto. Siga para a [Parte 2](#parte-2--software) e volte para o passo 1.4 depois de instalar o servidor.

### 1.4 Gravar o firmware do sensor

Você precisa de:

- o arquivo `firmware/.env`, criado pelo instalador na [Parte 2](#23-seguir-o-assistente);
- o modelo de sons, um `.zip` exportado do Edge Impulse em **Deployment → Arduino library**. O instalador o coloca no lugar certo.

Grave o firmware **com o modelo**:

```bash
cd firmware
pio run -e esp32s3_model -t upload
pio device monitor
```

> [!IMPORTANT]
> Use `esp32s3_model`. O ambiente `esp32s3` grava o firmware **sem** modelo: o sensor conecta, mas nunca reconhece nada nem vibra.

No log, procure:

```text
[WiFi] IP: 192.168.x.x  RSSI: -55 dBm
[MQTT] Conectado.
```

A linha `[EI] Sem modelo` **não** pode aparecer. Ao tocar um som de sirene pelo celular, deve aparecer `[INF] siren …`, e o motor do lado do celular deve vibrar. Saia do monitor com `Ctrl+C`.

---

## Parte 2 — Software

### 2.1 Instalar o Docker

O servidor roda no Docker.

- **Windows:** instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/) com a opção **WSL 2**. Abra-o e espere iniciar.
- **macOS:** instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/). Abra-o e espere iniciar.
- **Linux:**

  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo systemctl enable --now docker
  sudo usermod -aG docker $USER
  ```

  Saia da sessão e entre de novo.

Confira:

```bash
docker compose version
```

### 2.2 Abrir o instalador

Na pasta do projeto, a mesma da Parte 1:

```bash
./install.sh
```

No Windows, use `install.bat`.

Se você só quer o servidor, sem gravar um sensor, pode baixar o executável do seu sistema na página de [Releases](https://github.com/Chan-28/ELEX20/releases) e abri-lo. Ele instala em `~/ELEX20`, mas não traz o firmware.

### 2.3 Seguir o assistente

O assistente é em inglês e só muda algo depois da tela de revisão. Use `Tab` para mudar de campo e `Esc` para voltar.

1. **Choose where to install:** a pasta de instalação. Deixe a do projeto.
2. **Choose what to set up:** ligue **Connect a sensor through this network** e confirme o IP deste computador. Ligue **Telegram bot** se quiser alertas no celular ([como criar o bot](reference.md#telegram)). O modelo local de IA (cerca de 2 GB) é opcional.
3. **Set up the device:** em **Create the device configuration**, o nome e a senha do Wi-Fi (só 2,4 GHz) e o IP deste computador. Numa rede com login pessoal, como o eduroam, ligue **Institutional network with a personal login** e preencha o usuário e o certificado ([Wi-Fi institucional](reference.md#wi-fi-institucional)). Para o sensor funcionar em dois lugares, como casa e universidade, ligue **Add a second Wi-Fi network** ([Várias redes](reference.md#várias-redes)). Ligue **Add an Edge Impulse sound model to the firmware** e informe o `.zip` do modelo.
4. **Review and install:** confira e confirme.

Na primeira vez, o Docker baixa alguns GB, o que leva vários minutos. No final, aparecem os endereços e os logins.

Volte agora à Parte 1 e [grave o firmware](#14-gravar-o-firmware-do-sensor).

> [!WARNING]
> Guarde o arquivo `.env` da pasta de instalação e não o compartilhe: ele tem as senhas.

**Reserve o IP do computador no roteador.** Se o IP mudar, o sensor deixa de achar o servidor (mas continua vibrando).

### 2.4 Abrir os serviços

| Serviço                 | Endereço                | Login                                  |
| ----------------------- | ----------------------- | -------------------------------------- |
| **Grafana** (painéis)   | <http://localhost:3000> | `admin` / `password`: troque no 1º uso |
| **Hermes** (assistente) | <http://localhost:9119> | `admin` / `password`: troque no 1º uso |
| **n8n** (automação)     | <http://localhost:5678> | crie no primeiro acesso                |

Os serviços só abrem neste computador. Isso é de propósito.

### 2.5 Conferir se os dados chegam

1. No Grafana, abra **Dashboards → Sons Urbanos — ELEX20**.
2. O painel de sensores deve mostrar o seu sensor com um heartbeat recente (menos de 1 minuto).
3. Toque um som de sirene perto do sensor. Em alguns segundos, um evento `siren` aparece em **Últimos eventos**.
4. Com o Telegram configurado, o alerta chega no chat.

Sem o sensor por perto, você pode testar o servidor com um sensor simulado:

```bash
uv run python debug/simulate_sensor.py --duration 60
```

Depois apague os dados simulados:

```bash
uv run python debug/simulate_sensor.py --cleanup
```

### 2.6 Dia a dia

| Para                    | Rode, na pasta de instalação                                        |
| ----------------------- | ------------------------------------------------------------------- |
| Parar o servidor        | `docker compose stop`                                               |
| Ligar de novo           | `docker compose start`                                              |
| Atualizar               | `git pull` e rode o instalador de novo                              |
| Mudar uma configuração  | rode o instalador de novo; ele mantém o que você não mudar          |
| Trocar a rede do sensor | `./install.sh --wifi` ([Mudar de rede](reference.md#mudar-de-rede)) |
| Desinstalar             | `./install.sh --uninstall`                                          |

A desinstalação remove os containers e mantém o histórico, a menos que você peça para apagar os dados.

No **Linux**, se um comando `docker` disser que um container não existe, rode antes `export DOCKER_HOST=unix:///var/run/docker.sock`. O Docker Desktop, quando instalado, pode estar sendo usado no lugar do Docker do sistema.

### 2.7 Se algo der errado

| Sintoma                                    | O que conferir                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------------- |
| O sensor não conecta (`[MQTT] rc=` no log) | Wi-Fi de 2,4 GHz, IP do computador igual ao do instalador e porta 1883 liberada no firewall |
| Conecta, mas não aparecem eventos          | Se o firmware foi gravado com `esp32s3_model` e se o log mostra `[INF]`                     |
| Eventos aparecem, mas o alerta não chega   | Telegram configurado no instalador e rótulo com urgência alta (sirene, buzina, alarme…)     |
| O motor errado vibra                       | Refaça o [teste de toque](#13-testar-microfones-e-motores)                                  |

Para os detalhes técnicos, veja o [guia de debug](debug.md) e a [referência completa](reference.md).
