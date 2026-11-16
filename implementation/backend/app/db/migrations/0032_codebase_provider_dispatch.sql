-- Retain all usage independently of session deletion; unknown dispatches fail closed.
CREATE TABLE codebase_model_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, operation TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL
);
CREATE TABLE codebase_model_deleted_daily(day TEXT PRIMARY KEY, request_count INTEGER NOT NULL);
CREATE TABLE codebase_speech_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, operation TEXT NOT NULL,
 stt_seconds REAL NOT NULL, tts_chars INTEGER NOT NULL, request_count INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')), created_at TEXT NOT NULL
);
CREATE TABLE codebase_provider_requests (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','DONE')),
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX codebase_one_active_request ON codebase_provider_requests(session_id) WHERE status='ACTIVE';
