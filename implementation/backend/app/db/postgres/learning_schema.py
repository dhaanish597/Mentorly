"""Experimental learning/interview DDL, independent of product runtime.

Requires a PostgreSQL studio_workspaces table with id and deleted_at columns.
This is schema-only: no authentication, service transactions, import of existing
SQLite records, expiry cleanup, or PostgreSQL runtime wiring is provided.
Dates remain TEXT to match SQLite storage. Achievement dates accept ISO dates
and timestamps; invalid text is excluded and timezone-naive values are UTC.
Other SQLite date syntaxes are not supported. Workspace tombstones purge learning
and interview records. This migration cannot retrofit already-existing tables.
"""
from .migrations import Migration

LEARNING_MIGRATION = Migration(5, "learning_interview", r"""
-- Learning owns its evidence; workspace capabilities are not copied into this aggregate.
CREATE TABLE learning_sessions (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 lesson_id TEXT NOT NULL, catalog_version TEXT NOT NULL, content_hash TEXT NOT NULL,
 lesson_json TEXT NOT NULL, language_mode TEXT NOT NULL,
 epoch INTEGER NOT NULL DEFAULT 1 CHECK(epoch>=1), run INTEGER NOT NULL DEFAULT 1 CHECK(run>=1),
 state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','completed','exhausted')),
 answer_count INTEGER NOT NULL DEFAULT 0 CHECK(answer_count BETWEEN 0 AND 5),
 hint_count INTEGER NOT NULL DEFAULT 0 CHECK(hint_count BETWEEN 0 AND 3),
 coach_messages_json TEXT NOT NULL, feedback_json TEXT, report_json TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(id,workspace_id)
);
CREATE INDEX learning_session_workspace ON learning_sessions(workspace_id,state,updated_at);
CREATE TABLE learning_answers (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 run INTEGER NOT NULL CHECK(run>=1), epoch INTEGER NOT NULL CHECK(epoch>=1),
 question_id TEXT NOT NULL, answer TEXT NOT NULL CHECK(length(answer) BETWEEN 1 AND 2000),
 correct INTEGER NOT NULL CHECK(correct IN (0,1)), evaluation_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,workspace_id) REFERENCES learning_sessions(id,workspace_id) ON DELETE CASCADE,
 UNIQUE(session_id,epoch)
);
CREATE INDEX learning_answer_session ON learning_answers(session_id,run);
CREATE TABLE learning_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL, run INTEGER NOT NULL CHECK(run>=1),
 kind TEXT NOT NULL CHECK(kind IN ('session.started','session.restarted','answer.evaluated','hint.requested','lesson.completed')),
 source TEXT NOT NULL CHECK(source='learning_engine'), answer_id TEXT REFERENCES learning_answers(id) ON DELETE CASCADE,
 study_seconds INTEGER NOT NULL DEFAULT 0 CHECK(study_seconds BETWEEN 0 AND 300), created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,workspace_id) REFERENCES learning_sessions(id,workspace_id) ON DELETE CASCADE
);
CREATE INDEX learning_event_workspace ON learning_events(workspace_id,created_at);
CREATE UNIQUE INDEX learning_run_completion ON learning_events(session_id,run) WHERE kind='lesson.completed';
CREATE UNIQUE INDEX learning_answer_event ON learning_events(answer_id,kind) WHERE answer_id IS NOT NULL;
CREATE TABLE learning_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL, title TEXT NOT NULL, earned_at TEXT NOT NULL,
 source_event TEXT NOT NULL REFERENCES learning_events(id) ON DELETE CASCADE,
 PRIMARY KEY(workspace_id,id)
);
CREATE TABLE learning_external_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source TEXT NOT NULL CHECK(source='interview'), source_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='interview.completed'), created_at TEXT NOT NULL, UNIQUE(source,source_id,kind)
);
CREATE INDEX learning_external_workspace ON learning_external_events(workspace_id,created_at);

-- Workspace capability-owned interviews; reports and completion outbox are atomic.
CREATE TABLE interview_sessions (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 type TEXT NOT NULL CHECK(type IN ('dsa','cs','system_design','codebase_defense')),
 difficulty TEXT NOT NULL CHECK(difficulty IN ('beginner','intermediate','advanced')),
 topics_json TEXT NOT NULL, duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 5 AND 60),
 language_mode TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>=1),
 state TEXT NOT NULL CHECK(state IN ('active','completed')),
 started_at TEXT NOT NULL, deadline_at TEXT NOT NULL, completed_at TEXT,
 completion_reason TEXT, plan_json TEXT NOT NULL,
 CHECK((state='active' AND completed_at IS NULL) OR (state='completed' AND completed_at IS NOT NULL))
);
CREATE INDEX interview_workspace ON interview_sessions(workspace_id,started_at);
CREATE INDEX interview_deadline ON interview_sessions(state,deadline_at);
CREATE TABLE interview_questions (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL, epoch INTEGER NOT NULL,
 question_json TEXT NOT NULL, asked_at TEXT NOT NULL,
 UNIQUE(session_id,sequence), UNIQUE(session_id,epoch), UNIQUE(session_id,id)
);
CREATE TABLE interview_answers (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 question_id TEXT NOT NULL UNIQUE, epoch INTEGER NOT NULL, answer TEXT NOT NULL,
 code TEXT, created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,question_id) REFERENCES interview_questions(session_id,id),
 UNIQUE(session_id,epoch)
);
CREATE TABLE interview_reports (
 session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
 report_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE interview_events (
 session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
);
CREATE UNIQUE INDEX interview_single_completion ON interview_events(session_id)
 WHERE event_type='interview.completed';

-- Additive upgrade: never change already-applied 0014 learning checksums.
CREATE TABLE learning_evidence_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL CHECK(id IN ('first_interview','three_study_days')),
 title TEXT NOT NULL, earned_at TEXT NOT NULL, source_event TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('learning_engine','interview')),
 PRIMARY KEY(workspace_id,id)
);

CREATE FUNCTION learning_evidence_date(value text) RETURNS date LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 -- Restrict parsing to ISO forms; PostgreSQL otherwise accepts session-dependent dates.
 IF value !~ '^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([zZ]|[+-]\d{2}:\d{2})?)?$' THEN
  RETURN NULL;
 END IF;
 IF value ~ '([zZ]|[+-]\d{2}:\d{2})$' THEN
  RETURN (value::timestamptz AT TIME ZONE 'UTC')::date;
 END IF;
 RETURN value::timestamp::date;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_time_zone_displacement_value THEN
 RETURN NULL;
END $$;
CREATE FUNCTION learning_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='learning_events' THEN
  IF NEW.kind IN ('lesson.completed','answer.evaluated') AND NOT EXISTS (
   SELECT 1 FROM learning_answers a WHERE a.id=NEW.answer_id AND a.session_id=NEW.session_id
   AND a.workspace_id=NEW.workspace_id AND a.run=NEW.run AND (NEW.kind='answer.evaluated' OR a.correct=1)) THEN
   RAISE EXCEPTION 'Learning event requires evaluated owned answer evidence'; END IF;
 ELSIF TG_TABLE_NAME='learning_sessions' THEN
  IF NEW.state='completed' AND NOT EXISTS (SELECT 1 FROM learning_answers a WHERE a.session_id=NEW.id
   AND a.workspace_id=NEW.workspace_id AND a.run=NEW.run AND a.correct=1) THEN
   RAISE EXCEPTION 'Learning completion requires correct answer'; END IF;
 ELSIF TG_TABLE_NAME='learning_achievements' THEN
  IF NOT EXISTS (SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
   AND e.kind='lesson.completed' AND e.source='learning_engine') THEN RAISE EXCEPTION 'Achievement requires verified completion event'; END IF;
 ELSIF TG_TABLE_NAME='learning_external_events' THEN
  IF NOT EXISTS (SELECT 1 FROM interview_sessions s JOIN interview_reports r ON r.session_id=s.id
   JOIN interview_events e ON e.session_id=s.id AND e.event_type='interview.completed'
   WHERE s.id=NEW.source_id AND s.workspace_id=NEW.workspace_id AND s.state='completed' AND s.completed_at IS NOT NULL)
   THEN RAISE EXCEPTION 'Interview completion requires durable owned report and outbox'; END IF;
 ELSIF TG_TABLE_NAME='learning_evidence_achievements' THEN
  IF NOT ((NEW.id='first_interview' AND NEW.source='interview' AND EXISTS
   (SELECT 1 FROM learning_external_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id AND e.source='interview' AND e.kind='interview.completed')) OR
   (NEW.id='three_study_days' AND NEW.source='learning_engine' AND EXISTS
    (SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
     AND e.kind IN ('answer.evaluated','hint.requested') AND learning_evidence_date(e.created_at)=learning_evidence_date(NEW.earned_at))
    AND (SELECT count(DISTINCT learning_evidence_date(e.created_at)) FROM learning_events e WHERE e.workspace_id=NEW.workspace_id
     AND e.kind IN ('answer.evaluated','hint.requested') AND learning_evidence_date(e.created_at) BETWEEN learning_evidence_date(NEW.earned_at)-2 AND learning_evidence_date(NEW.earned_at))=3))
   THEN RAISE EXCEPTION 'Achievement requires verified owned evidence and threshold'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER learning_completion_evidence BEFORE INSERT ON learning_events FOR EACH ROW EXECUTE FUNCTION learning_guard();
CREATE TRIGGER learning_completion_state BEFORE UPDATE OF state ON learning_sessions FOR EACH ROW EXECUTE FUNCTION learning_guard();
CREATE TRIGGER learning_achievement_evidence BEFORE INSERT ON learning_achievements FOR EACH ROW EXECUTE FUNCTION learning_guard();
CREATE TRIGGER learning_interview_evidence BEFORE INSERT ON learning_external_events FOR EACH ROW EXECUTE FUNCTION learning_guard();
CREATE TRIGGER learning_evidence_achievement_guard BEFORE INSERT ON learning_evidence_achievements FOR EACH ROW EXECUTE FUNCTION learning_guard();
CREATE FUNCTION learning_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Evidence is immutable'; END $$;
CREATE TRIGGER learning_answer_immutable BEFORE UPDATE ON learning_answers FOR EACH ROW EXECUTE FUNCTION learning_immutable();
CREATE TRIGGER learning_event_immutable BEFORE UPDATE ON learning_events FOR EACH ROW EXECUTE FUNCTION learning_immutable();
CREATE TRIGGER learning_achievement_immutable BEFORE UPDATE ON learning_achievements FOR EACH ROW EXECUTE FUNCTION learning_immutable();
CREATE TRIGGER learning_external_immutable BEFORE UPDATE ON learning_external_events FOR EACH ROW EXECUTE FUNCTION learning_immutable();
CREATE TRIGGER learning_evidence_achievement_immutable BEFORE UPDATE ON learning_evidence_achievements FOR EACH ROW EXECUTE FUNCTION learning_immutable();
CREATE TRIGGER interview_report_immutable BEFORE UPDATE ON interview_reports FOR EACH ROW EXECUTE FUNCTION learning_immutable();
CREATE FUNCTION learning_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='studio_workspaces' THEN
  IF NEW.deleted_at IS NOT NULL THEN
   DELETE FROM interview_sessions WHERE workspace_id=NEW.id;
   DELETE FROM learning_sessions WHERE workspace_id=NEW.id;
   DELETE FROM learning_external_events WHERE workspace_id=NEW.id;
   DELETE FROM learning_evidence_achievements WHERE workspace_id=NEW.id;
  END IF;
 ELSIF TG_TABLE_NAME='interview_sessions' THEN
  DELETE FROM learning_external_events WHERE source='interview' AND source_id=OLD.id;
 ELSIF TG_TABLE_NAME='learning_events' THEN
  DELETE FROM learning_evidence_achievements WHERE source='learning_engine' AND source_event=OLD.id;
 ELSE DELETE FROM learning_evidence_achievements WHERE source='interview' AND source_event=OLD.id;
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER learning_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces FOR EACH ROW EXECUTE FUNCTION learning_cleanup();
CREATE TRIGGER learning_interview_delete AFTER DELETE ON interview_sessions FOR EACH ROW EXECUTE FUNCTION learning_cleanup();
CREATE TRIGGER learning_action_badge_cascade AFTER DELETE ON learning_events FOR EACH ROW EXECUTE FUNCTION learning_cleanup();
CREATE TRIGGER learning_external_badge_cascade AFTER DELETE ON learning_external_events FOR EACH ROW EXECUTE FUNCTION learning_cleanup();
DELETE FROM interview_sessions WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
DELETE FROM learning_sessions WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
DELETE FROM learning_external_events WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
DELETE FROM learning_evidence_achievements WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
""")
