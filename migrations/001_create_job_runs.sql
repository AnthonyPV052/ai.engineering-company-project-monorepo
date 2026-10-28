-- Nightly jobs are operational runs, intentionally separate from pipeline_runs.
CREATE TABLE IF NOT EXISTS job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name VARCHAR(128) NOT NULL,
    target_date DATE NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_job_runs_job_name_target_date
    ON job_runs (job_name, target_date);

-- This constraint makes the state-based lock safe under concurrent starts.
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_runs_processing_job
    ON job_runs (job_name)
    WHERE status = 'processing';
