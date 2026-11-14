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
CREATE TRIGGER learning_completion_evidence BEFORE INSERT ON learning_events
WHEN NEW.kind IN ('lesson.completed','answer.evaluated')
BEGIN
 SELECT CASE WHEN NOT EXISTS (
  SELECT 1 FROM learning_answers a WHERE a.id=NEW.answer_id AND a.session_id=NEW.session_id
  AND a.workspace_id=NEW.workspace_id AND a.run=NEW.run AND (NEW.kind='answer.evaluated' OR a.correct=1)
 ) THEN RAISE(ABORT,'Learning event requires evaluated owned answer evidence') END;
END;
CREATE TRIGGER learning_completion_state BEFORE UPDATE OF state ON learning_sessions
WHEN NEW.state='completed'
BEGIN
 SELECT CASE WHEN NOT EXISTS (
  SELECT 1 FROM learning_answers a WHERE a.session_id=NEW.id AND a.workspace_id=NEW.workspace_id
  AND a.run=NEW.run AND a.correct=1
 ) THEN RAISE(ABORT,'Learning completion requires correct answer') END;
END;
CREATE TRIGGER learning_achievement_evidence BEFORE INSERT ON learning_achievements
BEGIN
 SELECT CASE WHEN NOT EXISTS (
  SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
  AND e.kind='lesson.completed' AND e.source='learning_engine'
 ) THEN RAISE(ABORT,'Achievement requires verified completion event') END;
END;
CREATE TRIGGER learning_answer_immutable BEFORE UPDATE ON learning_answers
BEGIN SELECT RAISE(ABORT,'Learning answers are immutable'); END;
CREATE TRIGGER learning_event_immutable BEFORE UPDATE ON learning_events
BEGIN SELECT RAISE(ABORT,'Learning events are immutable'); END;
CREATE TRIGGER learning_achievement_immutable BEFORE UPDATE ON learning_achievements
BEGIN SELECT RAISE(ABORT,'Learning achievements are immutable'); END;
CREATE TABLE learning_external_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source TEXT NOT NULL CHECK(source='interview'), source_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='interview.completed'), created_at TEXT NOT NULL, UNIQUE(source,source_id,kind)
);
CREATE INDEX learning_external_workspace ON learning_external_events(workspace_id,created_at);
CREATE TRIGGER learning_external_immutable BEFORE UPDATE ON learning_external_events
BEGIN SELECT RAISE(ABORT,'Learning external events are immutable'); END;
-- The interview module supplies source tables before invoking the bridge.
CREATE TRIGGER learning_interview_evidence BEFORE INSERT ON learning_external_events
BEGIN
 SELECT CASE WHEN NOT EXISTS (
  SELECT 1 FROM interview_sessions s JOIN interview_reports r ON r.session_id=s.id
  JOIN interview_events e ON e.session_id=s.id AND e.event_type='interview.completed'
  WHERE s.id=NEW.source_id AND s.workspace_id=NEW.workspace_id AND s.state='completed'
  AND s.completed_at IS NOT NULL
 ) THEN RAISE(ABORT,'Interview completion requires durable owned report and outbox') END;
END;
