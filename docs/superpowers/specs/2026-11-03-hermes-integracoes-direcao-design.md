# Hermes integrado ao pipeline e firmware com direção do som

Data: 2026-11-03 · Status: rascunho para aprovação

## Intenção

O ELEX20 é um sistema de percepção sonora háptica para pessoas surdas ou com
deficiência auditiva (relatório "Oficina de Integração 1", 2026/2). Hoje o
repositório tem o caminho ESP32 → MQTT → n8n → TimescaleDB → Grafana, e o Hermes
roda isolado: não enxerga os dados, não conversa com o n8n e o firmware não faz
nada do que o relatório pede (um microfone, sem direção, sem motores).

O objetivo é fechar o projeto como o relatório o descreve:

- O usuário conversa com o Hermes (Telegram, Discord e painel) e obtém respostas
  sobre os sons captados e a saúde dos sensores.
- O Hermes consulta o banco, aciona ações no n8n e agenda tarefas pedidas pelo
  usuário (ex.: relatório semanal em PDF).
- O n8n avisa o Hermes quando algo acontece (alertas) e o Hermes decide o que
  fazer.
- O firmware tem 4 microfones, estima a direção do som em 8 setores e aciona o
  motor correspondente.

## Objetivos

1. **Hermes lê o banco** com um papel somente leitura e ferramentas de consulta
   pré-definidas, sem SQL livre.
2. **Ponte bidirecional Hermes ↔ n8n**: n8n → Hermes por webhook assinado; Hermes
   → n8n por ações determinísticas (webhook ou MCP, ver "A verificar").
3. **Agendamentos a pedido do usuário** com o cron nativo do Hermes, com entrega
   no Telegram ou no Discord. É uma capacidade geral: nada é agendado por padrão.
4. **Relatórios sob demanda**: o Hermes consegue gerar um relatório (inclusive em
   PDF) quando o usuário pedir, agendado ou não. "Relatório semanal em PDF toda
   segunda às 9h" é só um exemplo de uso, não um requisito.
5. **Modelo de áudio integrado**: o modelo YAMNet já treinado no Edge Impulse
   Studio passa a rodar no firmware no lugar do mock.
5. **Análise dos sensores**: "os sensores estão funcionando?", respondida com
   dados reais de heartbeat (última vez visto, RSSI, heap, atraso dos eventos).
6. **Direção do som**: firmware com 4 INMP441, estimativa por GCC-PHAT, 8 setores
   de 45°, publicada no MQTT, gravada no banco e consultável pelo Hermes.
7. **Feedback háptico** no firmware: motor correspondente ao setor quando um som
   de alerta é detectado.
8. **Comandos para o dispositivo** por MQTT (sensibilidade, limiares), disparados
   pelo n8n a pedido do Hermes.

## Não objetivos

- Não adicionar FastAPI nem WebSocket. O MQTT cobre os dois sentidos.
- Não dar ao Hermes escrita no banco, acesso direto ao MQTT nem o socket do Docker.
- Não controlar containers nem o host pelo Hermes.
- Não retreinar o modelo: ele já foi treinado no Edge Impulse Studio (YAMNet, ~8 h
  de dataset). Aqui só se integra ao firmware.
- Não definir o significado dos padrões de vibração para o usuário (questão em
  aberto no relatório).
- Não criar app móvel, integração com WhatsApp, e-mail ou Notion.

## Anti-objetivos (falha mesmo que "funcione")

- O Hermes executar qualquer ação com efeito que não esteja numa lista fechada.
- Texto vindo de fora (chat, web, rótulos MQTT) virar comando ou SQL.
- Segredos (tokens, senhas, HMAC) no código, na imagem ou no git.
- Prometer precisão de direção sem validação com o protótipo.

## Restrições

- Serviços na rede interna `monitoring`; nenhuma porta nova publicada além de
  loopback. A porta do webhook do Hermes (8644) não vai para o host.
- Mosquitto com usuário e ACL; TimescaleDB sem porta no host.
- Imagens fixadas por versão e digest. O Hermes está em `v0.22.5`.
- Python só com `uv`; firmware em PlatformIO; comentários em português;
  Conventional Commits.
- Credenciais do firmware entram pelo ambiente de build, nunca no código.

## O que o usuário decidiu

- MQTT em vez de FastAPI/WebSocket.
- Hermes só lê o banco. n8n aciona o Hermes por webhook e o Hermes decide.
- Canais: Telegram, Discord e painel.
- Perguntas-alvo: "os sensores estão funcionando?", "de qual direção o som está
  chegando?", "resumo da captação dos sons hoje", relatório semanal em PDF na
  segunda às 9h no Discord/Telegram (este último é um exemplo, não obrigatório).
- A direção do som é núcleo: o firmware deve ser adaptado ao projeto (4
  microfones, 8 setores, motores, comandos).
