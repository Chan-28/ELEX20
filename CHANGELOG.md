# Changelog

Mudanças de cada release do ELEX20. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e as versões, o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Toda release precisa de uma seção aqui antes da tag: o workflow de release falha sem ela e usa o texto da seção como notas da release no GitHub.

## [Não lançado]

### Corrigido

- O painel "Últimos eventos" do Grafana não mostrava a direção do som, que o banco já gravava. Agora exibe a direção (N a NO), o ângulo, a confiança da direção e a urgência.

## [1.3.0] - 2026-11-08

Corrige o texto dos alertas do Grafana, que falhava nos três alertas (o executável da v1.2.0 ainda tem esse problema), elimina o heartbeat falso de sensores desligados e permite conectar o sensor a redes Wi-Fi institucionais, como o eduroam.

### Corrigido

- Os três alertas do Grafana falhavam ao montar o texto (`$values.A` não existe para consultas). Agora uma expressão de redução `B` alimenta o limiar e a mensagem, por exemplo "Sensor esp32s3-sound-01 sem heartbeat há 7m 9s". ([#63](https://github.com/Chan-28/ELEX20/pull/63))
- Heartbeat falso de sensor desligado: o firmware publicava `sound/status` com retain, e a cada reconexão do n8n ao broker (reinício, republicação do workflow) o Mosquitto reentregava o último status de cada sensor, gravado em `device_status` com a hora atual. Isso atrasava o alerta "Sensor sem heartbeat". O status deixa de ser retido, e o firmware apaga ao conectar o status retido por versões anteriores (payload vazio, que o n8n descarta). ([#64](https://github.com/Chan-28/ELEX20/pull/64))
- O simulador publicava o status com `retain`: a cada reconexão do n8n, o broker reentregava a mensagem e um sensor simulado já parado ganhava um heartbeat novo. Ele deixa de reter, e o `--cleanup` apaga também as mensagens retidas. ([#63](https://github.com/Chan-28/ELEX20/pull/63))
- A referência mandava gravar o firmware sem modelo (`esp32s3`) e tratava `[EI] Sem modelo` como esperado; agora orienta `esp32s3_model`. O README cita a opção do modelo no instalador e o teste de bancada. ([#62](https://github.com/Chan-28/ELEX20/pull/62))
- Versões alinhadas em 1.2.0 no `pyproject.toml` e no `package.json` (estavam em 0.2.0 e 1.0.0); um teste confere que acompanham o CHANGELOG. ([#62](https://github.com/Chan-28/ELEX20/pull/62))
- `AGENTS.md` atualizado (estrutura, testes e regra de versão na release), nota obsoleta sobre os nomes da v1.0.0 removida da referência e aviso sobre os rótulos antigos no histórico do modelo. ([#62](https://github.com/Chan-28/ELEX20/pull/62))
- `.vscode/settings.json` usava o unittest; agora roda os testes com o pytest e formata com o Ruff. ([#62](https://github.com/Chan-28/ELEX20/pull/62))

### Adicionado

- Wi-Fi institucional (WPA2-Enterprise, como o eduroam) no firmware, com PEAP ou TTLS. Ele entra quando `firmware/.env` define `WIFI_EAP_USER`; `WIFI_PASS` passa a ser a senha desse usuário. O certificado da CA da rede (`WIFI_EAP_CA_FILE`) é opcional, mas o build avisa sem ele, porque aí o sensor não confere o servidor. O instalador mantém essas linhas ao regravar o `firmware/.env`, e a referência explica as restrições comuns dessas redes (portal cativo, isolamento entre clientes, porta 1883 bloqueada). ([#65](https://github.com/Chan-28/ELEX20/pull/65))

### Alterado

- Nomes de workflows e jobs do CI padronizados em inglês, e comentários vindos dos modelos do GitHub traduzidos. O workflow "Docker Security & Deploy" passa a se chamar "Docker Security", porque não faz deploy. ([#62](https://github.com/Chan-28/ELEX20/pull/62))

### Removido

- Arquivos de sessões antigas que não pertenciam ao projeto: `HANDOFF.md`, `docs/superpowers/` (desenho já implementado na v1.0.0), `.archify/` (diagramas gerados por ferramenta, agora ignorados) e `.husky/.huky`. ([#62](https://github.com/Chan-28/ELEX20/pull/62))
- Dependências Python que nenhum código usa: `psycopg2-binary`, `aiohttp`, `pandas`, `colorama`, `python-dotenv`, `typing-extensions`, `uvloop` e `winloop`, e as ferramentas de desenvolvimento `black`, `isort`, `mypy` e `scipy-stubs` (o Ruff já organiza imports e formata). ([#62](https://github.com/Chan-28/ELEX20/pull/62))

### Para atualizar

Rode o instalador da v1.3.0 na mesma pasta, ou, num clone, `git pull` e `./install.sh`, para receber os alertas corrigidos. Grave o firmware de novo (`pio run -e esp32s3_model -t upload`) para acabar com o heartbeat falso; o firmware novo apaga sozinho o status retido pelas versões anteriores. Para usar uma rede institucional, veja [Wi-Fi institucional](docs/reference.md#wi-fi-institucional).

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

[Não lançado]: https://github.com/Chan-28/ELEX20/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/Chan-28/ELEX20/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Chan-28/ELEX20/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Chan-28/ELEX20/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Chan-28/ELEX20/releases/tag/v1.0.0
