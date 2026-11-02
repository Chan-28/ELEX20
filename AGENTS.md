# AGENTS.md

## Visão geral

ELEX20: monitoramento de sons urbanos. ESP32-S3 com microfone I2S roda um modelo Edge Impulse e publica a classificação por MQTT. O n8n grava no TimescaleDB e o Grafana exibe. O Hermes estabelece conexões bidirecionais para entrada de dados e e realização de ações segundo instruções do usuário. Python 3.1x gerenciado só com `uv`; firmware em C++/Arduino via PlatformIO; a infraestrutura roda toda em Docker Compose.

```text
ESP32-S3 (Edge Impulse) → MQTT (Mosquitto) → n8n → TimescaleDB → Grafana
```

## Comandos essenciais

```bash
# Python (uv é a única fonte de dependências: pyproject.toml + uv.lock)
uv sync --group dev --frozen       # instalar
uv run ruff check .                # lint (npm run lint faz o mesmo)
uv run ruff format .               # formatar (npm run format)
uv run ruff check . --fix && uv run ruff format .   # npm run fix
uv run pytest tests/ -v --tb=short # testes (mesmo comando do CI)
uv run pytest tests/test_dependencies.py::NOME -v   # um teste só

# Infra
cp .env.example .env               # preencher antes de subir (nunca commitar)
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

| Caminho                             | Papel                                                                                                                                                                                    |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `firmware/`                         | Código do ESP32-S3 (`src/main.cpp`, `platformio.ini`). O modelo Edge Impulse vai em `firmware/lib/ei-model/` (não versionado).                                                           |
| `tests/`                            | pytest. Hoje só cobre `dependencies.py`.                                                                                                                                                 |
| `dependencies.py`                   | Gerenciador de dependências baseado em `uv` (`UVDependencyManager`).                                                                                                                     |
| `timescaledb/init.sql`              | Schema: `devices`, `sound_events` (hypertable).                                                                                                                                          |
| `mosquitto/`, `grafana/`, `hermes/` | Configuração dos serviços do compose.                                                                                                                                                    |
| `.github/workflows/`                | CI: lint Python, firmware, CodeQL, segurança de Docker (Gitleaks, Grype, Trivy config, OWASP ZAP baseline), zizmor (segurança dos próprios workflows), `pio check` no firmware, release. |

## Arquitetura e limites

- Serviços ficam na rede interna `monitoring`. **O TimescaleDB não expõe porta ao host**; não adicione `ports:` a ele.
- O n8n escuta só em `127.0.0.1:5678`. Mantenha os serviços ligados a localhost. A porta 1883 só é publicada em `MQTT_BIND` (padrão loopback); o Mosquitto exige usuário (`device` publica, `n8n` assina) e ACL em `mosquitto/acl`.
- Grafana e n8n não usam o superusuário do banco: `grafana_ro` (leitura) e `n8n_app`, criados pelo `db-init` (`timescaledb/db-init.sql`). Não monte o socket do Docker no Hermes.
- Imagens são fixadas por versão e digest; atualize pelo Dependabot, não volte para `latest`.
- Tópicos MQTT: `sound/inference` e `sound/status` no firmware; o schema documenta `sound/inference/<device_id>`. Mudou um, confira os outros.
- `AUDIO_SAMPLE_RATE` (16000) e `AUDIO_WINDOW_MS` precisam coincidir com a janela do projeto Edge Impulse.
- Credenciais do firmware entram por `sysenv` (`firmware/.env` ou secrets do CI), nunca no código.

## Convenções de código

- Ruff com regras `E, F, I, B, S, UP, C4, ARG, N` (inclui segurança `S`). Imports organizados pelo Ruff; não rode `black` nem `isort`, mesmo estando no grupo `dev`.
- Python ≥ 3.11 (`.python-version`). Não crie `requirements.txt`.
- Comentários e docstrings em português, como no resto do projeto.

## Testes

- pytest em `tests/`, com `tmp_path`/`monkeypatch` e mocks de `subprocess`; sem rede e sem uv real.
- Código novo em Python precisa de teste. O CI roda `pytest` com cobertura.

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
