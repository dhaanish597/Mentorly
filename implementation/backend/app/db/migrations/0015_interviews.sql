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
CREATE TRIGGER interview_report_immutable BEFORE UPDATE ON interview_reports
BEGIN
 SELECT RAISE(ABORT,'Interview reports are immutable');
END;
CREATE TABLE interview_events (
 session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
);
CREATE UNIQUE INDEX interview_single_completion ON interview_events(session_id)
 WHERE event_type='interview.completed';
