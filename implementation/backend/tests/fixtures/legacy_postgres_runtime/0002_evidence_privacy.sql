-- Native PostgreSQL guards preserve evidence and deletion invariants.

CREATE FUNCTION trigger_repo_snapshot_delete_authored_prompt_events() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM studio_events
 WHERE event_type='coach.action' AND viva_json_valid(payload_json)
 AND viva_json_extract(payload_json,'$.source')='authored_repo_defense'
 AND viva_json_extract(payload_json,'$.snapshot_id')=old.id;
 RETURN OLD;
END $fn$;
CREATE TRIGGER repo_snapshot_delete_authored_prompt_events BEFORE DELETE ON repo_snapshots FOR EACH ROW EXECUTE FUNCTION trigger_repo_snapshot_delete_authored_prompt_events();

CREATE FUNCTION trigger_learning_completion_evidence() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
IF NOT EXISTS (
  SELECT 1 FROM learning_answers a WHERE a.id=NEW.answer_id AND a.session_id=NEW.session_id
  AND a.workspace_id=NEW.workspace_id AND a.run=NEW.run AND (NEW.kind='answer.evaluated' OR a.correct=1)
 ) THEN RAISE EXCEPTION 'Learning event requires evaluated owned answer evidence' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_completion_evidence BEFORE INSERT ON learning_events FOR EACH ROW WHEN (NEW.kind IN ('lesson.completed','answer.evaluated')) EXECUTE FUNCTION trigger_learning_completion_evidence();

CREATE FUNCTION trigger_learning_completion_state() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
IF NOT EXISTS (
  SELECT 1 FROM learning_answers a WHERE a.session_id=NEW.id AND a.workspace_id=NEW.workspace_id
  AND a.run=NEW.run AND a.correct=1
 ) THEN RAISE EXCEPTION 'Learning completion requires correct answer' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_completion_state BEFORE UPDATE OF state ON learning_sessions FOR EACH ROW WHEN (NEW.state='completed') EXECUTE FUNCTION trigger_learning_completion_state();

CREATE FUNCTION trigger_learning_achievement_evidence() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
IF NOT EXISTS (
  SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
  AND e.kind='lesson.completed' AND e.source='learning_engine'
 ) THEN RAISE EXCEPTION 'Achievement requires verified completion event' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_achievement_evidence BEFORE INSERT ON learning_achievements FOR EACH ROW EXECUTE FUNCTION trigger_learning_achievement_evidence();

CREATE FUNCTION trigger_learning_answer_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
RAISE EXCEPTION 'Learning answers are immutable' USING ERRCODE='23514';
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_answer_immutable BEFORE UPDATE ON learning_answers FOR EACH ROW EXECUTE FUNCTION trigger_learning_answer_immutable();

CREATE FUNCTION trigger_learning_event_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
RAISE EXCEPTION 'Learning events are immutable' USING ERRCODE='23514';
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_event_immutable BEFORE UPDATE ON learning_events FOR EACH ROW EXECUTE FUNCTION trigger_learning_event_immutable();

CREATE FUNCTION trigger_learning_achievement_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
RAISE EXCEPTION 'Learning achievements are immutable' USING ERRCODE='23514';
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_achievement_immutable BEFORE UPDATE ON learning_achievements FOR EACH ROW EXECUTE FUNCTION trigger_learning_achievement_immutable();

CREATE FUNCTION trigger_learning_external_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
RAISE EXCEPTION 'Learning external events are immutable' USING ERRCODE='23514';
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_external_immutable BEFORE UPDATE ON learning_external_events FOR EACH ROW EXECUTE FUNCTION trigger_learning_external_immutable();

CREATE FUNCTION trigger_learning_interview_evidence() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
IF NOT EXISTS (
  SELECT 1 FROM interview_sessions s JOIN interview_reports r ON r.session_id=s.id
  JOIN interview_events e ON e.session_id=s.id AND e.event_type='interview.completed'
  WHERE s.id=NEW.source_id AND s.workspace_id=NEW.workspace_id AND s.state='completed'
  AND s.completed_at IS NOT NULL
 ) THEN RAISE EXCEPTION 'Interview completion requires durable owned report and outbox' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_interview_evidence BEFORE INSERT ON learning_external_events FOR EACH ROW EXECUTE FUNCTION trigger_learning_interview_evidence();

CREATE FUNCTION trigger_interview_report_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
RAISE EXCEPTION 'Interview reports are immutable' USING ERRCODE='23514';
 RETURN NEW;
END $fn$;
CREATE TRIGGER interview_report_immutable BEFORE UPDATE ON interview_reports FOR EACH ROW EXECUTE FUNCTION trigger_interview_report_immutable();

CREATE FUNCTION trigger_module_speech_delete_accounting() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
INSERT INTO studio_speech_deleted_daily(day,request_count)
 VALUES(viva_date(OLD.created_at),OLD.request_count)
 ON CONFLICT(day) DO UPDATE SET request_count=studio_speech_deleted_daily.request_count+excluded.request_count;
 RETURN OLD;
