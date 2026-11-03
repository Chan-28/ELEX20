# HANDOFF — sessão de 2026-11-02 a 2026-11-03

Registro completo da conversa entre o usuário (usuário) e o Claude Code
na worktree `claude/platform-io-firmware-a00022`. Quem retomar o trabalho deve ler
este arquivo e depois o documento de desenho em
`docs/superpowers/specs/2026-11-03-hermes-integracoes-direcao-design.md`.

> Observação: o `.gitignore` de `main` ignora `HANDOFF.md` (PR #34). Este arquivo foi
> adicionado com `git add -f` a pedido do usuário ("não coloque ele no gitignore por
> enquanto"). O `.gitignore` não foi alterado.

## 1. Estado em uma frase

O desenho (sem código) de duas entregas está escrito e aguarda aprovação para virar
plano de implementação: (a) integrar o Hermes ao TimescaleDB e ao n8n, com cron a
pedido e análise dos sensores; (b) adaptar o firmware ao relatório do projeto (4
microfones, direção do som em 8 setores, motores, comandos, modelo YAMNet). Nada de
produto foi implementado ainda.

## 2. Pedido original e linha do tempo

1. Pergunta inicial: "como o firmware do PlatformIO funciona no meu repositório?"
   Resposta: descrição de `firmware/platformio.ini`, `firmware/src/main.cpp` e do CI
   (`.github/workflows/firmware.yml`).
2. Pedido de diagrama (archify). Foram gerados dois diagramas (ver seção 5).
3. Pedido para abrir o diagrama no Chromium (aberto via `/usr/bin/chromium-browser`).
4. "Faltou a parte do Hermes nos diagramas": o Hermes foi incluído no diagrama de
   execução; descobriu-se que ele não tem ligação nenhuma com MQTT ou banco hoje.
5. O usuário quer que o Hermes tenha: leitura do banco (um "RAG" por SQL), conexão
   bidirecional com o n8n, cron a pedido, análise de sensores/infraestrutura, e
   quer também direção do som. Fase 1 aprovada.
6. Brainstorming (skill `superpowers:brainstorming`): perguntas, leitura do PDF do
   projeto, correção de escopo, documento de desenho.
7. Correções do usuário no fim: o relatório semanal em PDF é só exemplo (cron e
   relatório não são obrigatórios); o modelo YAMNet já existe e foi treinado no Edge
   Impulse Studio (ele não sabia integrá-lo).
8. Pedido de saída: este HANDOFF, commit de tudo, push e PR.

## 3. O que o usuário decidiu (palavras dele resumidas)

- MQTT no lugar de FastAPI/WebSocket ("só causarão overhead"). Confirmado como correto.
- O Hermes só **lê** o banco. O n8n aciona o Hermes por webhook e o Hermes decide o
  que fazer. No sentido contrário (Hermes → n8n) o usuário teme que webhook não baste;
  ficou como dúvida a verificar (ver seção 8).
- Canais: Telegram, Discord e painel do Hermes ("de preferência nos três").
- Perguntas-alvo do Hermes: "os sensores estão funcionando?", "de qual direção o som
  característico está chegando?", "faça um resumo da captação dos sons hoje", e como
  exemplo "relatório semanal em PDF toda segunda às 9h no Discord/Telegram".
- A direção do som é núcleo do projeto: o firmware deve ser atualizado para o projeto
  (4 microfones, 8 direções).
- O usuário concordou com a proposta de firmware (seção 6) sem ressalvas.
- Cron e PDF não são obrigatórios: são capacidades gerais, o semanal é só um exemplo.
- O modelo de áudio já existe (YAMNet treinado no Edge Impulse Studio, dataset de ~8 h).
  O usuário não sabe integrá-lo ao código.
- Ordem de trabalho aceita: leitura do banco e estado dos sensores → n8n nos dois
  sentidos → agendamentos e relatório; firmware acompanha.

## 4. Contexto técnico do repositório (verificado nesta sessão)

### 4.1 Pipeline atual

```text
ESP32-S3 (INMP441) → MQTT (Mosquitto) → n8n → TimescaleDB → Grafana
Hermes (hermes-agent) isolado: Discord/Telegram, Ollama, Lightpanda, painel :9119
```

### 4.2 Firmware (`firmware/`)

- `platformio.ini`: ambientes `esp32s3` (padrão) e `esp32s3_debug` (liga
  `ELEX_MOCK_INFERENCE`). Placa `esp32-s3-devkitc-1`, Arduino, PSRAM `qio_opi`, 8 MB.
  Libs: `PubSubClient`, `ArduinoJson` 7. Pinos I2S: WS 42, SCK 40, SD 41. Áudio:
  16 kHz, janela 975 ms. Tópicos `sound/inference` e `sound/status` (+ `/<DEVICE_ID>`).
- `src/main.cpp`: lê 1 amostra I2S por iteração do `loop()` (`>> 14` para 16 bits),
  enche um buffer na PSRAM e, ao completar a janela, chamaria `runInference()`
  (hoje **comentado**; só o ambiente debug publica o mock com `"mock": true`).
  Heartbeat a cada 5 s com `uptime_s`, `heap`, `rssi` (retain).
- Credenciais: o PR #33 (já em `main`) trocou o `${sysenv.*}` por
  `firmware/load_env.py`, que lê o ambiente ou `firmware/.env` e **falha o build** se
  faltar credencial. `firmware/.pio/` agora está no `.gitignore`.
- CI: `.github/workflows/firmware.yml` (build com credenciais `CI_DUMMY`, `pio check`).
- O firmware tem **1 microfone**, sem direção, sem urgência, sem motores e sem
  assinatura de comandos.

### 4.3 Banco (`timescaledb/`)

- `init.sql` (só roda em volume vazio): `devices`, `sound_events` (hypertable),
  `sound_events_hourly` (agregação contínua), retenção de 90 dias.
- `db-init.sql` (roda a cada subida): papéis `grafana_ro` (somente leitura) e `n8n_app`,
  banco do n8n, constraints de validação (`label` ≤ 64, `device_id` regex, etc.).
- `sound_events` **não tem** colunas de direção, setor ou urgência. O heartbeat
  (`sound/status`) **não é gravado** em lugar nenhum.

### 4.4 Mosquitto (`mosquitto/acl`)

- `device`: escreve `sound/inference/+` e `sound/status/+`. `n8n`: lê `sound/#`.
- Não existe usuário do Hermes (e não deve existir; ver decisões).

### 4.5 n8n

- Serviço em `docker-compose.yaml`, só em `127.0.0.1:5678`, banco próprio
  (`n8n_app`). **Os workflows não estão versionados** (não há pasta `n8n/`), embora o
  `init.sql` diga que `sound_events` é populada por um workflow.

### 4.6 Hermes

- Serviço `hermes-agent` (imagem `nousresearch/hermes-agent:v0.22.5@sha256:…`),
  comando `gateway run`, painel em `127.0.0.1:9119`, dados em `./hermes_data`,
  `hermes/config.jsonc` montado como `/opt/data/config.json:ro`.
- Variáveis: `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL`, `OPENROUTER_API_KEY`, tokens do
  Discord/Telegram, allowlists (`TELEGRAM_ALLOWED_USERS`, `DISCORD_ALLOWED_USERS`),
  SMTP/IMAP, usuário e senha do painel.
- O socket do Docker **não** é montado (decisão de segurança do PR #24). Terminal
  `local`. Ollama e Lightpanda na rede interna.
- **Achado importante:** a documentação do Hermes diz que a configuração é
  `~/.hermes/config.yaml` (YAML), com outras chaves. O `config.jsonc` do repositório
  provavelmente **não é lido**. Isso nunca foi testado no container (o relatório de
  auditoria já avisava que não se verificou se o Hermes honra `terminal.backend: local`
  nem as allowlists).
- O `CLAUDE.md`/`AGENTS.md` descrevem o Hermes como agente de conexões bidirecionais,
  mas no código ele **não** tem ligação com MQTT nem com o banco.

### 4.7 `training/` (entrou em `main` pelo PR #35)

- Pipeline YAMNet com transfer learning: YAMNet congelado + cabeça **Dense** (pool
  médio, sons estacionários) ou **Conv1D** (sequência temporal); exporta TFLite
  float32 e INT8. É um bloco de aprendizado customizado do Edge Impulse
  (`parameters.json`, `Dockerfile`, `.ei-block-config` com organização 516485 e
  projeto 9258).
- Aviso do próprio `train.py`: o TFLite exportado tem **só a cabeça**; o projeto do
  Studio precisa usar o bloco DSP **"Raw audio"** (não MFCC/MFE) para o Studio embutir
  o YAMNet na biblioteca Arduino. Credenciais Kaggle por `KAGGLE_USERNAME`/`KAGGLE_KEY`.
- Janela nativa do YAMNet: 15.600 amostras a 16 kHz = 975 ms, igual ao
  `AUDIO_WINDOW_MS=975` do firmware.
- A lista de classes **não está no repositório** (vem do dataset no Studio).

## 5. Diagramas gerados (archify) — arquivos na pasta `.archify/`

- `.archify/architecture-firmware-build-20261102-235242/firmware-build.html`:
  `.env` / secrets do CI → sysenv → `platformio.ini` → `pio run` → `firmware.bin` →
  upload ao ESP32-S3 (+ artefato do CI). **Desatualizado:** foi feito antes do PR #33
  (ainda mostra `${sysenv}`; hoje o caminho é `load_env.py`).
- `.archify/architecture-firmware-runtime-20261102-235242/firmware-runtime.html`:
  microfone → I2S → buffer → inferência → MQTT → Mosquitto → n8n → TimescaleDB →
  Grafana, mais Hermes, Ollama, Lightpanda e canais de chat. Mostra em card que o
  Hermes não tem ligação com o pipeline.
- Cada pasta tem `candidate.json` (fonte editável) e recibos (`*.finalize*.json`,
  `review-*`).
- Verificação: validação, entrega e checagem estrutural passaram; a checagem no
  navegador passou usando `ARCHIFY_CHROME` apontando para o Chromium do Playwright
  (`~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`). O Chromium do snap
  não serve para a automação. **Não houve revisão visual por capturas de tela.**
- A interface do visualizador fica em inglês (o archify não tem catálogo `pt-BR`).
- Não foram ancorados em linhas de código (`meta.repository`).
- Para regenerar:
  `ARCHIFY_CHROME=<chrome> node ~/.claude/skills/archify/bin/archify.mjs finalize architecture <candidate.json> <saida.html> --quality showcase --out-dir <pasta>/review-N --json`
  (um `--out-dir` novo a cada rodada depois da primeira checagem no navegador).

## 6. Proposta de firmware aprovada pelo usuário

- **Microfones**: 4 INMP441 (frente, direita, trás, esquerda) em faixa na cabeça
  (relatório). ESP32-S3 com dois controladores I2S: I2S0 mestre lê (frente, trás),
  I2S1 escravo, com o mesmo BCLK/WS, lê (direita, esquerda). Pinos configuráveis;
  GPIO 33–37 ficam reservados à PSRAM octal.
- **Direção**: GCC-PHAT nos 6 pares, mínimos quadrados para o azimute, interpolação
  parabólica do pico (a 16 kHz o atraso máximo é só ~8 amostras com raio de 9 cm),
  8 setores de 45° (Marco 3 do relatório), só quando há som de alerta acima do limiar.
- **Mensagem MQTT**: `inference` ganha `direction_deg`, `sector`, `doa_confidence`.
- **Comandos**: assina `sound/cmd/<device_id>` (sensibilidade, limiar), validados
  contra faixas fixas.
- **Motores**: 4 saídas PWM (LEDC) + MOSFET AO3400A, motor do setor mais próximo.
- **Testes**: biblioteca de direção sem dependência de hardware, testada no ambiente
  `native` do PlatformIO (Unity) com sinais sintéticos.
- **Modelo**: biblioteca exportada do Studio (Deployment → Arduino library) em
  `firmware/lib/ei-model/` (não versionada); o firmware passa a usar
  `EI_CLASSIFIER_RAW_SAMPLE_COUNT` e `EI_CLASSIFIER_FREQUENCY`; `runInference()`
  substitui o mock.
- **Limite honesto**: precisão real da direção, alinhamento entre os dois I2S e efeito
  dos motores só se validam no protótipo. Aqui valem build e testes sintéticos.

## 7. Proposta do lado do servidor (decisões minhas, a revisar)

- Papel `hermes_ro` (somente leitura, `statement_timeout`) e ferramentas de consulta
  parametrizadas expostas por um servidor MCP pequeno do repositório (nada de SQL
  livre). O Hermes usa `mcp_servers` com `tools.include`.
- Colunas novas em `sound_events`: `direction_deg`, `sector`, `doa_confidence`,
  `urgency`. Tabela `sound_classes(label, urgency)` com os rótulos do modelo.
- `device_status` (hypertable, retenção de 30 dias) e a view `device_last_status`,
  alimentadas pelo n8n a partir de `sound/status/+`.
- Migração idempotente em `timescaledb/db-init.sql` (o `init.sql` só roda em volume
  vazio).
- Workflows do n8n versionados em `n8n/workflows/`.
- Comandos ao dispositivo: tópico `sound/cmd/<device_id>`; `n8n` escreve, `device` lê o
  seu. O Hermes **nunca** publica no MQTT; passa pelo n8n, que valida faixa e tipo.
- n8n → Hermes: webhook assinado com HMAC (`X-Webhook-Signature`), porta 8644 só na
  rede interna. Hermes → n8n: webhook do n8n com header de autenticação, ou MCP do n8n
  (nó MCP Server Trigger), a verificar.
- Cron: o cron **nativo** do Hermes (`/cron add`, linguagem natural, `--deliver
  telegram|discord`, exige o gateway rodando). Relatórios: gerador determinístico em
  `hermes/reports/`, chamado sob demanda.
- Fuso do cron: `America/Sao_Paulo` (escolha minha). IDs dos chats
  (`TELEGRAM_HOME_CHANNEL`, `DISCORD_HOME_CHANNEL`) ficam no `.env` do usuário.
- Webhook "não ser suficiente": para tarefas longas, o n8n responde "recebi o job X" e
  entrega o resultado depois no chat ou chamando o Hermes de volta.

## 8. A verificar antes de implementar (lista aberta)

1. Qual arquivo de configuração o Hermes `v0.22.5` realmente lê no container e onde
   (`/opt/data/config.yaml`?). Corrigir ou remover `hermes/config.jsonc`.
2. Se o webhook do Hermes sobe na 8644 com `gateway run` e como declarar rotas/entrega.
3. Se o MCP do n8n funciona com `mcp_servers.url` + `headers`; se não, webhooks do n8n.
4. Como um job de cron declara anexo (PDF) na entrega.
5. Se o container do Hermes tem Python para o servidor MCP e o gerador de PDF.
6. Lista de classes do modelo (projeto 9258 no Studio).
7. Se o YAMNet exportado cabe no ESP32-S3 (RAM, flash, latência) junto com a direção.
8. Se o projeto do Studio usa "Raw audio" como bloco DSP (necessário para embutir o
   YAMNet).

Fontes consultadas sobre o Hermes (documentação oficial):
<https://hermes-agent.nousresearch.com/docs/user-guide/features/cron>,
<https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp>,
<https://hermes-agent.nousresearch.com/docs/user-guide/configuration>,
<https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks>.
Alguns detalhes vieram de espelhos e de páginas truncadas; conferir na documentação.

## 9. Relatório do projeto (PDF "Relatório_ELEX20_2026_2")

- Título: "Sistema de Percepção Sonora Háptica" (Oficina de Integração 1, 2026/2).
  Autores: Autores omitidos.
- Sistema vestível: 4 INMP441 numa faixa ao redor da cabeça, ESP32-S3, TinyML (Edge
  Impulse), 4 motores de vibração 1027 ERM com MOSFET AO3400A por PWM, bateria LiPo.
- Servidor local em Docker: o relatório cita FastAPI + WebSocket + TimescaleDB + Grafana
  + n8n + Ollama + Hermes Agent. **O usuário decidiu ignorar FastAPI/WebSocket**; o
  repositório usa MQTT.
- Papel do Hermes no relatório: analisar registros em busca de **falsos positivos** e
  traduzir pedidos em linguagem natural em configurações técnicas (ex.: sensibilidade
  do ESP32). O n8n faz as rotinas agendadas (ex.: resumo diário) e recebe webhooks do
  chat.
- Registro previsto: timestamp, id, tipo do som, confiança, nível de urgência e
  **direção**.
- Marcos: M1 áudio/RMS e controle PWM dos motores; M2 classificação embarcada,
  comunicação bidirecional, sons simultâneos; M3 direção em pelo menos 8 pontos
  cardeais, integração com os motores, testes de ruído e de falso positivo.
- Questão em aberto no relatório: como o usuário reconhece os padrões de vibração.

## 10. Arquivos criados ou alterados nesta sessão (no PR)

- `docs/superpowers/specs/2026-11-03-hermes-integracoes-direcao-design.md`: documento
  de desenho (rascunho para aprovação).
- `.archify/`: dois diagramas e seus recibos.
- `HANDOFF.md`: este arquivo.
- Nenhum código de produto, nenhuma alteração em `docker-compose.yaml`, banco, ACL,
  n8n ou firmware.

## 11. Próximos passos

1. O usuário revisa o documento de desenho e responde "sim" (ou corrige).
2. Invocar `superpowers:writing-plans` com o documento aprovado.
3. Executar na ordem da seção "Ordem de entrega" do documento (verificar o Hermes →
   banco/n8n → firmware → ponte MCP/webhook → cron/relatório → smoke e diagramas).
4. Atualizar `scripts/infra-smoke.sh` para cobrir `hermes_ro` e a nova ACL.
5. Regenerar os diagramas (o de build está desatualizado) e incluir o Hermes ligado
   ao banco e ao n8n.
6. Pedir ao usuário o nome do projeto/lista de classes do Studio e confirmar o
   export (Deployment → Arduino library, bloco "Raw audio").

## 12. Dicas de ambiente e armadilhas desta sessão

- WSL2, shell zsh. Para abrir páginas: `/usr/bin/chromium-browser` (snap) funciona via
  WSLg; para automação do archify use o Chromium do Playwright em `ARCHIFY_CHROME`.
- Hooks do ambiente (GateGuard) exigem declarar fatos antes do primeiro Bash e de
  cada novo arquivo criado ou editado.
- `pkill -f 'snap/chromium'` mata o próprio shell; não use.
- Sem `pdftoppm`: o PDF foi lido com `uv run --no-project --with pypdf` na pasta
  temporária da sessão.
- Não rodar `docker compose down -v`; não commitar `.env`; não editar `uv.lock` à mão;
  não expor portas do banco; comentários em português; Conventional Commits.
- O usuário escreve em português; manter as respostas em português.
- O usuário mencionou "algumas notas em anexo" no fim, mas nenhum anexo chegou; foi
  pedido que reenvie se existirem.

## 13. Git

- Branch: `claude/platform-io-firmware-a00022` (a partir de `main` em `5594f7bf`, que já
  inclui os PRs #33 load_env, #34 ignora HANDOFF.md e #35 training).
- PR #32 (relatório de auditoria) e #33 (credenciais do firmware) foram aceitos antes
  desta sessão terminar.
