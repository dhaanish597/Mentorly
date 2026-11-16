CREATE TABLE IF NOT EXISTS codebase_learning_audio (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES codebase_learning_sessions(id) ON DELETE CASCADE,
    wav BYTEA NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_codebase_audio_expiry ON codebase_learning_audio(expires_at);
CREATE INDEX IF NOT EXISTS idx_codebase_audio_session ON codebase_learning_audio(session_id);