- Ordem de trabalho: leitura do banco e estado dos sensores, depois n8n nos dois
  sentidos, depois agendamentos e PDF; o firmware acompanha.

## Decisões minhas (a revisar)

- **Banco**: papel `hermes_ro` (`default_transaction_read_only`, `statement_timeout`),
  com `SELECT` em `devices`, `sound_events_hourly`, `device_status` e views novas.
  O Hermes acessa por um servidor MCP pequeno do repositório com ferramentas
  parametrizadas, e o `tools.include` do Hermes lista só essas.
- **Colunas novas em `sound_events`**: `direction_deg` (SMALLINT), `sector` (TEXT,
  `N`, `NE`, `E`, `SE`, `S`, `SO`, `O`, `NO`, relativos à frente da cabeça),
  `doa_confidence` (FLOAT4), `urgency` (SMALLINT). Urgência vem de uma tabela
  `sound_classes(label, urgency)` aplicada pelo n8n, preenchida com os rótulos do
  modelo treinado (a lista de classes vem do projeto no Edge Impulse Studio).
- **Estado dos sensores**: o n8n assina `sound/status/+` e grava em `device_status`
  (hypertable, retenção de 30 dias) e a view `device_last_status`.
- **Migração**: `timescaledb/init.sql` só roda em volume vazio, então as mudanças
  entram também de forma idempotente em `timescaledb/db-init.sql`, que roda a cada
  subida.
- **Workflows do n8n versionados** em `n8n/workflows/` (hoje o workflow de ingestão
  não está no repositório).
- **Comandos ao dispositivo**: tópico `sound/cmd/<device_id>`. O usuário `n8n`
  ganha `write` nesse tópico; o `device` ganha `read` só no seu. O Hermes nunca
  publica; passa pelo n8n, que valida faixa e tipo.
- **Relatórios**: um gerador determinístico no repositório (`hermes/reports/`) que o
  Hermes pode chamar quando o usuário pedir, usando `hermes_ro`; ele produz o PDF e
  o Hermes escreve só o texto do resumo. Cron e relatório são independentes: o
  usuário pode pedir um sem o outro, e o exemplo semanal é só uma combinação.
- **Direção**: GCC-PHAT em 6 pares de microfones, mínimos quadrados para o
  azimute, interpolação parabólica do pico, só calculada quando há som de alerta
  acima do limiar.
- **Firmware testável**: o cálculo de direção fica numa biblioteca sem dependência
  de hardware, com testes no ambiente `native` do PlatformIO (sinais sintéticos).

## Arquitetura

```text
INMP441 x4 → ESP32-S3 (I2S0 mestre + I2S1 escravo, clock compartilhado)
  ├─ mixagem mono 16 kHz → Edge Impulse (ou mock) → classe + confiança
  ├─ GCC-PHAT → direção (setor) ─┬→ motor correspondente (PWM/MOSFET)
  │                              └→ MQTT sound/inference/<id>
  ├─ heartbeat → MQTT sound/status/<id>
  └─ assina sound/cmd/<id> (sensibilidade, limiar)

Mosquitto → n8n ┬→ sound_events (com direção e urgência)
                ├→ device_status
                ├→ webhook assinado → Hermes (alertas)
                └→ publica sound/cmd/<id> (a pedido do Hermes)

Hermes ┬→ MCP de consulta (hermes_ro) → TimescaleDB
       ├→ ações no n8n (lista fechada)
       ├→ cron nativo → relatório PDF → Telegram/Discord
       └→ conversa com o usuário (Telegram, Discord, painel)
```

## Firmware

- **I2S**: dois controladores. I2S0 mestre lê o par (frente, trás); I2S1 escravo,
  com o mesmo BCLK/WS, lê o par (direita, esquerda). Pinos configuráveis em
  `platformio.ini`; os pinos 33-37 ficam reservados à PSRAM octal.
- **Geometria**: 4 microfones a 0°, 90°, 180° e 270° numa faixa de raio configurável
  (padrão 9 cm). Referência: 0° é a frente do usuário.
- **Direção**: janela curta (≈ 512 amostras) em torno do pico de energia, FFT
  própria (sem dependência), PHAT, pico interpolado, azimute por mínimos quadrados
  e confiança pelo pico normalizado. Saída: graus, setor (45°) e confiança.
- **Alinhamento**: calibração do desvio entre I2S0 e I2S1 por comando e parâmetro
  de compilação; precisa de medição no protótipo.
- **Motores**: 4 saídas PWM (LEDC) com MOSFET; intensidade por urgência e setor
  mais próximo, com limite de duração para evitar vibração contínua.
