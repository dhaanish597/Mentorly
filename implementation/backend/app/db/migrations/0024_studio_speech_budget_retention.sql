-- Shared lifetime audio budgets also survive original Studio session cleanup.
-- Studio's purge_speech_usage already preserves daily request_count separately.
CREATE TRIGGER studio_speech_delete_audio_budget
AFTER DELETE ON studio_speech_usage
WHEN OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN')
BEGIN
 INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 VALUES(date(OLD.created_at),OLD.stt_seconds,OLD.tts_chars)
 ON CONFLICT(day) DO UPDATE SET
 stt_seconds=stt_seconds+excluded.stt_seconds,
 tts_chars=tts_chars+excluded.tts_chars;
END;
