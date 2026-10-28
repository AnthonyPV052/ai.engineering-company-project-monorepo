-- DLQ audit trail for tasks that exhausted Celery retries.
CREATE TABLE IF NOT EXISTS celery_dead_letter_queue (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(255) NOT NULL,
    attempt INTEGER NOT NULL,
    error TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_celery_dlq_task_id
    ON celery_dead_letter_queue (task_id);