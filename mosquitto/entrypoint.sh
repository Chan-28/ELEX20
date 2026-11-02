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

exec /docker-entrypoint.sh mosquitto -c /mosquitto/config/mosquitto.conf
