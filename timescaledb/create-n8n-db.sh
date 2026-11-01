#!/bin/sh
# Cria o banco do n8n na primeira inicialização do TimescaleDB.
# O n8n exige DB_POSTGRESDB_DATABASE já existente e o init.sql só roda em POSTGRES_DB.
# Só executa com o volume vazio; em volume existente, crie o banco à mão:
#   docker compose exec timescaledb psql -U "$POSTGRES_USER" -c 'CREATE DATABASE n8n'
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "CREATE DATABASE \"${N8N_DB:-n8n}\""
