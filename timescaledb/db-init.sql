-- Papéis com privilégio mínimo, banco do n8n e restrições de dados.
-- Executado por timescaledb/db-init.sh (psql como superusuário) a cada subida.
-- Variáveis psql: pg_db, n8n_db, ro_pass, n8n_pass.

-- ── Papéis ───────────────────────────────────────────────────────────────────
-- grafana_ro: usado pelo datasource do Grafana (leitura, só nas tabelas de sons)
-- n8n_app:    usado pelo n8n (dono do próprio banco; grava em sound_events)
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r)
FROM (VALUES ('grafana_ro'), ('n8n_app')) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec

-- Senhas sempre sincronizadas com o .env
SELECT format('ALTER ROLE grafana_ro PASSWORD %L', :'ro_pass') \gexec
SELECT format('ALTER ROLE n8n_app PASSWORD %L', :'n8n_pass') \gexec

-- Consultas do Grafana: somente leitura e com tempo limite
ALTER ROLE grafana_ro SET default_transaction_read_only = on;
ALTER ROLE grafana_ro SET statement_timeout = '30s';

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
SELECT format('GRANT CONNECT ON DATABASE %I TO grafana_ro, n8n_app', :'pg_db') \gexec
GRANT USAGE ON SCHEMA public TO grafana_ro, n8n_app;

-- Só as tabelas de sons: as tabelas internas do Grafana (usuários, chaves,
-- segredos de datasource) ficam neste mesmo banco e NÃO são concedidas.
GRANT SELECT ON devices, sound_events, sound_events_hourly TO grafana_ro;
GRANT SELECT, INSERT, UPDATE ON devices TO n8n_app;
GRANT SELECT, INSERT ON sound_events TO n8n_app;

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
