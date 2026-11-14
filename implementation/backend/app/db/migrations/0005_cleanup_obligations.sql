-- Payload-free obligations survive tombstoning and coordinator restart.
CREATE TABLE cleanup_obligations (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    turn_generation INTEGER NOT NULL,
    audio_pending INTEGER NOT NULL DEFAULT 1 CHECK(audio_pending IN (0,1)),
    pending_jobs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_cleanup_obligations_updated ON cleanup_obligations(updated_at);
INSERT INTO cleanup_obligations(session_id,turn_generation,audio_pending,pending_jobs_json,created_at,updated_at)
SELECT id,active_turn_generation,1,'[]',deleted_at,deleted_at FROM sessions WHERE deleted_at IS NOT NULL;
