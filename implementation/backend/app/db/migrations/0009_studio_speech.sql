CREATE TABLE studio_speech_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id), epoch INTEGER NOT NULL,
 operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 stt_seconds REAL NOT NULL DEFAULT 0, tts_chars INTEGER NOT NULL DEFAULT 0,
 request_count INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(session_id,operation,idempotency_key)
);
CREATE INDEX studio_speech_usage_daily ON studio_speech_usage(created_at,status);
CREATE TABLE studio_speech_deleted_daily (day TEXT PRIMARY KEY, request_count INTEGER NOT NULL);
