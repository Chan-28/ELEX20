#!/usr/bin/env bash
# Teste de infraestrutura: valida os controles de segurança do banco e do MQTT.
#   - papéis do banco: grafana_ro só lê; n8n_app só insere; nenhum é superusuário;
#     restrições de tamanho/formato de sound_events
#   - Mosquitto: cliente anônimo recusado; "device" só publica em sound/*; "n8n" só lê
# Sobe containers num projeto descartável (elexsmoke) com senhas de teste e remove
# os próprios volumes ao terminar. Usado localmente e em .github/workflows/infra-smoke.yml.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

PROJECT=elexsmoke
export GRAFANA_RO_PASSWORD=smoke-ro N8N_DB_PASSWORD=smoke-n8n
export MQTT_DEVICE_PASS=smoke-device MQTT_N8N_PASS=smoke-n8n-mqtt

dc() { docker compose -p "$PROJECT" --env-file .env.example "$@"; }

# container_name fixo no compose: não dá para rodar junto com a stack de verdade
for name in timescaledb mosquitto db-init; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
    echo "Já existe um container '$name' (stack em uso?). Pare-o antes de rodar o smoke." >&2
    exit 2
  fi
done

cleanup() {
  dc down >/dev/null 2>&1
  docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" | xargs -r docker volume rm >/dev/null 2>&1
}
trap cleanup EXIT

FAILS=0
ok()   { echo "  PASS  $1"; }
bad()  { echo "  FAIL  $1"; FAILS=$((FAILS + 1)); }
expect_ok()   { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }
expect_fail() { local d=$1; shift; if "$@" >/dev/null 2>&1; then bad "$d"; else ok "$d"; fi; }

# SQL como <usuário> <senha> <banco> <comando>, dentro do container do banco
sql() { docker exec -e PGPASSWORD="$2" timescaledb psql -h 127.0.0.1 -v ON_ERROR_STOP=1 -U "$1" -d "$3" -tAc "$4"; }
# MQTT dentro do container do broker
mpub() { docker exec mosquitto mosquitto_pub -h localhost "$@"; }
msub() { docker exec mosquitto mosquitto_sub -h localhost "$@"; }

echo "Subindo timescaledb, db-init e mosquitto..."
if ! dc up -d --wait timescaledb db-init mosquitto >/dev/null 2>&1; then
  dc ps -a; dc logs --tail=40 db-init mosquitto timescaledb
  echo "Falha ao subir a stack" >&2
  exit 1
fi

# POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB vêm do .env.example
DB=grafana
echo; echo "Banco de dados"
sql postgres password "$DB" "CREATE TABLE IF NOT EXISTS segredo_interno(x int)" >/dev/null
expect_ok   "db-init é idempotente (segunda execução)" dc run --rm --no-deps db-init
expect_ok   "grafana_ro lê sound_events"               sql grafana_ro "$GRAFANA_RO_PASSWORD" "$DB" "select count(*) from sound_events"
expect_ok   "grafana_ro lê o agregado sound_events_hourly" sql grafana_ro "$GRAFANA_RO_PASSWORD" "$DB" "select count(*) from sound_events_hourly"
expect_fail "grafana_ro não escreve"                   sql grafana_ro "$GRAFANA_RO_PASSWORD" "$DB" "insert into sound_events(device_id,label,confidence) values('d','l',0.5)"
expect_fail "grafana_ro não lê tabelas fora da lista"  sql grafana_ro "$GRAFANA_RO_PASSWORD" "$DB" "select * from segredo_interno"
expect_fail "grafana_ro não executa COPY PROGRAM"      sql grafana_ro "$GRAFANA_RO_PASSWORD" "$DB" "copy (select 1) to program 'id'"
[ "$(sql grafana_ro "$GRAFANA_RO_PASSWORD" "$DB" "select current_setting('is_superuser')" 2>/dev/null)" = "off" ] \
  && ok "grafana_ro não é superusuário" || bad "grafana_ro não é superusuário"
