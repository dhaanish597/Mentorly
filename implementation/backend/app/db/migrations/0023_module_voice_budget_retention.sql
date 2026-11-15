-- Anonymous lifetime audio budgets must survive capability hard or soft deletion.
-- request_count remains exclusively in studio_speech_deleted_daily (migration 0018).
CREATE TABLE module_speech_deleted_totals (
 day TEXT PRIMARY KEY,
 stt_seconds REAL NOT NULL DEFAULT 0 CHECK(stt_seconds>=0),
 tts_chars INTEGER NOT NULL DEFAULT 0 CHECK(tts_chars>=0)
);
-- Older deletions retained counts only. Exact durations/chars are unrecoverable;
-- conservatively reserve the maximum bounded 30s / 8000 text chars per call.
INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
SELECT day,request_count*30.0,request_count*8000
FROM studio_speech_deleted_daily WHERE request_count>0;
CREATE TRIGGER module_speech_delete_audio_budget
AFTER DELETE ON module_speech_usage
WHEN OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN')
BEGIN
 INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 VALUES(date(OLD.created_at),OLD.stt_seconds,OLD.tts_chars)
 ON CONFLICT(day) DO UPDATE SET
 stt_seconds=stt_seconds+excluded.stt_seconds,
 tts_chars=tts_chars+excluded.tts_chars;
END;