- **Modelo**: biblioteca exportada pelo Studio (Deployment → Arduino library) em
  `firmware/lib/ei-model/`. O firmware passa a usar `EI_CLASSIFIER_RAW_SAMPLE_COUNT`
  e `EI_CLASSIFIER_FREQUENCY` do modelo em vez de valores fixos, e o `runInference()`
  substitui o mock. O `training/train.py` avisa que o TFLite exportado tem só a
  cabeça: o projeto do Studio precisa usar o bloco DSP "Raw audio" (não MFCC/MFE),
  e então o Studio embute o YAMNet na biblioteca exportada. A janela de 975 ms atual coincide com a do YAMNet (15.600
  amostras a 16 kHz). A inferência usa um canal mono (mistura dos 4 microfones ou
  um de referência, a decidir nos testes).
- **Mensagem**: `inference` ganha `direction_deg`, `sector`, `doa_confidence`;
  mantém `mock:true` nas leituras simuladas.
- **Comandos**: JSON com chave e valor validados contra faixas fixas; comando
  inválido é ignorado e registrado no serial.
- **Testes**: ambiente `native` com Unity; casos com atrasos sintéticos nos 8
  setores, ruído, pico fraco e sinal sem direção; build `esp32s3` e
  `esp32s3_debug` no CI.

## Hermes

- Configuração real em `config.yaml` (confirmar o caminho no container); remover
  ou converter o `config.jsonc` atual.
- `mcp_servers`: um servidor de consulta ao banco (stdio, no próprio container) e,
  se confirmado, o MCP do n8n para as ações.
- Webhook de entrada com assinatura HMAC (`X-Webhook-Signature`), rota por tipo de
  alerta, entrega no chat configurado.
- Cron nativo: `/cron add` e pedido em linguagem natural; `--deliver` para
  `telegram` e `discord`; variáveis `TELEGRAM_HOME_CHANNEL` e `DISCORD_HOME_CHANNEL`.
- Allowlists de usuários mantidas; sem `GATEWAY_ALLOW_ALL_USERS`.

## Segurança

- `hermes_ro` sem escrita e com limite de tempo; ferramentas com parâmetros
  tipados, intervalo máximo de datas e limite de linhas.
- Webhook do n8n com autenticação por header; webhook do Hermes com HMAC; segredos
  só em `.env`.
- Rótulos vindos do MQTT já têm `CHECK` de tamanho; tratar como dado não confiável
  no contexto do modelo.
- ACL do Mosquitto estendida e coberta por `scripts/infra-smoke.sh`.
- Comandos ao dispositivo validados no n8n e de novo no firmware.

## A verificar antes de implementar

1. Qual arquivo de configuração o container do Hermes `v0.22.5` realmente lê, e
   onde (`/opt/data/config.yaml`?).
2. Se o webhook do Hermes sobe na porta 8644 com `gateway run` e como declarar
   rotas e entrega.
3. Se o MCP do n8n (nó MCP Server Trigger) funciona com `mcp_servers.url` e
   `headers`; se não, usar webhooks do n8n com uma ferramenta HTTP.
4. Como um job de cron declara o anexo do PDF na entrega.
5. Se o container do Hermes tem Python para o servidor MCP e para o gerador do PDF
   (ou se isso exige uma imagem própria).
6. A lista de classes do modelo. O pipeline de treino já está em `training/`
   (`train.py`, `parameters.json`, `.ei-block-config`, PR #35): é um bloco de
   aprendizado customizado do Edge Impulse (YAMNet congelado + cabeça Dense ou
   Conv1D). O projeto do Studio é o `id` 9258 da organização 516485. As classes
   saem do dataset do Studio e não estão no repositório.
7. Se o YAMNet exportado cabe no ESP32-S3 (RAM, flash e latência; o Studio mostra a
   estimativa na tela de Deployment) e se roda junto com o cálculo de direção.

## Ordem de entrega

1. Verificar o Hermes e corrigir sua configuração.
2. Banco (`hermes_ro`, colunas, `device_status`) e workflows de ingestão do n8n.
3. Firmware: integração do modelo do Edge Impulse, biblioteca de direção com
   testes, 4 microfones, mensagem, comandos e motores.
4. Servidor MCP de consulta e ponte n8n ↔ Hermes (webhooks, ACL, comandos).
5. Cron a pedido e gerador de relatório sob demanda (o semanal é só um exemplo de
   teste).
6. Smoke de infraestrutura, documentação e diagramas atualizados.

## Deixado ao construtor

Nomes de funções e tabelas auxiliares, layout do PDF, texto das mensagens, escolha
da biblioteca de PDF e formato exato do JSON dos comandos, desde que respeitem as
faixas e restrições acima.

## Fora do alcance de verificação aqui

A precisão real da direção, o alinhamento entre os dois controladores I2S e o
efeito dos motores só se validam no protótipo. Aqui valem build, testes sintéticos
e o smoke de infraestrutura.
