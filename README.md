# ELEX20 - Análise e Reconhecimento de Sons Locais

Projeto para captura, classificação e visualização de sinais EMG em tempo real, usando ESP32 com Edge Impulse (inferência local), MQTT, n8n, TimescaleDB, Grafana e Python.

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
ESP32 (Edge Impulse, inferência EMG)

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
| **Portainer** — gerenciar containers | <http://localhost:9000>     | `admin`             | `password` |
| **Hermes Dashboard** — assistente IA | <http://localhost:9119>     | `admin`             | `password` |
| **Mosquitto** — broker MQTT (ESP32)  | `mqtt://localhost:1883`     | —                   | —          |
| **TimescaleDB** — banco de dados     | interno (sem porta exposta) | `postgres`          | `password` |

> As senhas padrão estão definidas no arquivo `.env`. Veja a seção [Trocar senhas](#trocar-senhas) para alterá-las.

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

> O arquivo `.env` contém as senhas e configurações. O padrão já funciona sem modificações. Edite apenas se quiser trocar senhas ou adicionar tokens de API (Telegram, Discord, etc.).

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
3. Os dashboards de EMG já estão pré-configurados na seção **Dashboards**

#### n8n — automação de fluxos

O n8n exige a criação de uma conta **apenas na primeira abertura**:

1. Acesse <http://localhost:5678>
2. Preencha o formulário com nome, e-mail e senha (qualquer valor — é local)
3. Clique em **Get started**
4. A conta é salva automaticamente e não precisa ser criada novamente

> A partir da segunda abertura, basta fazer login com o e-mail e senha escolhidos.

#### Portainer — gerenciamento de containers

1. Acesse <http://localhost:9000>
2. Entre com `admin` / `password`
3. Clique em **Get Started** → **local** para ver todos os containers

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

**Para trocar a senha do Portainer:**

```bash
# 1. Gere um novo hash bcrypt
python3 -c "import bcrypt; print(bcrypt.hashpw(b'nova_senha', bcrypt.gensalt()).decode())" > portainer/admin_password_hash

# 2. Apague o volume e reinicie (necessário para o Portainer ler a nova senha)
docker compose down
docker volume rm elex20_portainer_data
docker compose up -d portainer
```

**Para trocar a senha do n8n:** acesse <http://localhost:5678>, clique no seu nome de usuário (canto inferior esquerdo) → **Settings** → **Change password**.

---

### Ver logs de um serviço

```bash
# Últimas 50 linhas de log do n8n
docker logs n8n --tail 50

# Acompanhar logs em tempo real
docker logs grafana -f
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

#### Portainer não abre a tela de configuração inicial

O Portainer tem um **timeout de 5 minutos** para criar o primeiro usuário após o primeiro start. Se expirou:

```bash
docker compose down
docker volume rm elex20_portainer_data
docker compose up -d portainer
```

Acesse <http://localhost:9000> imediatamente após este comando.

#### n8n mostra erro de banco de dados

O n8n usa um banco dedicado (`n8n`) no TimescaleDB. Se o banco não existir:

```bash
docker exec -it timescaledb psql -U postgres -c "CREATE DATABASE n8n OWNER postgres;"
docker compose restart n8n
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

### Gerenciamento de dependências (`dependencies.py`)

O script `dependencies.py` é a **única interface** de gerenciamento de pacotes do projeto. Ele usa UV exclusivamente e lê o `pyproject.toml` como fonte de verdade.

```bash
# Verificar ambiente e sincronizar dependências faltantes
python dependencies.py

# Apenas verificar, sem instalar
python dependencies.py --no-install

# Verificar consistência do lockfile (uv.lock)
python dependencies.py --lock-check

# Sincronizar ambiente via uv sync --frozen
python dependencies.py --sync
```

> Para adicionar uma nova dependência ao projeto, edite `pyproject.toml` e execute `uv lock` para atualizar o lockfile.

IMPORTANTE: As bibliotecas `bleak` e `pylsl` requerem dependências extras no Linux:

```bash
# bleak (Bluetooth Low Energy)
sudo apt install glib-2.0 libbluetooth-dev bluez
# pylsl
conda install -c conda-forge liblsl
```

## Configuração do R

Abra o R ou o RStudio e instale os pacotes usados na coanfecção dos gráficos:

```r
install.packages(c("ggplot2", "tidyr", "dplyr", "scales", "GGally", "gridExtra"))
```

Se aparecer erro de repositório, escolha um mirror CRAN próximo.

Obs.: Para Linux, o comando

```bash
sudo apt install build-essential libcurl4-openssl-dev libssl-dev libxml2-dev
```

é obrigatório para que garantir que ele possua as ferramentas de compilação do R.

## Como executar o projeto Python

Há dois jeitos comuns de rodar a aplicação:

### Via scripts `.bat` (Somente para Windows)

Na pasta `bin/` existe um atalho pronto:

```bash
.\bin\Executar_Projeto.bat
```

O script `Executar_Projeto.bat` roda a cadeia completa do projeto em janelas separadas:

1. `tools/captar_Dados.py` captura os dados do BLE e publica o stream `EMG`.
2. `tools/filtrar_Dados.py` lê `EMG`, processa e publica `EMG_Processado`.
3. `src/Grafico.py` consome `EMG` e `EMG_Processado` e plota os dois sinais em gráficos distintos.

Para validar o fluxo real do ESP32 antes de abrir a interface, os seguintes programas devem ser executados:

```bash
(Windows)
python .\tests\verificar_stream.py
(Linux)
python3 tests/verificar_stream.py
```

Esse teste confirma se os streams LSL `EMG` e `EMG_Processado` aparecem com os nomes esperados.

### Via Python direto

```bash
(Windows)
python .\src\captar_Dados.py
python .\src\filtrar_Dados.py
python .\src\Grafico.py
(Linux)
python3 src/captar_Dados.py
python3 src/filtrar_Dados.py
python3 src/Grafico.py

```

## Checklist de validação

Antes de considerar o projeto pronto, confirme:

1. `python --version` e `R --version` funciona.
2. `uv sync` termina sem erro.
3. O simulador LSL inicia antes do gráfico principal.
4. O dispositivo BLE aparece com o nome esperado `ESP32_EMG`.

## Solução de problemas (Python / BLE)

### O Python não encontra pacotes

Reinstale as dependências:

```bash
uv sync
```

Se estiver usando ambiente virtual, confirme que ele está ativado (`source .venv/bin/activate`).

### O R não abre ou não é reconhecido

Verifique o PATH e rode:

```bash
R --version
```

Depois instale novamente os pacotes usados pelo projeto.

### O stream LSL não aparece no gráfico

- Verifique se os nomes dos streams são `EMG` e `EMG_Processado`.
- Feche outras aplicações que possam estar consumindo o mesmo stream.

### O BLE não conecta no ESP32

- Confirme o nome do dispositivo: `ESP32_EMG`.
- Verifique se o ESP32 está ligado e com Bluetooth ativo.
- Tente aproximar o computador da placa.

## Observação sobre o workspace

Para manter os caminhos consistentes, abra o projeto a partir da pasta `ELEX20`.

## Flags de saúde

[![CodeScene Average Code Health](https://codescene.io/projects/83420/status-badges/average-code-health)](https://codescene.io/projects/83420)
[![CodeScene Hotspot Code Health](https://codescene.io/projects/83420/status-badges/hotspot-code-health)](https://codescene.io/projects/83420)
[![CodeScene System Mastery](https://codescene.io/projects/83420/status-badges/system-mastery)](https://codescene.io/projects/83420)
[![CodeScene general](https://codescene.io/images/analyzed-by-codescene-badge.svg)](https://codescene.io/projects/83420)

## Star History

<a href="https://www.star-history.com/?repos=Chan-28%2FELEX20.git&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=Chan-28/ELEX20.git&type=date&theme=dark&legend=top-left&sealed_token=NR-lIw07qnsnl0b8_AmOpAHvwOIoG9rXi3WJ0sUY1kw50Z4gu6blbDXnK9FLCnocezkv7Td2qNNOr2Mde_2teQCzJBz7wTwnrF3v38U8ULQuh9HL2hfM9U6ajRIjAhs89t8RKPBVoSfMFzICESpxk027ugaYM8pYsH-SyTOQJ-6Oyf6eapu62_8XP09c" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=Chan-28/ELEX20.git&type=date&legend=top-left&sealed_token=NR-lIw07qnsnl0b8_AmOpAHvwOIoG9rXi3WJ0sUY1kw50Z4gu6blbDXnK9FLCnocezkv7Td2qNNOr2Mde_2teQCzJBz7wTwnrF3v38U8ULQuh9HL2hfM9U6ajRIjAhs89t8RKPBVoSfMFzICESpxk027ugaYM8pYsH-SyTOQJ-6Oyf6eapu62_8XP09c" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=Chan-28/ELEX20.git&type=date&legend=top-left&sealed_token=NR-lIw07qnsnl0b8_AmOpAHvwOIoG9rXi3WJ0sUY1kw50Z4gu6blbDXnK9FLCnocezkv7Td2qNNOr2Mde_2teQCzJBz7wTwnrF3v38U8ULQuh9HL2hfM9U6ajRIjAhs89t8RKPBVoSfMFzICESpxk027ugaYM8pYsH-SyTOQJ-6Oyf6eapu62_8XP09c" />
 </picture>
</a>
