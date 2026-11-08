# Changelog

Mudanças de cada release do ELEX20. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e as versões, o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Toda release precisa de uma seção aqui antes da tag: o workflow de release falha sem ela e usa o texto da seção como notas da release no GitHub.

## [Não lançado]

### Removido

- Arquivos de sessões antigas que não pertenciam ao projeto: `HANDOFF.md`, `docs/superpowers/` (desenho já implementado na v1.0.0), `.archify/` (diagramas gerados por ferramenta, agora ignorados) e `.husky/.huky`.
- Dependências Python que nenhum código usa: `psycopg2-binary`, `aiohttp`, `pandas`, `colorama`, `python-dotenv`, `typing-extensions`, `uvloop` e `winloop`, e as ferramentas de desenvolvimento `black`, `isort`, `mypy` e `scipy-stubs` (o Ruff já organiza imports e formata).

### Corrigido

- `.vscode/settings.json` usava o unittest; agora roda os testes com o pytest e formata com o Ruff.

## [1.2.0] - 2026-11-08

Corrige o broker MQTT, que travava no reinício (o executável da v1.1.0 ainda tem esse problema), padroniza os rótulos em inglês e acrescenta observabilidade, métricas de desempenho do sensor e ferramentas de debug.

### Corrigido

- O Mosquitto entrava em loop de reinício depois de qualquer reinício do container (`File exists` ao recriar o arquivo de senhas). Com o broker fora, a ingestão do n8n parava. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- O instalador destrava o gatilho MQTT do n8n que fica preso quando falha ao ativar com o broker fora: ele despublica cada workflow antes de publicar. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- A varredura agendada de segredos (Gitleaks) falhava todo dia com falsos positivos de pastas legadas do histórico. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- A tela do dispositivo do instalador aceitava qualquer valor com o Wi-Fi desligado. ([#60](https://github.com/Chan-28/ELEX20/pull/60))

### Alterado

- **Rótulos em inglês** (`siren`, `horn`, `gunshot_explosion`…) no firmware, no banco e nos alertas. Modelos treinados antes da troca seguem funcionando: o firmware traduz os nomes em português. Na subida, o banco migra os eventos já gravados e restaura as urgências da lista. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- Imagens do TimescaleDB, do n8n, do Grafana e do Loki fixadas também por digest, e a varredura de vulnerabilidades passa a ler as imagens do próprio compose. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- Pyroscope removido da stack: nenhum serviço enviava perfis para ele. ([#59](https://github.com/Chan-28/ELEX20/pull/59))

### Adicionado

- **Instalador:** opção para colocar um modelo do Edge Impulse no firmware (no assistente ou com `--ei-model ARQUIVO`). Ela recusa modelos fora de 16 kHz e avisa sobre rótulos desconhecidos. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- **Métricas de desempenho do sensor** no heartbeat e no banco: tempo por janela, tempos do Edge Impulse, memória, folga de pilha, reconexões, descartes e temperatura. O Hermes passa a informar latência e temperatura. ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- **Observabilidade no Grafana:** logs dos containers pelo Loki, painel com o estado dos sensores e alertas de sensor sem heartbeat, ingestão parada e container em loop de reinício. ([#59](https://github.com/Chan-28/ELEX20/pull/59))
- **Pasta `debug/`:** firmware de bancada e `mic_check.py` (qualidade e ordem dos microfones, gravação em WAV, teste dos motores), `simulate_sensor.py` (sensores simulados no MQTT) e `sensor_health.py` (saúde dos sensores ao longo do tempo). ([#60](https://github.com/Chan-28/ELEX20/pull/60))
- Guias [de instalação](docs/install.md) e [de debug](docs/debug.md), cada um com uma parte de hardware e outra de software.

### Para atualizar

Rode o instalador da v1.2.0 na mesma pasta, ou, num clone, `git pull` e `./install.sh`. A subida migra o banco sozinha. Grave o firmware de novo (`pio run -e esp32s3_model -t upload`) para ter os rótulos em inglês e as métricas de desempenho. O firmware antigo continua gravando, sem as métricas.

## [1.1.0] - 2026-11-07

### Adicionado

- Instalador em tela cheia (Textual) com desinstalação segura. ([#58](https://github.com/Chan-28/ELEX20/pull/58))
- Classificação e vibração seguem funcionando sem rede, com reconexão por recuo exponencial. ([#50](https://github.com/Chan-28/ELEX20/pull/50))
- Modelo de 14 categorias de som e dataset ampliado. ([#42](https://github.com/Chan-28/ELEX20/pull/42), [#43](https://github.com/Chan-28/ELEX20/pull/43))

### Corrigido

- Rótulos do modelo alinhados entre firmware e banco, e biblioteca do modelo incluída no build. ([#55](https://github.com/Chan-28/ELEX20/pull/55))
- Treino e teste separados pelo autor do Freesound, para não vazar gravações entre os dois. ([#51](https://github.com/Chan-28/ELEX20/pull/51))

### Alterado

- Nomes de arquivos e flags em inglês, README centrado no sensor e guia de referência. ([#49](https://github.com/Chan-28/ELEX20/pull/49), [#56](https://github.com/Chan-28/ELEX20/pull/56))

## [1.0.0] - 2026-11-04

Primeira release: firmware do ESP32-S3 com estimativa de direção do som e motores, stack em Docker (Mosquitto, n8n, TimescaleDB, Grafana e Hermes) e instalador multiplataforma assinado. ([#37](https://github.com/Chan-28/ELEX20/pull/37))

[Não lançado]: https://github.com/Chan-28/ELEX20/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Chan-28/ELEX20/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Chan-28/ELEX20/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Chan-28/ELEX20/releases/tag/v1.0.0
