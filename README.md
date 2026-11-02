# ELEX20 - Análise e Reconhecimento de Sons Locais

Projeto para captura, classificação e visualização de sons urbanos em tempo real, usando ESP32 com Edge Impulse (inferência local), MQTT, n8n, TimescaleDB, Grafana e Python.

## Visão geral

O workspace deverá ser aberto na pasta `ELEX20`.
Estrutura principal:

- `bin/`: scripts `.bat` para executar o projeto
- `firmware/`: código do ESP32 (PlatformIO + Edge Impulse)
- `src/`: aplicativos Python principais
- `tools/`: utilitários de captura, filtro e exportação
- `tests/`: testes de integração LSL
- `grafana/`: dashboards e configurações de observabilidade
- `hermes/`: configuração do assistente de IA (gateways Telegram/Discord)
- `mosquitto/`: configuração do broker MQTT

### Fluxo de dados

```text
ESP32 (Edge Impulse, classificação de sons urbanos)

    → [MQTT / WiFi] → Mosquitto
    → [trigger]     → n8n (automação)
    → [insert]      → TimescaleDB
    → [query]       → Grafana (dashboards ao vivo)

```

---

## Infraestrutura de dados (Docker)

Toda a camada de coleta, armazenamento e visualização roda em containers Docker — **sem necessidade de instalar banco de dados, servidor ou ferramenta de BI manualmente**.

### Serviços disponíveis

| Serviço                              | Endereço                    | Usuário             | Senha      |
| ------------------------------------ | --------------------------- | ------------------- | ---------- |
| **Grafana** — dashboards e métricas  | <http://localhost:3000>     | `admin`             | `password` |
| **n8n** — automação de fluxos        | <http://localhost:5678>     | criado no 1º acesso | —          |
| **Hermes Dashboard** — assistente IA | <http://localhost:9119>     | `admin`             | `password` |
| **Mosquitto** — broker MQTT (ESP32)  | `mqtt://localhost:1883`     | `device` / `n8n`    | `.env`     |
| **TimescaleDB** — banco de dados     | interno (sem porta exposta) | `postgres`          | `password` |

