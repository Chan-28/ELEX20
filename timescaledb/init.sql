CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─────────────────────────────────────────────────────────────
-- Resultados de inferência do modelo Edge Impulse (ESP32-S3)
-- Classificação de som ambiente — populada pelo workflow n8n via MQTT
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS emg_inference (
    time        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    device_id   TEXT         NOT NULL,
    label       TEXT         NOT NULL,
    confidence  FLOAT4       NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    raw_json    JSONB
);

SELECT create_hypertable('emg_inference', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_emg_inference_device_time
    ON emg_inference (device_id, time DESC);

-- ─────────────────────────────────────────────────────────────
-- Amostras brutas EMG (opcional — para replay ou análise offline)
-- Populada diretamente pelo Python (captar_Dados.py → psycopg2)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS emg_raw (
    time        TIMESTAMPTZ  NOT NULL,
    device_id   TEXT         NOT NULL,
    channel     SMALLINT     NOT NULL DEFAULT 0,
    voltage_uv  FLOAT4       NOT NULL
);

SELECT create_hypertable('emg_raw', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_emg_raw_device_time
    ON emg_raw (device_id, time DESC);
