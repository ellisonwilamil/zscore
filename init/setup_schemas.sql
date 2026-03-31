-- =================================================================
-- PARTE 1: CRIAÇÃO DOS SCHEMAS E USUÁRIO
-- =================================================================
CREATE SCHEMA IF NOT EXISTS "AnalyticsAnomalies";
CREATE SCHEMA IF NOT EXISTS "AnalyticsZscore";

-- Criação do usuário de serviço (se não existir)
-- Nota: A senha deve ser definida via Secret Management em produção
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'analytics_worker') THEN
        CREATE ROLE analytics_worker WITH LOGIN PASSWORD 'Senha_Producao_Forte_Aqui';
    END IF;
END
$$;

-- Permissões básicas nos Schemas
GRANT USAGE ON SCHEMA "AnalyticsAnomalies" TO analytics_worker;
GRANT USAGE ON SCHEMA "AnalyticsZscore" TO analytics_worker;

-- =================================================================
-- PARTE 2: TABELAS NO SCHEMA "AnalyticsAnomalies"
-- =================================================================
SET search_path TO "AnalyticsAnomalies";

CREATE TABLE IF NOT EXISTS script_execution_summary (
    id SERIAL PRIMARY KEY,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    execution_time_seconds DOUBLE PRECISION,
    total_anomalies_detected INTEGER DEFAULT 0,
    total_anomalies_inserted INTEGER DEFAULT 0,
    total_duplicates INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'Running',
    max_value DOUBLE PRECISION,
    machine_filter VARCHAR(255),
    sensor_filter VARCHAR(255),
    date_filter DATE
);

CREATE TABLE IF NOT EXISTS anomalies (
    id SERIAL PRIMARY KEY,
    script_execution_id INTEGER REFERENCES script_execution_summary(id),
    machine_name VARCHAR(255) NOT NULL,
    sensor_name VARCHAR(255) NOT NULL,
    trend_name VARCHAR(255) NOT NULL,
    anomaly_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    var_value DOUBLE PRECISION,
    adaptive_threshold DOUBLE PRECISION,
    diff_value DOUBLE PRECISION,
    excess_percent DOUBLE PRECISION,
    igas_value DOUBLE PRECISION,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    feedback_true_anomaly BOOLEAN,
    feedback_severity INTEGER CHECK (feedback_severity BETWEEN 1 AND 5),
    feedback_attendant VARCHAR(255),
    feedback_maintenance_flow BOOLEAN DEFAULT FALSE,
    feedback_notes TEXT,
    CONSTRAINT unique_anomaly UNIQUE (machine_name, sensor_name, trend_name, anomaly_datetime)
);

-- Índices Compostos para Performance do Front-end
CREATE INDEX idx_anomalies_machine_sensor ON anomalies (machine_name, sensor_name);
CREATE INDEX idx_anomalies_datetime ON anomalies (anomaly_datetime DESC);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA "AnalyticsAnomalies" TO analytics_worker;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA "AnalyticsAnomalies" TO analytics_worker;

-- =================================================================
-- PARTE 3: TABELAS NO SCHEMA "AnalyticsZscore"
-- =================================================================
SET search_path TO "AnalyticsZscore";

CREATE TABLE IF NOT EXISTS zscore_configs (
    id SERIAL PRIMARY KEY,
    config_name VARCHAR(255) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    window_size_days INTEGER NOT NULL DEFAULT 7,
    step_size_days INTEGER NOT NULL DEFAULT 1,
    zscore_std_multiplier DOUBLE PRECISION NOT NULL DEFAULT 3.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO zscore_configs (config_name, is_active) 
VALUES ('default', TRUE) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS zscore_execution_summary (
    id SERIAL PRIMARY KEY,
    schemas VARCHAR(10),
    date_filter DATE NOT NULL,
    config_id INTEGER REFERENCES zscore_configs(id),
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_freq_trends INTEGER DEFAULT 0,
    end_time TIMESTAMP WITH TIME ZONE,
    execution_time_seconds DOUBLE PRECISION,
    status VARCHAR(50) NOT NULL,
    processed_parks INTEGER DEFAULT 0,
    processed_machines INTEGER DEFAULT 0,  
    processed_sensors INTEGER DEFAULT 0,
    processed_trends INTEGER DEFAULT 0,
    zscore_records_inserted INTEGER DEFAULT 0,
    error_log TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS zscore_results (
    id BIGSERIAL PRIMARY KEY,
    execution_id INTEGER NOT NULL REFERENCES zscore_execution_summary(id),
    park_name VARCHAR(50) NOT NULL,
    machine_name VARCHAR(100) NOT NULL,
    sensor_name VARCHAR(100) NOT NULL,
    trend_name VARCHAR(255) NOT NULL,
    window_end_date DATE NOT NULL,
    z_score DOUBLE PRECISION,
    variance DOUBLE PRECISION,
    base_fixa DOUBLE PRECISION,
    group_mean_base_fixa DOUBLE PRECISION,
    group_std_base_fixa DOUBLE PRECISION,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_zscore_result UNIQUE (park_name, machine_name, sensor_name, trend_name, window_end_date)
);

-- Índices Compostos para Performance do Front-end
CREATE INDEX idx_zscore_park_trend ON zscore_results (park_name, trend_name);
CREATE INDEX idx_zscore_date ON zscore_results (window_end_date DESC);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA "AnalyticsZscore" TO analytics_worker;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA "AnalyticsZscore" TO analytics_worker;