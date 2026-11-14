-- Preserve full evidence identity and client-save ordering without altering prior migrations.
ALTER TABLE sessions ADD COLUMN latest_client_edit_sequence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE traces ADD COLUMN revision_json TEXT;
ALTER TABLE traces ADD COLUMN challenge_id TEXT;
ALTER TABLE jobs ADD COLUMN revision_json TEXT;
ALTER TABLE jobs ADD COLUMN challenge_id TEXT;
CREATE INDEX idx_jobs_session_active ON jobs(session_id,status);
