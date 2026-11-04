#!/bin/sh
# Gera os segredos internos da stack (senhas dos papéis do banco, do MQTT e dos tokens
# entre n8n e Hermes) na primeira subida e os guarda em volumes do Docker.
# - Sem configuração: cada segredo é aleatório (192 bits) e persiste entre subidas.
# - Para fixar um valor, defina a variável no .env (ex.: MQTT_DEVICE_PASS=...): ela vale
#   sempre e sobrescreve o volume.
# Cada serviço monta só o volume dos segredos de que precisa (docker-compose.yaml).
set -eu

gerar() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

for par in \
  grafana_ro:GRAFANA_RO_PASSWORD n8n_db:N8N_DB_PASSWORD hermes_ro:HERMES_RO_PASSWORD \
  mqtt_device:MQTT_DEVICE_PASS mqtt_n8n:MQTT_N8N_PASS \
  hermes_webhook:HERMES_WEBHOOK_SECRET n8n_command:N8N_COMMAND_TOKEN; do
  nome=${par%%:*}
  variavel=${par##*:}
  arquivo="/secrets/$nome/value"
  eval "fixo=\${$variavel:-}"
  if [ -n "$fixo" ]; then
    printf '%s' "$fixo" > "$arquivo"
  elif [ ! -s "$arquivo" ]; then
    gerar > "$arquivo"
  fi
  chmod 0444 "$arquivo"
done
echo "segredos prontos"
