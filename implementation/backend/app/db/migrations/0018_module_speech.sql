-- Source-bound voice accounting; audio and transcripts are never retained here.
CREATE TABLE module_speech_usage (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL,
 module TEXT NOT NULL CHECK(module IN ('lesson','interview','redrive')),
 epoch INTEGER NOT NULL CHECK(epoch>=1),
 operation TEXT NOT NULL CHECK(operation IN ('STT','TTS')),
 stt_seconds REAL NOT NULL DEFAULT 0 CHECK(stt_seconds>=0 AND stt_seconds<=30),
 tts_chars INTEGER NOT NULL DEFAULT 0 CHECK(tts_chars>=0),
 request_count INTEGER NOT NULL CHECK(request_count>=1),
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX module_speech_daily ON module_speech_usage(created_at,status);
CREATE INDEX module_speech_source ON module_speech_usage(workspace_id,module,source_id,status);
-- Cascading capability deletion must not restore already-dispatched daily credit.
CREATE TRIGGER module_speech_delete_accounting AFTER DELETE ON module_speech_usage
WHEN OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN')
BEGIN
 INSERT INTO studio_speech_deleted_daily(day,request_count)
 VALUES(date(OLD.created_at),OLD.request_count)
 ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count;
END;
