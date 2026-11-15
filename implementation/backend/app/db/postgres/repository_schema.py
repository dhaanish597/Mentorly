"""Experimental repository/redrive/module speech schema, requires v4 and v5.

No runtime, authorization, data import, repository ingestion, FTS index/search,
retention sweeper, async cancellation, provider dispatch or distributed quota
admission is supplied. Studio and module audio totals remain separate pending a
shared budget implementation. Module voice reservations are charged on deletion;
there is no safe undispatched release protocol in this slice. Source references
are polymorphic and require caller authorization, not database validation. Tables
and retained aggregates require a trusted writer; privilege separation is required
before integration. Composite ownership constraints strengthen SQLite constraints.
"""
from .migrations import Migration

REPOSITORY_MIGRATION = Migration(6, "repository_redrive_voice", r"""
CREATE TABLE repo_snapshots (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL, source_locator TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_hash TEXT,
 total_files INTEGER NOT NULL DEFAULT 0, files_indexed INTEGER NOT NULL DEFAULT 0,
 coverage_json TEXT NOT NULL DEFAULT '{}', failure_code TEXT
);
CREATE INDEX idx_repo_snapshots_workspace ON repo_snapshots(workspace_id,id);
CREATE TABLE repo_files (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 path TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, language TEXT NOT NULL,
 parse_status TEXT NOT NULL, imports_json TEXT NOT NULL, calls_json TEXT NOT NULL,
 symbols_json TEXT NOT NULL, rank REAL NOT NULL DEFAULT 0, UNIQUE(snapshot_id,path)
);
CREATE TABLE repo_chunks (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES repo_files(id) ON DELETE CASCADE, path TEXT NOT NULL,
 symbol TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
 chunk_hash TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE repo_evidence_cards (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, origin TEXT NOT NULL
);
CREATE TABLE repo_defense_sessions (
 id TEXT PRIMARY KEY, studio_session_id TEXT NOT NULL UNIQUE REFERENCES studio_sessions(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 phase TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE repo_defense_answers (
 id TEXT PRIMARY KEY, defense_id TEXT NOT NULL REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL, phase TEXT NOT NULL, answer TEXT NOT NULL, citations_json TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(defense_id,sequence)
);
CREATE TABLE repo_decisions (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, rationale TEXT NOT NULL,
 learner_alternative TEXT, created_at TEXT NOT NULL
);

-- Repository-only retry state follows every privacy deletion path through FKs.
CREATE TABLE repo_idempotency (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 operation TEXT NOT NULL, key TEXT NOT NULL, input_hash TEXT NOT NULL,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 studio_session_id TEXT REFERENCES studio_sessions(id) ON DELETE CASCADE,
 defense_id TEXT REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 evidence_card_id TEXT REFERENCES repo_evidence_cards(id) ON DELETE CASCADE,
 decision_id TEXT REFERENCES repo_decisions(id) ON DELETE CASCADE,
 response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,operation,key)
);
CREATE INDEX idx_repo_idempotency_snapshot ON repo_idempotency(snapshot_id);
CREATE INDEX idx_repo_idempotency_defense ON repo_idempotency(defense_id);

-- Keep the original answer schema compatible with existing studio consumers.
CREATE TABLE repo_defense_answer_evidence (
 answer_id TEXT PRIMARY KEY REFERENCES repo_defense_answers(id) ON DELETE CASCADE,
 evidence_links_json TEXT NOT NULL DEFAULT '[]',
 changed_requirement TEXT, learner_alternative TEXT,
 unknowns_json TEXT NOT NULL DEFAULT '[]'
);

-- Workspace-scoped passive beginner learning, separate from studio defense epochs.
CREATE TABLE repo_learning_plans (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 snapshot_hash TEXT NOT NULL,
 steps_json TEXT NOT NULL,
 cursor INTEGER NOT NULL DEFAULT 0 CHECK(cursor >= 0),
 epoch INTEGER NOT NULL DEFAULT 1 CHECK(epoch >= 1),
 revisit_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(workspace_id,snapshot_id)
);
CREATE TABLE repo_learning_attempts (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL CHECK(sequence >= 1),
 step_id TEXT NOT NULL,
 answer TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
);
CREATE TABLE repo_learning_evidence_events (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES repo_learning_attempts(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL,
 evidence_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
);
CREATE INDEX idx_repo_learning_attempts_rate ON repo_learning_attempts(created_at,plan_id);

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

ALTER TABLE repo_snapshots ADD UNIQUE(id,workspace_id);
ALTER TABLE studio_sessions ADD UNIQUE(id,workspace_id,repo_snapshot_id);
ALTER TABLE repo_evidence_cards ADD UNIQUE(id,workspace_id,snapshot_id);
ALTER TABLE repo_defense_sessions ADD UNIQUE(id,workspace_id,snapshot_id);
ALTER TABLE repo_decisions ADD UNIQUE(id,workspace_id,snapshot_id);
ALTER TABLE repo_defense_sessions ADD FOREIGN KEY (studio_session_id,workspace_id,snapshot_id)
 REFERENCES studio_sessions(id,workspace_id,repo_snapshot_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (studio_session_id,workspace_id,snapshot_id)
 REFERENCES studio_sessions(id,workspace_id,repo_snapshot_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (defense_id,workspace_id,snapshot_id)
 REFERENCES repo_defense_sessions(id,workspace_id,snapshot_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (evidence_card_id,workspace_id,snapshot_id)
 REFERENCES repo_evidence_cards(id,workspace_id,snapshot_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (decision_id,workspace_id,snapshot_id)
 REFERENCES repo_decisions(id,workspace_id,snapshot_id) ON DELETE CASCADE;
ALTER TABLE repo_files ADD UNIQUE(id,snapshot_id);
ALTER TABLE repo_chunks ADD FOREIGN KEY (file_id,snapshot_id) REFERENCES repo_files(id,snapshot_id) ON DELETE CASCADE;
ALTER TABLE repo_evidence_cards ADD UNIQUE(id,workspace_id);
ALTER TABLE repo_evidence_cards ADD FOREIGN KEY (snapshot_id,workspace_id) REFERENCES repo_snapshots(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_defense_sessions ADD UNIQUE(id,workspace_id);
ALTER TABLE repo_defense_sessions ADD FOREIGN KEY (snapshot_id,workspace_id) REFERENCES repo_snapshots(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_defense_sessions ADD FOREIGN KEY (studio_session_id,workspace_id) REFERENCES studio_sessions(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_decisions ADD UNIQUE(id,workspace_id);
ALTER TABLE repo_decisions ADD FOREIGN KEY (snapshot_id,workspace_id) REFERENCES repo_snapshots(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (snapshot_id,workspace_id) REFERENCES repo_snapshots(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (studio_session_id,workspace_id) REFERENCES studio_sessions(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (defense_id,workspace_id) REFERENCES repo_defense_sessions(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (evidence_card_id,workspace_id) REFERENCES repo_evidence_cards(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_idempotency ADD FOREIGN KEY (decision_id,workspace_id) REFERENCES repo_decisions(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_learning_plans ADD FOREIGN KEY (snapshot_id,workspace_id) REFERENCES repo_snapshots(id,workspace_id) ON DELETE CASCADE;
ALTER TABLE repo_learning_attempts ADD UNIQUE(id,plan_id);
ALTER TABLE repo_learning_evidence_events ADD FOREIGN KEY (attempt_id,plan_id) REFERENCES repo_learning_attempts(id,plan_id) ON DELETE CASCADE;
CREATE TABLE module_speech_deleted_totals (
 day TEXT PRIMARY KEY, stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(stt_seconds>=0),
 tts_chars BIGINT NOT NULL DEFAULT 0 CHECK(tts_chars>=0)
);
-- Reconstruct conservative bounds for prior anonymous deletions, as SQLite does.
INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 SELECT day,request_count*30.0,request_count*8000 FROM studio_speech_deleted_daily WHERE request_count>0;
CREATE FUNCTION module_speech_preserve_usage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE usage_day text := studio_usage_day(OLD.created_at);
BEGIN
 INSERT INTO studio_speech_deleted_daily VALUES(usage_day,OLD.request_count)
  ON CONFLICT(day) DO UPDATE SET request_count=studio_speech_deleted_daily.request_count+EXCLUDED.request_count;
 INSERT INTO module_speech_deleted_totals VALUES(usage_day,OLD.stt_seconds,OLD.tts_chars)
  ON CONFLICT(day) DO UPDATE SET stt_seconds=module_speech_deleted_totals.stt_seconds+EXCLUDED.stt_seconds,
   tts_chars=module_speech_deleted_totals.tts_chars+EXCLUDED.tts_chars;
 RETURN OLD;
END $$;
CREATE TRIGGER module_speech_delete_accounting AFTER DELETE ON module_speech_usage FOR EACH ROW EXECUTE FUNCTION module_speech_preserve_usage();
CREATE FUNCTION repo_event_matches(payload text, snapshot text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE obj jsonb;
BEGIN
 obj := payload::jsonb;
 RETURN obj->>'source'='authored_repo_defense' AND obj->>'snapshot_id'=snapshot;
EXCEPTION WHEN invalid_text_representation THEN RETURN false;
END $$;
CREATE FUNCTION repo_snapshot_event_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 DELETE FROM studio_events WHERE event_type='coach.action' AND repo_event_matches(payload_json,OLD.id);
 RETURN OLD;
END $$;
CREATE TRIGGER repo_snapshot_delete_authored_prompt_events BEFORE DELETE ON repo_snapshots FOR EACH ROW EXECUTE FUNCTION repo_snapshot_event_cleanup();
CREATE FUNCTION repo_workspace_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.deleted_at IS NOT NULL THEN
  DELETE FROM repo_snapshots WHERE workspace_id=NEW.id;
  DELETE FROM module_speech_usage WHERE workspace_id=NEW.id;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER repo_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces FOR EACH ROW EXECUTE FUNCTION repo_workspace_cleanup();
CREATE FUNCTION repo_studio_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.deleted_at IS NOT NULL THEN DELETE FROM repo_defense_sessions WHERE studio_session_id=NEW.id; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER repo_studio_soft_delete AFTER UPDATE OF deleted_at ON studio_sessions FOR EACH ROW EXECUTE FUNCTION repo_studio_cleanup();
""")