[ "$(sql n8n_app "$N8N_DB_PASSWORD" n8n "select current_setting('is_superuser')" 2>/dev/null)" = "off" ] \
  && ok "n8n_app não é superusuário" || bad "n8n_app não é superusuário"
expect_ok   "n8n_app insere leitura válida"            sql n8n_app "$N8N_DB_PASSWORD" "$DB" "insert into sound_events(device_id,label,confidence,raw_json) values('esp32-01','chuva',0.9,'{\"a\":1}')"
expect_fail "n8n_app não apaga"                        sql n8n_app "$N8N_DB_PASSWORD" "$DB" "delete from sound_events"
expect_fail "n8n_app não lê tabelas fora da lista"     sql n8n_app "$N8N_DB_PASSWORD" "$DB" "select * from segredo_interno"
expect_ok   "n8n_app cria tabelas no próprio banco"    sql n8n_app "$N8N_DB_PASSWORD" n8n "create table if not exists t(x int)"
expect_fail "label com 100 caracteres é rejeitado"     sql n8n_app "$N8N_DB_PASSWORD" "$DB" "insert into sound_events(device_id,label,confidence) values('esp32-01',repeat('x',100),0.9)"
expect_fail "device_id inválido é rejeitado"           sql n8n_app "$N8N_DB_PASSWORD" "$DB" "insert into sound_events(device_id,label,confidence) values('a b;--','chuva',0.9)"
expect_fail "raw_json acima de 4 KB é rejeitado"       sql n8n_app "$N8N_DB_PASSWORD" "$DB" "insert into sound_events(device_id,label,confidence,raw_json) values('d','l',0.5,jsonb_build_object('k',repeat('x',5000)))"

echo; echo "MQTT (Mosquitto)"
expect_fail "cliente anônimo é recusado"               mpub -t sound/inference/x -m a
expect_fail "senha errada é recusada"                  mpub -u device -P errada -t sound/inference/x -m a
expect_ok   "device publica em sound/inference/<id>"   mpub -u device -P "$MQTT_DEVICE_PASS" -i esp -r -q 1 -t sound/inference/esp -m '{"ok":1}'
[ "$(msub -u n8n -P "$MQTT_N8N_PASS" -t 'sound/#' -C 1 -W 5 2>/dev/null)" = '{"ok":1}' ] \
  && ok "n8n recebe o que o device publicou" || bad "n8n recebe o que o device publicou"
mpub -u device -P "$MQTT_DEVICE_PASS" -i esp -r -q 1 -t other/topic -m fora >/dev/null 2>&1
[ -z "$(msub -u n8n -P "$MQTT_N8N_PASS" -t 'other/#' -C 1 -W 2 2>/dev/null)" ] \
  && ok "device não entrega fora de sound/*" || bad "device não entrega fora de sound/*"
mpub -u n8n -P "$MQTT_N8N_PASS" -i n8n -r -q 1 -t sound/inference/forjado -m forjado >/dev/null 2>&1
[ -z "$(msub -u n8n -P "$MQTT_N8N_PASS" -t 'sound/inference/forjado' -C 1 -W 2 2>/dev/null)" ] \
  && ok "n8n não consegue publicar" || bad "n8n não consegue publicar"
expect_ok   "healthcheck anônimo funciona no listener 1884 (loopback)" mpub -p 1884 -t health -m ping -q 1
mpub -p 1884 -r -q 1 -t sound/inference/anonimo -m anonimo >/dev/null 2>&1
[ -z "$(msub -u n8n -P "$MQTT_N8N_PASS" -t 'sound/inference/anonimo' -C 1 -W 2 2>/dev/null)" ] \
  && ok "listener 1884 só aceita o tópico health" || bad "listener 1884 só aceita o tópico health"

echo
if [ "$FAILS" -eq 0 ]; then echo "Todos os controles passaram."; else echo "$FAILS controle(s) falharam." >&2; exit 1; fi
