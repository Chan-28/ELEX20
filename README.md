# ELEX20 - Análise e Reconhecimento de Sons Locais

Projeto para captura, classificação e visualização de sons urbanos em tempo real, usando ESP32 com Edge Impulse (inferência local), MQTT, n8n, TimescaleDB, Grafana e um assistente de IA (Hermes) que conversa pelo Telegram e pelo Discord.

```text
ESP32 (Edge Impulse, classificação de sons urbanos + direção do som)

    → [MQTT / WiFi] → Mosquitto
    → [trigger]     → n8n (automação)
    → [insert]      → TimescaleDB
    → [query]       → Grafana (dashboards ao vivo)
                    → Hermes (consultas, alertas e comandos pelo chat)
```

---

## Instalação rápida (recomendada)

Funciona em **Windows, macOS e Linux**. Você não precisa saber programar: o instalador cria as senhas, sobe todos os serviços e configura o n8n sozinho.

### 1. Instale o Docker

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

### 2. Baixe o instalador

Na página de [Releases](https://github.com/Chan-28/ELEX20/releases), baixe o arquivo do seu sistema:

| Sistema                             | Arquivo                              |
| ----------------------------------- | ------------------------------------ |
| Windows                             | `elex-instalador-windows-x86_64.exe` |
| macOS (Apple Silicon: M1, M2, ...)  | `elex-instalador-macos-arm64`        |
| macOS (Intel)                       | `elex-instalador-macos-x86_64`       |
| Linux (PC comum)                    | `elex-instalador-linux-x86_64`       |
| Linux (ARM: Raspberry Pi 4/5, etc.) | `elex-instalador-linux-arm64`        |

O mesmo arquivo serve para qualquer distribuição Linux (Ubuntu, Debian, Mint, Fedora, Arch, openSUSE...). Para saber se o seu Linux é x86_64 ou ARM, rode `uname -m`.

### 3. Execute

- **Windows:** dê dois cliques no arquivo. Se o SmartScreen avisar "O Windows protegeu seu computador", clique em **Mais informações** e depois em **Executar assim mesmo** (o executável não tem assinatura paga da Microsoft; veja como verificar a assinatura mais abaixo).
- **macOS:** abra o Terminal na pasta do download e rode:

  ```bash
  chmod +x elex-instalador-macos-arm64
  xattr -d com.apple.quarantine elex-instalador-macos-arm64
  ./elex-instalador-macos-arm64
  ```

- **Linux:**

  ```bash
  chmod +x elex-instalador-linux-x86_64
  ./elex-instalador-linux-x86_64
  ```

### 4. Responda às perguntas

O instalador pergunta só o que é opcional (você pode apertar Enter para pular tudo):

- se vai ligar o sensor ESP32 na sua rede (ele descobre o IP do computador);
- chave do OpenRouter (IA na nuvem; sem ela o Hermes usa o modelo local);
- bot do Telegram e/ou do Discord (token, o seu ID e o chat que recebe os alertas);
- se quer baixar o modelo local de IA (cerca de 2 GB).

Ele instala em `~/ELEX20` (no Windows, `C:\Users\<você>\ELEX20`) e, ao final, mostra os endereços e as senhas geradas. **As senhas ficam no arquivo `.env` dessa pasta: guarde-o e não o compartilhe.**

Na primeira vez, o Docker baixa alguns GB de imagens; pode levar vários minutos.

### O que o instalador faz

1. Confere se o Docker está instalado e ligado.
2. Copia os arquivos da stack para a pasta de instalação.
3. Cria o `.env` com senhas aleatórias (nunca troca um `.env` que já existe).
4. Executa `docker compose up -d` e espera o n8n e o Grafana responderem.
5. Baixa o modelo local do Ollama (opcional).
6. Cria no n8n as credenciais do Postgres e do MQTT, importa os workflows e os ativa.

Pode rodar de novo a qualquer momento: ele só completa o que falta. Opções úteis (linha de comando): `--dir PASTA`, `--nao-interativo`, `--sem-modelo`, `--set CHAVE=VALOR` e `--dry-run` (só mostra os comandos do Docker).

### Verificar o download (opcional)

Cada arquivo da release vem com `.sha256` e `.sigstore.json`. Com o [cosign](https://docs.sigstore.dev/cosign/system_config/installation/):

```bash
cosign verify-blob \
  --bundle elex-instalador-linux-x86_64.sigstore.json \
  --certificate-identity "https://github.com/Chan-28/ELEX20/.github/workflows/release.yml@refs/tags/<versão>" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  elex-instalador-linux-x86_64
```

### Já clonou o repositório?

Rode o instalador direto da pasta, com o Python 3 do sistema: `./instalar.sh` (Linux/macOS) ou `instalar.bat` (Windows). Ele usa o repositório como pasta de instalação.

---

## Serviços

| Serviço                              | Endereço                    | Usuário                 | Senha                                |
| ------------------------------------ | --------------------------- | ----------------------- | ------------------------------------ |
| **Grafana** — dashboards e métricas  | <http://localhost:3000>     | `GRAFANA_ADMIN_USER`    | `GRAFANA_ADMIN_PASSWORD` (no `.env`) |
| **n8n** — automação de fluxos        | <http://localhost:5678>     | criado no 1º acesso     | —                                    |
| **Hermes Dashboard** — assistente IA | <http://localhost:9119>     | `HERMES_DASHBOARD_USER` | `HERMES_DASHBOARD_PASS` (no `.env`)  |
| **Mosquitto** — broker MQTT (ESP32)  | `mqtt://localhost:1883`     | `device` / `n8n`        | `MQTT_DEVICE_PASS` / `MQTT_N8N_PASS` |
| **TimescaleDB** — banco de dados     | interno (sem porta exposta) | `postgres`              | `POSTGRES_PASSWORD` (no `.env`)      |

> Com o instalador, todas as senhas são aleatórias. Se você criar o `.env` à mão a partir do `.env.example`, as senhas de exemplo (`password`) servem só para a sua máquina: troque-as antes de qualquer outro uso.

### Compatibilidade de sistemas operacionais

| Recurso                         | Linux | macOS             | Windows                                                           |
| ------------------------------- | ----- | ----------------- | ----------------------------------------------------------------- |
| Instalador (executável)         | ✅    | ✅                | ✅                                                                |
| Docker Compose (stack completa) | ✅    | ✅ Docker Desktop | ✅ Docker Desktop + WSL2                                          |
| Coleta de logs (Alloy)          | ✅    | ➖ desligada      | ➖ desligada (ligue com `COMPOSE_PROFILES=logs` se quiser testar) |
| Python / uv / firmware          | ✅    | ✅                | ✅                                                                |
| direnv (`.envrc`)               | ✅    | ✅                | ⚠️ não disponível — use `set DOCKER_HOST=...` no WSL2 ou ignore   |
| Commits com Husky               | ✅    | ✅                | ✅ Git Bash ou WSL2                                               |

> A coleta de logs (Alloy) lê caminhos do Docker que só existem no Linux; por isso o instalador a liga apenas lá. O restante da stack é igual nos três sistemas.
>
> **Windows:** se o sensor ESP32 não conectar, libere a porta **1883** no Firewall do Windows. O ESP32 só usa Wi-Fi de **2,4 GHz**.

---

## Instalação manual (avançado)

Quem prefere não usar o instalador faz os mesmos passos à mão:

```bash
cp .env.example .env
```

Preencha no `.env` as sete variáveis **sem valor padrão** (o compose falha e avisa qual falta), cada uma com `openssl rand -hex 24`: `GRAFANA_RO_PASSWORD`, `N8N_DB_PASSWORD`, `HERMES_RO_PASSWORD`, `MQTT_DEVICE_PASS`, `MQTT_N8N_PASS`, `HERMES_WEBHOOK_SECRET` e `N8N_COMMAND_TOKEN`. No macOS e no Windows, deixe `COMPOSE_PROFILES=` vazio. Para o ESP32 na rede local, defina também `MQTT_BIND` com o IP do computador nessa rede (o padrão `127.0.0.1` só aceita conexões locais) e use a mesma senha de `MQTT_DEVICE_PASS` em `MQTT_PASS` no `firmware/.env`.

```bash
docker compose up -d
docker compose ps        # espere 30–60 s: tudo deve estar running ou healthy
```

Depois, ligue o n8n ao banco e ao MQTT:

```bash
# crie as credenciais e importe/ative os workflows (o instalador faz isto sozinho)
docker compose exec n8n n8n import:workflow --separate --input=/workflows
```

e, no n8n, crie as credenciais **Postgres** `TimescaleDB (n8n_app)` (host `timescaledb`, banco `POSTGRES_DB`, usuário `n8n_app`, senha `N8N_DB_PASSWORD`) e **MQTT** `Mosquitto (usuário n8n)` (host `mosquitto`, porta 1883, usuário `n8n`, senha `MQTT_N8N_PASS`), e ative os dois workflows. Por fim, baixe a reserva local do Hermes: `docker compose exec ollama ollama pull qwen2.5:3b`.

---

## Primeiro uso de cada serviço

### Grafana — dashboards

1. Acesse <http://localhost:3000>
2. Entre com o usuário e a senha do `.env` (`GRAFANA_ADMIN_USER` e `GRAFANA_ADMIN_PASSWORD`)
3. Os dashboards de sons urbanos já estão pré-configurados na seção **Dashboards**

### n8n — automação de fluxos

O n8n exige a criação de uma conta **apenas na primeira abertura**:

1. Acesse <http://localhost:5678>
2. Preencha o formulário com nome, e-mail e senha (qualquer valor — é local)
3. Clique em **Get started**

Os workflows **ELEX20 - Ingestão MQTT** e **ELEX20 - Comando ao dispositivo** já estão importados e ativos (o instalador cuida disso).

### Hermes — assistente de IA

1. Acesse <http://localhost:9119> e entre com o usuário e a senha do `.env`
2. Fale com o bot no Telegram ou no Discord (só os IDs listados em `TELEGRAM_ALLOWED_USERS` e `DISCORD_ALLOWED_USERS` são atendidos)
3. Ferramentas que ele tem: `sensores_status`, `eventos_recentes`, `resumo_sons`, `direcao_predominante`, `classes_urgencia` e `enviar_comando`. Ele lê o banco só com o papel `hermes_ro` e nunca fala direto com o MQTT: os comandos passam pelo n8n, que valida chave e faixa.
4. Os alertas de urgência alta chegam ao chat definido em `TELEGRAM_HOME_CHANNEL`.

A reserva local do Hermes usa o modelo `qwen2.5:3b`; as alternativas estão comentadas em `hermes/config.yaml`. Os níveis de urgência por tipo de som (`sound_classes`) são uma proposta inicial: ajuste com `UPDATE` e mantenha a mesma tabela em `firmware/lib/elex_core/settings.cpp`.

---

## Parar, reiniciar e atualizar

Rode estes comandos na pasta de instalação:

```bash
docker compose stop      # pausa tudo (dados preservados)
docker compose start     # retoma
docker compose restart grafana   # reinicia um serviço
docker compose down      # remove os containers (os dados nos volumes ficam)
```

> **Os dados não são perdidos** ao parar ou remover containers — ficam em volumes Docker. Só `docker compose down -v` apaga os volumes: **nunca use esse comando** sem backup.

Para atualizar as imagens: `docker compose pull` e depois `docker compose up -d`.

### Trocar senhas

Edite o `.env` e reinicie os serviços afetados:

```bash
docker compose up -d grafana hermes-agent timescaledb
```

> `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` e a conta do n8n só valem na primeira criação dos dados; mudar depois exige trocar a senha dentro do próprio serviço. As senhas `GRAFANA_RO_PASSWORD`, `N8N_DB_PASSWORD` e `HERMES_RO_PASSWORD` são reaplicadas a cada `docker compose up`.

---

## Solução de problemas

### O instalador diz que o Docker não está rodando

Abra o Docker Desktop (Windows e macOS) e espere o ícone ficar verde. No Linux: `sudo systemctl start docker`. Se aparecer "permission denied", rode `sudo usermod -aG docker $USER` e entre de novo na sessão.

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

### Os alertas não chegam no Telegram

Confira `TELEGRAM_HOME_CHANNEL` no `.env` e se os workflows do n8n estão ativos (<http://localhost:5678>).

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

Use `uv add` / `uv remove` para mudar dependências (atualiza o `uv.lock`); nunca edite o `uv.lock` à mão. Para gerar o executável do instalador localmente: `uvx --from "pyinstaller>=6.11" pyinstaller installer/elex_instalador.spec`.

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
