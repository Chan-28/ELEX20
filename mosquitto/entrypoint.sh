#!/bin/sh
# Gera o arquivo de senhas do Mosquitto a partir do ambiente e inicia o broker.
# As senhas nunca ficam no repositório: vêm do .env via docker-compose.
set -eu

: "${MQTT_DEVICE_PASS:?defina MQTT_DEVICE_PASS no .env}"
: "${MQTT_N8N_PASS:?defina MQTT_N8N_PASS no .env}"

PASSWD=/mosquitto/config/passwd
mosquitto_passwd -b -c "$PASSWD" device "$MQTT_DEVICE_PASS"
mosquitto_passwd -b "$PASSWD" n8n "$MQTT_N8N_PASS"
# O broker roda como usuário "mosquitto" e precisa ler o arquivo
chown mosquitto:mosquitto "$PASSWD"
chmod 0600 "$PASSWD"

# ACLs montadas do host chegam com dono/permissão do host; o broker (usuário "mosquitto")
# recusará arquivos legíveis por todos em versões futuras. Copia com dono e 0600.
for f in acl acl-health; do
  install -m 0600 -o mosquitto -g mosquitto "/mosquitto/acl-src/$f" "/mosquitto/config/$f"
done

exec /docker-entrypoint.sh mosquitto -c /mosquitto/config/mosquitto.conf
