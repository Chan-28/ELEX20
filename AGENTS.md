# AGENTS.md

## Visão geral

ELEX20: monitoramento de sons urbanos. ESP32-S3 com microfone I2S roda um modelo Edge Impulse e publica a classificação por MQTT. O n8n grava no TimescaleDB e o Grafana exibe. O Hermes estabelece conexões bidirecionais para entrada de dados e e realização de ações segundo instruções do usuário. Python 3.1x gerenciado só com `uv`; firmware em C++/Arduino via PlatformIO; a infraestrutura roda toda em Docker Compose.

```text
ESP32-S3 (Edge Impulse) → MQTT (Mosquitto) → n8n → TimescaleDB → Grafana
```

A prioridade do projeto é o núcleo no dispositivo: captar o som, classificar e dar o feedback motor. Monitoramento, integração e gravação nos workflows são secundários.

## Comandos essenciais

```bash
# Python (uv é a única fonte de dependências: pyproject.toml + uv.lock)
uv sync --group dev --frozen       # instalar
uv run ruff check .                # lint (npm run lint faz o mesmo)
uv run ruff format .               # formatar (npm run format)
uv run ruff check . --fix && uv run ruff format .   # npm run fix
bash scripts/infra-smoke.sh        # testa papéis do banco e ACL do MQTT (sobe containers descartáveis)

# Infra
cp .env.example .env               # opcional: sem .env a stack sobe com os padrões (nunca commitar)
docker compose up -d
docker compose logs -f <servico>

# Firmware (a partir de firmware/)
cp .env.example .env               # WIFI_SSID, WIFI_PASS, MQTT_HOST, MQTT_USER, MQTT_PASS
pio run -e esp32s3                 # build
pio run -e esp32s3 -t upload && pio device monitor

# JS (só lint de configs e commitlint; Husky roda no commit)
npm install
```

Documentação e arquivos `.md/.json/.yaml` não exigem build. O Prettier formata esses arquivos no pre-commit.

## Estrutura

| Caminho                             | Papel                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `firmware/`                         | Código do ESP32-S3 (`src/main.cpp`, `platformio.ini`). `lib/elex_core/` (direção GCC-PHAT, comandos, urgência) é testada sem hardware com `pio test -e native`. O modelo Edge Impulse vai em `firmware/lib/ei-model/` (não versionado).                                                                                                                                                                    |
| `scripts/infra-smoke.sh`            | Teste de infraestrutura: papéis do banco e ACL do Mosquitto (roda no CI em `infra-smoke.yml`).                                                                                                                                                                                                                                                                                                             |
| `installer/`, `install.sh/.bat`     | Instalador multiplataforma (só stdlib): confere o Docker, gera o `.env`, sobe a stack e configura o n8n (credenciais + `publish:workflow`). O `elex_installer.spec` o empacota com PyInstaller; `installer.yml` compila nos 3 SOs e `release.yml` anexa os executáveis assinados à release. `ARQUIVOS_DO_PROJETO` lista o que é embutido: um arquivo novo montado no compose precisa entrar lá (há teste). |
| `n8n/workflows/`                    | Workflows do n8n exportados (ingestão MQTT, alerta ao Hermes, comando ao dispositivo); importe com `n8n import:workflow`.                                                                                                                                                                                                                                                                                  |
| `timescaledb/init.sql`              | Schema: `devices`, `sound_events` (hypertable).                                                                                                                                                                                                                                                                                                                                                            |
| `mosquitto/`, `grafana/`, `hermes/` | Configuração dos serviços do compose. `hermes/config.yaml` é o único arquivo que o Hermes lê; `hermes/mcp/` é o servidor MCP (consultas com `hermes_ro` e `enviar_comando` via n8n).                                                                                                                                                                                                                       |
| `.github/workflows/`                | CI: lint Python, firmware, CodeQL, segurança de Docker (Gitleaks, Grype, Trivy config, OWASP ZAP baseline), zizmor (segurança dos próprios workflows), `pio check` no firmware, release.                                                                                                                                                                                                                   |

## Arquitetura e limites

