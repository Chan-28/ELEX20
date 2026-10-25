CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─────────────────────────────────────────────────────────────
-- Dispositivos registrados (ESP32-S3 com microfone INMP441)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT         PRIMARY KEY,
    name          TEXT,
    location      TEXT,
    registered_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────
-- Eventos de classificação de som ambiente
-- Populada pelo workflow n8n via MQTT topic sound/inference/<id>
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sound_events (
    time        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    device_id   TEXT         NOT NULL,
    label       TEXT         NOT NULL,
    confidence  FLOAT4       NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    location    TEXT,
    raw_json    JSONB
);

SELECT create_hypertable('sound_events', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_sound_events_device_time
    ON sound_events (device_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_sound_events_label_time
    ON sound_events (label, time DESC);

-- ─────────────────────────────────────────────────────────────
-- Agregação contínua: contagem e confiança média por hora
-- Atualizada automaticamente pelo TimescaleDB background worker
-- ─────────────────────────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS sound_events_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS hour,
    device_id,
    label,
    COUNT(*)        AS event_count,
    AVG(confidence) AS avg_confidence
FROM sound_events
GROUP BY hour, device_id, label;

-- Política de refresh: mantém a vista atualizada a cada hora,
-- cobrindo as últimas 7 dias
SELECT add_continuous_aggregate_policy('sound_events_hourly',
    start_offset => INTERVAL '7 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- ─────────────────────────────────────────────────────────────
-- Política de retenção: 90 dias de dados brutos
-- (a agregação contínua mantém o histórico compacto)
-- ─────────────────────────────────────────────────────────────
SELECT add_retention_policy('sound_events',
    INTERVAL '90 days',
    if_not_exists => TRUE);