END $fn$;
CREATE TRIGGER module_speech_delete_accounting AFTER DELETE ON module_speech_usage FOR EACH ROW WHEN (OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN')) EXECUTE FUNCTION trigger_module_speech_delete_accounting();

CREATE FUNCTION trigger_learning_evidence_achievement_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
IF NOT (
  (NEW.id='first_interview' AND NEW.source='interview' AND EXISTS (
   SELECT 1 FROM learning_external_events e WHERE e.id=NEW.source_event
   AND e.workspace_id=NEW.workspace_id AND e.source='interview' AND e.kind='interview.completed'
  )) OR
  (NEW.id='three_study_days' AND NEW.source='learning_engine' AND EXISTS (
   SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
   AND e.kind IN ('answer.evaluated','hint.requested') AND viva_date(e.created_at)=viva_date(NEW.earned_at)
  ) AND (
   SELECT count(DISTINCT viva_date(e.created_at)) FROM learning_events e
   WHERE e.workspace_id=NEW.workspace_id AND e.kind IN ('answer.evaluated','hint.requested')
   AND viva_date(e.created_at) BETWEEN viva_date(NEW.earned_at,'-2 days') AND viva_date(NEW.earned_at)
  )=3)
 ) THEN RAISE EXCEPTION 'Achievement requires verified owned evidence and threshold' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_evidence_achievement_guard BEFORE INSERT ON learning_evidence_achievements FOR EACH ROW EXECUTE FUNCTION trigger_learning_evidence_achievement_guard();

CREATE FUNCTION trigger_learning_evidence_achievement_immutable() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
RAISE EXCEPTION 'Learning evidence achievements are immutable' USING ERRCODE='23514';
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_evidence_achievement_immutable BEFORE UPDATE ON learning_evidence_achievements FOR EACH ROW EXECUTE FUNCTION trigger_learning_evidence_achievement_immutable();

CREATE FUNCTION trigger_learning_action_badge_cascade() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM learning_evidence_achievements WHERE source='learning_engine' AND source_event=OLD.id;
 RETURN OLD;
END $fn$;
CREATE TRIGGER learning_action_badge_cascade AFTER DELETE ON learning_events FOR EACH ROW EXECUTE FUNCTION trigger_learning_action_badge_cascade();

CREATE FUNCTION trigger_learning_external_badge_cascade() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM learning_evidence_achievements WHERE source='interview' AND source_event=OLD.id;
 RETURN OLD;
END $fn$;
CREATE TRIGGER learning_external_badge_cascade AFTER DELETE ON learning_external_events FOR EACH ROW EXECUTE FUNCTION trigger_learning_external_badge_cascade();

CREATE FUNCTION trigger_learning_workspace_soft_delete() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM learning_sessions WHERE workspace_id=NEW.id;
 DELETE FROM learning_external_events WHERE workspace_id=NEW.id;
 DELETE FROM learning_evidence_achievements WHERE workspace_id=NEW.id;
 RETURN NEW;
END $fn$;
CREATE TRIGGER learning_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces FOR EACH ROW WHEN (NEW.deleted_at IS NOT NULL) EXECUTE FUNCTION trigger_learning_workspace_soft_delete();

CREATE FUNCTION trigger_learning_interview_delete() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM learning_external_events WHERE source='interview' AND source_id=OLD.id;
 RETURN OLD;
END $fn$;
CREATE TRIGGER learning_interview_delete AFTER DELETE ON interview_sessions FOR EACH ROW EXECUTE FUNCTION trigger_learning_interview_delete();

CREATE FUNCTION trigger_interview_workspace_soft_delete() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM interview_sessions WHERE workspace_id=NEW.id;
 RETURN NEW;
END $fn$;
CREATE TRIGGER interview_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces FOR EACH ROW WHEN (NEW.deleted_at IS NOT NULL) EXECUTE FUNCTION trigger_interview_workspace_soft_delete();

CREATE FUNCTION trigger_module_speech_soft_delete_privacy() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
DELETE FROM module_speech_usage WHERE workspace_id=NEW.id;
 RETURN NEW;
END $fn$;
CREATE TRIGGER module_speech_soft_delete_privacy AFTER UPDATE OF deleted_at ON studio_workspaces FOR EACH ROW WHEN (NEW.deleted_at IS NOT NULL) EXECUTE FUNCTION trigger_module_speech_soft_delete_privacy();

CREATE FUNCTION trigger_module_speech_delete_audio_budget() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 VALUES(viva_date(OLD.created_at),OLD.stt_seconds,OLD.tts_chars)
 ON CONFLICT(day) DO UPDATE SET
 stt_seconds=module_speech_deleted_totals.stt_seconds+excluded.stt_seconds,
 tts_chars=module_speech_deleted_totals.tts_chars+excluded.tts_chars;
 RETURN OLD;
END $fn$;
CREATE TRIGGER module_speech_delete_audio_budget AFTER DELETE ON module_speech_usage FOR EACH ROW WHEN (OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN')) EXECUTE FUNCTION trigger_module_speech_delete_audio_budget();

CREATE FUNCTION trigger_studio_speech_delete_audio_budget() RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
BEGIN
INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 VALUES(viva_date(OLD.created_at),OLD.stt_seconds,OLD.tts_chars)
 ON CONFLICT(day) DO UPDATE SET
 stt_seconds=module_speech_deleted_totals.stt_seconds+excluded.stt_seconds,
 tts_chars=module_speech_deleted_totals.tts_chars+excluded.tts_chars;
 RETURN OLD;
END $fn$;
CREATE TRIGGER studio_speech_delete_audio_budget AFTER DELETE ON studio_speech_usage FOR EACH ROW WHEN (OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN')) EXECUTE FUNCTION trigger_studio_speech_delete_audio_budget();