> As senhas padrão estão definidas no arquivo `.env`. Veja a seção [Trocar senhas](#trocar-senhas) para alterá-las.

---

### Compatibilidade de sistemas operacionais

| Recurso                         | Linux | macOS | Windows                                                         |
| ------------------------------- | ----- | ----- | --------------------------------------------------------------- |
| Docker Compose (stack completa) | ✅    | ✅    | ✅ Docker Desktop + WSL2                                        |
| Python / uv / firmware          | ✅    | ✅    | ✅                                                              |
| Coleta de logs (Alloy)          | ✅    | ✅    | ✅ via WSL2                                                     |
| direnv (`.envrc`)               | ✅    | ✅    | ⚠️ não disponível — use `set DOCKER_HOST=...` no WSL2 ou ignore |
| Commits com Husky               | ✅    | ✅    | ✅ Git Bash ou WSL2                                             |

> **Windows**: recomenda-se usar **Docker Desktop** com backend **WSL2** e rodar todos os comandos no terminal WSL2 (Ubuntu) ou Git Bash. O PowerShell nativo pode ter limitações com as ferramentas de desenvolvimento.

---

### Pré-requisitos

Apenas **um programa** precisa ser instalado:

- **Docker Engine** (Linux) **ou Docker Desktop** (Windows / macOS)
  - Linux: <https://docs.docker.com/engine/install/ubuntu/>
  - Windows / macOS: <https://www.docker.com/products/docker-desktop/>

Após instalar, verifique:

```bash
docker --version
docker compose version
```

---

### Inicialização (3 passos)

#### Passo 1 — Copiar o arquivo de configuração

```bash
cp .env.example .env
```

> O arquivo `.env` contém as senhas e configurações. Quatro senhas **não têm valor padrão** e precisam ser preenchidas antes do `docker compose up` (o compose falha e avisa qual falta): `GRAFANA_RO_PASSWORD`, `N8N_DB_PASSWORD`, `MQTT_DEVICE_PASS` e `MQTT_N8N_PASS`. Gere cada uma com `openssl rand -hex 24`. Para o ESP32 na LAN, defina também `MQTT_BIND` com o IP do host nessa rede (o padrão `127.0.0.1` só aceita conexões locais) e use a mesma senha de `MQTT_DEVICE_PASS` em `MQTT_PASS` no `firmware/.env`. No n8n, crie a credencial MQTT com usuário `n8n` e a senha de `MQTT_N8N_PASS`.

#### Passo 2 — Iniciar todos os serviços

```bash
docker compose up -d
```

O Docker vai baixar as imagens automaticamente na primeira vez (~2–4 GB dependendo da conexão). As próximas execuções iniciam em segundos.

#### Passo 3 — Aguardar a inicialização

Aguarde cerca de **30–60 segundos** e acesse os serviços pelo navegador. Para acompanhar o progresso:

```bash
docker compose ps
```

Todos os serviços devem aparecer como `running` ou `healthy`.

---

### Primeiro uso de cada serviço

#### Grafana — dashboards

1. Acesse <http://localhost:3000>
2. Entre com `admin` / `password`
3. Os dashboards de sons urbanos já estão pré-configurados na seção **Dashboards**

#### n8n — automação de fluxos

O n8n exige a criação de uma conta **apenas na primeira abertura**:

1. Acesse <http://localhost:5678>
2. Preencha o formulário com nome, e-mail e senha (qualquer valor — é local)
3. Clique em **Get started**
4. A conta é salva automaticamente e não precisa ser criada novamente

> A partir da segunda abertura, basta fazer login com o e-mail e senha escolhidos.

#### Hermes Dashboard — assistente de IA

1. Acesse <http://localhost:9119>
2. Entre com `admin` / `password`
3. Configure os gateways (Telegram / Discord) pela interface

---

### Parar e reiniciar os serviços

```bash
# Pausar todos os containers (dados preservados)
docker compose stop

# Retomar depois de pausar
docker compose start

# Reiniciar um serviço específico
docker compose restart grafana

# Parar e remover os containers (dados nos volumes são preservados)
docker compose down
```

> **Os dados não são perdidos** ao parar ou remover containers — ficam armazenados em volumes Docker persistentes. Apenas `docker compose down -v` apaga os volumes (use com cautela).

---

### Atualizar as imagens

Para obter versões mais recentes dos serviços:

```bash
docker compose pull
docker compose up -d
```

---

### Trocar senhas

Edite o arquivo `.env` com um editor de texto e altere os valores:

```code
GRAFANA_ADMIN_PASSWORD=nova_senha
HERMES_DASHBOARD_PASS=nova_senha
POSTGRES_PASSWORD=nova_senha
```

Depois reinicie os serviços afetados:

```bash
docker compose up -d grafana hermes-agent timescaledb
```

---

### Solução de problemas (Docker)

#### `docker compose up -d` falha com "port already in use"

Outra aplicação está usando a mesma porta. Identifique qual:

```bash
sudo ss -tlnp | grep 3000   # substitua pelo número da porta
```

#### Um container aparece como "Restarting"

Veja os logs para entender o erro:

```bash
docker logs <nome-do-container> --tail 30
```

#### n8n mostra erro de banco de dados

O n8n usa um banco dedicado (`n8n`) no TimescaleDB, criado automaticamente pelo serviço `db-init` a cada `docker compose up` (só cria se não existir, então funciona também em volumes antigos). Se o n8n ainda reclamar do banco, veja o que o init registrou:

```bash
docker compose logs db-init
```

#### Hermes continua reiniciando

Verifique os tokens de gateway no `.env`:

```bash
docker logs hermes-agent --tail 20
```

Se aparecer `The token ... was rejected`, os tokens do Telegram ou Discord estão inválidos. Atualize-os no `.env` e reinicie:

```bash
docker compose restart hermes-agent
```

---

## Pré-requisitos (Python e R)

- Python **3.11** ou superior
- R 4.5 ou superior
- [uv](https://docs.astral.sh/uv/) — gerenciador de pacotes Python
- VS Code com extensões Python
- Git

```bash
python --version   # deve retornar 3.11+
R --version
uv --version
```

## Configuração do Python

### Instalar o uv (se ainda não tiver)

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Instalar as dependências do projeto

Na raiz do workspace `ELEX20`:

```bash
uv sync
```

Isso cria o ambiente virtual `.venv` e instala exatamente o que está em `uv.lock` — reprodutível em qualquer máquina.

Para ativar o ambiente manualmente:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### Gerenciamento de dependências

O `pyproject.toml` + `uv.lock` são a única fonte de verdade. Para adicionar ou remover uma dependência use `uv add` / `uv remove` (atualiza o lockfile); para reproduzir o ambiente, `uv sync --frozen`.

## Observação sobre o workspace

Para manter os caminhos consistentes, abra o projeto a partir da pasta `ELEX20`.

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
