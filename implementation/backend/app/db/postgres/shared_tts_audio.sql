-- Shared, private TTS cache. Legacy bytes remain separately reconciled.
CREATE TABLE cloud_audio (
 scope TEXT NOT NULL, session_id TEXT NOT NULL, cache_key TEXT NOT NULL,
 wav BYTEA NOT NULL, created_at DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(scope,session_id,cache_key)
);
CREATE INDEX cloud_audio_created_at ON cloud_audio(created_at);
