#!/bin/sh
# Aplica papéis, banco do n8n, permissões e restrições do TimescaleDB.
# Idempotente: roda a cada `docker compose up`, em volumes novos e antigos
# (o init.sql só roda com volume vazio). Chamado pelo serviço db-init.
set -eu

# O healthcheck do timescaledb pode passar enquanto o servidor temporário do
# initdb ainda está de pé (só socket). Espera o servidor definitivo via TCP.
i=0
until pg_isready -q; do
  i=$((i + 1))
  [ "$i" -le 30 ] || { echo "timescaledb indisponível" >&2; exit 1; }
  sleep 2
done

# Senhas dos papéis: geradas pelo secrets-init e montadas como arquivos
GRAFANA_RO_PASSWORD=$(cat /run/secrets/grafana_ro/value)
N8N_DB_PASSWORD=$(cat /run/secrets/n8n_db/value)
HERMES_RO_PASSWORD=$(cat /run/secrets/hermes_ro/value)

exec psql -v ON_ERROR_STOP=1 \
  -v pg_db="$PGDATABASE" \
  -v n8n_db="$N8N_DB" \
  -v ro_pass="$GRAFANA_RO_PASSWORD" \
  -v n8n_pass="$N8N_DB_PASSWORD" \
  -v hermes_pass="$HERMES_RO_PASSWORD" \
  -f /db-init.sql
