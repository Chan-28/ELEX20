-- Papéis com privilégio mínimo, banco do n8n e restrições de dados.
-- Executado por timescaledb/db-init.sh (psql como superusuário) a cada subida.
-- Variáveis psql: pg_db, n8n_db, ro_pass, n8n_pass, hermes_pass.

-- ── Papéis ───────────────────────────────────────────────────────────────────
-- grafana_ro: usado pelo datasource do Grafana (leitura, só nas tabelas de sons)
-- n8n_app:    usado pelo n8n (dono do próprio banco; grava em sound_events)
-- hermes_ro:  usado pelo Hermes (leitura, sem raw_json de sound_events)
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r)
FROM (VALUES ('grafana_ro'), ('n8n_app'), ('hermes_ro')) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec

-- Senhas sempre sincronizadas com o .env
SELECT format('ALTER ROLE grafana_ro PASSWORD %L', :'ro_pass') \gexec
SELECT format('ALTER ROLE n8n_app PASSWORD %L', :'n8n_pass') \gexec
SELECT format('ALTER ROLE hermes_ro PASSWORD %L', :'hermes_pass') \gexec

-- Consultas do Grafana: somente leitura e com tempo limite
ALTER ROLE grafana_ro SET default_transaction_read_only = on;
ALTER ROLE grafana_ro SET statement_timeout = '30s';

-- Consultas do Hermes: somente leitura e com tempo limite curto
ALTER ROLE hermes_ro SET default_transaction_read_only = on;
ALTER ROLE hermes_ro SET statement_timeout = '10s';

-- ── Banco do n8n ─────────────────────────────────────────────────────────────
SELECT format('CREATE DATABASE %I OWNER n8n_app', :'n8n_db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'n8n_db') \gexec
SELECT format('ALTER DATABASE %I OWNER TO n8n_app', :'n8n_db') \gexec
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'n8n_db') \gexec

-- Volumes antigos: objetos criados quando o n8n usava o superusuário
\connect :n8n_db
ALTER SCHEMA public OWNER TO n8n_app;
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT format('ALTER %s %I.%I OWNER TO n8n_app',
                  CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
                  n.nspname, c.relname) AS cmd
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_roles o ON o.oid = c.relowner
    WHERE n.nspname = 'public' AND o.rolname <> 'n8n_app' AND c.relkind IN ('r', 'p', 'v', 'm')
  LOOP
    EXECUTE r.cmd;
  END LOOP;
END
$$;

-- ── Permissões no banco de sons ──────────────────────────────────────────────
\connect :pg_db
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'pg_db') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO grafana_ro, n8n_app, hermes_ro', :'pg_db') \gexec
GRANT USAGE ON SCHEMA public TO grafana_ro, n8n_app, hermes_ro;

-- ── Direção do som e urgência (migração idempotente de sound_events) ─────────
-- Setores relativos à frente da cabeça (0° = frente), 8 de 45°.
-- Urgência: 0 nenhuma, 1 baixa, 2 média, 3 alta.
ALTER TABLE sound_events ADD COLUMN IF NOT EXISTS direction_deg SMALLINT CHECK (direction_deg BETWEEN 0 AND 359);
ALTER TABLE sound_events ADD COLUMN IF NOT EXISTS sector TEXT CHECK (sector IN ('N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'));
ALTER TABLE sound_events ADD COLUMN IF NOT EXISTS doa_confidence FLOAT4 CHECK (doa_confidence BETWEEN 0 AND 1);
ALTER TABLE sound_events ADD COLUMN IF NOT EXISTS urgency SMALLINT CHECK (urgency BETWEEN 0 AND 3);

-- Urgência por rótulo do modelo (classes do projeto no Edge Impulse Studio).
-- Valores iniciais são uma proposta; ajuste com UPDATE (o seed não sobrescreve).
CREATE TABLE IF NOT EXISTS sound_classes (
    label    TEXT     PRIMARY KEY CHECK (char_length(label) BETWEEN 1 AND 64),
    urgency  SMALLINT NOT NULL CHECK (urgency BETWEEN 0 AND 3)
);
INSERT INTO sound_classes (label, urgency) VALUES
    ('siren', 3), ('car_horn', 3), ('gun_shot', 3),
    ('dog_bark', 2), ('drilling', 2), ('jackhammer', 2),
    ('engine_idling', 1), ('children_playing', 1), ('street_music', 1),
    ('air_conditioner', 0)
ON CONFLICT (label) DO NOTHING;

-- Estado dos sensores: heartbeat de sound/status/<device_id>, gravado pelo n8n
CREATE TABLE IF NOT EXISTS device_status (
    time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    device_id TEXT        NOT NULL CHECK (device_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    uptime_s  BIGINT      CHECK (uptime_s >= 0),
    heap      BIGINT      CHECK (heap >= 0),
    rssi      SMALLINT    CHECK (rssi BETWEEN -127 AND 0),
    raw_json  JSONB       CHECK (raw_json IS NULL OR octet_length(raw_json::text) <= 4096)
);
SELECT create_hypertable('device_status', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_device_status_device_time ON device_status (device_id, time DESC);
SELECT add_retention_policy('device_status', INTERVAL '30 days', if_not_exists => TRUE);

CREATE OR REPLACE VIEW device_last_status AS
SELECT DISTINCT ON (device_id) device_id, time, uptime_s, heap, rssi
FROM device_status
ORDER BY device_id, time DESC;

-- Só as tabelas de sons: as tabelas internas do Grafana (usuários, chaves,
-- segredos de datasource) ficam neste mesmo banco e NÃO são concedidas.
GRANT SELECT ON devices, sound_events, sound_events_hourly, sound_classes, device_status, device_last_status TO grafana_ro;
GRANT SELECT, INSERT, UPDATE ON devices TO n8n_app;
GRANT SELECT, INSERT ON sound_events TO n8n_app;
GRANT SELECT ON sound_classes TO n8n_app;
GRANT SELECT, INSERT ON device_status TO n8n_app;

-- Hermes: sem raw_json (conteúdo vindo do MQTT, não confiável) e sem escrita.
-- GRANT por coluna não vale para os chunks da hypertable; por isso uma view.
CREATE OR REPLACE VIEW sound_events_public AS
SELECT time, device_id, label, confidence, location, direction_deg, sector, doa_confidence, urgency
FROM sound_events;
GRANT SELECT ON devices, sound_events_hourly, sound_events_public, sound_classes, device_status, device_last_status TO hermes_ro;

-- ── Validação de dados (entrada vem do MQTT) ─────────────────────────────────
-- NOT VALID: vale para linhas novas sem barrar a subida por dados antigos.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sound_events_label_len') THEN
    ALTER TABLE sound_events
      ADD CONSTRAINT sound_events_label_len CHECK (char_length(label) BETWEEN 1 AND 64) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sound_events_device_fmt') THEN
    ALTER TABLE sound_events
      ADD CONSTRAINT sound_events_device_fmt CHECK (device_id ~ '^[A-Za-z0-9._-]{1,64}$') NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sound_events_location_len') THEN
    ALTER TABLE sound_events
      ADD CONSTRAINT sound_events_location_len CHECK (location IS NULL OR char_length(location) <= 128) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sound_events_raw_json_size') THEN
    ALTER TABLE sound_events
      ADD CONSTRAINT sound_events_raw_json_size CHECK (raw_json IS NULL OR octet_length(raw_json::text) <= 4096) NOT VALID;
  END IF;
END
$$;
