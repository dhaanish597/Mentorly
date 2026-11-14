CREATE TABLE studio_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch INTEGER NOT NULL,
 idempotency_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(session_id,idempotency_key)
);
CREATE INDEX studio_model_daily ON studio_model_usage(created_at,status);
CREATE TABLE studio_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count INTEGER NOT NULL CHECK(request_count >= 0)
);