- A rede fica fora do caminho do áudio: o `loop()` só classifica e estima a direção, a tarefa `net` cuida de Wi-Fi, MQTT e publicação (recuo em `lib/elex_core/backoff.h`; tempo do motor em `motor_timer.h`) e a tarefa `motor`, acima do `loop()`, é a única que toca nos motores. Não chame nada que bloqueie na rede no `loop()`, e não reinicie a placa por falta de rede. Detecções feitas sem rede são descartadas.
- Serviços ficam na rede interna `monitoring`. **O TimescaleDB não expõe porta ao host**; não adicione `ports:` a ele.
- O n8n escuta só em `127.0.0.1:5678`. Mantenha os serviços ligados a localhost. A porta 1883 só é publicada em `MQTT_BIND` (padrão loopback); o Mosquitto exige usuário (`device` publica, `n8n` assina) e ACL em `mosquitto/acl`.
- Grafana e n8n não usam o superusuário do banco: `grafana_ro` (leitura) e `n8n_app`, criados pelo `db-init` (`timescaledb/db-init.sql`). Não monte o socket do Docker no Hermes.
- O Alloy (`profiles: [logs]`) só sobe com `COMPOSE_PROFILES=logs` (Linux): no Docker Desktop do macOS/Windows os caminhos de logs não existem. O instalador define isso por sistema.
- Segredos internos (senhas dos papéis do banco e do MQTT, tokens n8n↔Hermes): o serviço `secrets-init` (`init/secrets-init.sh`) os gera na primeira subida em volumes `sec_*` (um por segredo; cada serviço monta só os seus, em `/run/secrets/<nome>/value`). Nada aqui é obrigatório no `.env`; definir a variável só fixa o valor. Um segredo novo precisa entrar no script, no compose (volume + mount) e em `SEGREDOS_AUTOMATICOS` do instalador (há teste).
- Imagens são fixadas por versão e digest; atualize pelo Dependabot, não volte para `latest`.
- Tópicos MQTT: `sound/inference`, `sound/status` e `sound/cmd` (`/<device_id>`; só o n8n escreve em `sound/cmd`, o Hermes nunca publica no MQTT); o schema documenta `sound/inference/<device_id>`. Mudou um, confira os outros.
- `AUDIO_SAMPLE_RATE` (16000) e `AUDIO_WINDOW_MS` precisam coincidir com a janela do projeto Edge Impulse.
- Credenciais do firmware entram pelo `firmware/load_env.py` (ambiente ou `firmware/.env`; secrets do CI), nunca no código; o build falha se alguma estiver vazia.

## Convenções de código

- Ruff com regras `E, F, I, B, S, UP, C4, ARG, N` (inclui segurança `S`). Imports organizados pelo Ruff; não rode `black` nem `isort`, mesmo estando no grupo `dev`.
- Python ≥ 3.11 (`.python-version`). Não crie `requirements.txt`.
- Comentários e docstrings em português, como no resto do projeto.
- Nomes de arquivos e flags de linha de comando em inglês. Executáveis e arquivos de release usam os nomes convencionais da comunidade (`install.sh`, `installer`).

## Testes

- Python: `uv run pytest` (`tests/`: comandos do Hermes e instalador). Firmware: `cd firmware && pio test -e native`. Faixas de comando e urgência por rótulo existem em três lugares (`hermes/mcp/commands.py`, `n8n/workflows/device-command.json`, `firmware/lib/elex_core/settings.cpp`; urgência também em `timescaledb/db-init.sql`): mudou um, confira os outros.
- Mudou compose, `mosquitto/` ou `timescaledb/`? Rode `bash scripts/infra-smoke.sh` (precisa de Docker; falha se já houver containers `timescaledb`/`mosquitto`).

## Git, commits e PRs

- Commits seguem Conventional Commits (`commitlint` no hook `commit-msg`). Ex.: `feat(firmware): ajusta janela de áudio`.
- O hook `pre-commit` roda `lint-staged` (ESLint e Prettier). Se falhar, corrija; não use `--no-verify`.
- PR para `main`. O CI do Python só dispara quando mudam `**.py`, `pyproject.toml` ou `uv.lock`.

## Nunca faça

- Commitar `.env`, `firmware/.env`, tokens (Discord, Telegram, OpenRouter) ou senhas.
- Expor portas do banco ou publicar serviços em `0.0.0.0`.
- Editar `uv.lock` à mão; use `uv add`/`uv remove`/`uv lock`.
- Rodar `docker compose down -v`: apaga os volumes (dados do TimescaleDB, n8n e Grafana).

## Armadilhas conhecidas (verificadas no código)

- `.envrc` define `DOCKER_HOST`; no Windows sem `direnv`, use WSL2.
