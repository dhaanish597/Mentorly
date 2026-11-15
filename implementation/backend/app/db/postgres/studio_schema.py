"""Experimental PostgreSQL Studio schema and local privacy primitives.

No API, authentication, concurrent admission, worker cancellation, expiry sweep,
repository/module-voice schema, or SQLite data migration is included. Speech
callers must commit the dispatch mark before provider I/O and use guarded release;
any bypass makes reservation accounting unsafe. Tables and aggregate totals remain
mutable by the database role: use only a trusted runtime role and do not integrate
until least-privilege grants and ownership are designed and verified. This schema
does not defend accounting against a compromised database writer. The caller
must tombstone expired workspaces/sessions and cancel external tasks. Anonymous
usage is retained by deletion triggers; dates that cannot be parsed are kept in
an 'unknown' bucket. Retained audio totals are Studio-only, not a replacement for
the SQLite shared module speech budget. Review-card ownership is strengthened.
"""
from .migrations import Migration

STUDIO_MIGRATION = Migration(4, "studio_schema", r"""
CREATE TABLE studio_workspaces (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE studio_sessions (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id), token_hash TEXT NOT NULL,
 mode TEXT NOT NULL, posture TEXT NOT NULL, scenario_id TEXT NOT NULL, scenario_version TEXT NOT NULL,
 repo_snapshot_id TEXT, epoch INTEGER NOT NULL DEFAULT 1, diagram_revision INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, expires_at TEXT NOT NULL, deleted_at TEXT,
 deadline_at TEXT, paused_at TEXT, remaining_seconds INTEGER, scenario_hash TEXT NOT NULL DEFAULT '', scenario_json TEXT NOT NULL DEFAULT '{}', constraint_index INTEGER NOT NULL DEFAULT 0, hint_level INTEGER NOT NULL DEFAULT 0, cleaned_at TEXT, UNIQUE(id, workspace_id)
);
CREATE INDEX studio_session_workspace ON studio_sessions(workspace_id);
CREATE TABLE studio_diagrams (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, revision INTEGER NOT NULL,
 parent_revision INTEGER, graph_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,revision)
);
CREATE TABLE studio_events (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, sequence INTEGER NOT NULL,
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
);
CREATE TABLE studio_idempotency (
 owner_id TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, key TEXT NOT NULL,
 digest TEXT NOT NULL, status INTEGER NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,method,path,key)
);
CREATE TABLE studio_turns (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch INTEGER NOT NULL, diagram_revision INTEGER NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(session_id,id)
);
CREATE TABLE studio_proposals (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 base_revision INTEGER NOT NULL, graph_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE studio_review_cards (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL,
 FOREIGN KEY (session_id,workspace_id) REFERENCES studio_sessions(id,workspace_id) ON DELETE CASCADE,
 prompt TEXT NOT NULL, evidence_json TEXT NOT NULL, fsrs_json TEXT NOT NULL, due_at TEXT NOT NULL
);
CREATE INDEX studio_review_due ON studio_review_cards(workspace_id,due_at);

-- Preserve immutable learner content while linking successive corrections.
ALTER TABLE studio_turns ADD COLUMN transcript_revision INTEGER NOT NULL DEFAULT 1 CHECK(transcript_revision >= 1);
ALTER TABLE studio_turns ADD COLUMN superseded_by TEXT;
ALTER TABLE studio_turns ADD CONSTRAINT studio_turn_same_session_successor
 FOREIGN KEY (session_id,superseded_by) REFERENCES studio_turns(session_id,id) ON DELETE SET NULL (superseded_by);
CREATE INDEX studio_turns_current ON studio_turns(session_id,superseded_by,created_at);

CREATE TABLE studio_speech_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, epoch INTEGER NOT NULL,
 operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 stt_seconds REAL NOT NULL DEFAULT 0 CHECK(stt_seconds >= 0), tts_chars INTEGER NOT NULL DEFAULT 0 CHECK(tts_chars >= 0),
 request_count INTEGER NOT NULL CHECK(request_count >= 0), status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 dispatch_state TEXT NOT NULL DEFAULT 'UNDISPATCHED' CHECK(dispatch_state IN ('UNDISPATCHED','DISPATCHED','RELEASED')),
 UNIQUE(session_id,operation,idempotency_key)
);
CREATE INDEX studio_speech_usage_daily ON studio_speech_usage(created_at,status);
CREATE TABLE studio_speech_deleted_daily (day TEXT PRIMARY KEY, request_count INTEGER NOT NULL);

CREATE TABLE studio_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch INTEGER NOT NULL,
 idempotency_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(session_id,idempotency_key)
);
CREATE INDEX studio_model_daily ON studio_model_usage(created_at,status);
CREATE TABLE studio_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count INTEGER NOT NULL CHECK(request_count >= 0)
);

CREATE TABLE studio_speech_deleted_audio (
 day TEXT PRIMARY KEY, stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
 tts_chars BIGINT NOT NULL DEFAULT 0
);
CREATE FUNCTION studio_usage_day(value text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF value !~ '^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([zZ]|[+-]\d{2}:\d{2})?)?$' THEN RETURN 'unknown'; END IF;
 IF value ~ '([zZ]|[+-]\d{2}:\d{2})$' THEN
  RETURN ((value::timestamptz AT TIME ZONE 'UTC')::date)::text;
 END IF;
 RETURN (value::timestamp::date)::text;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_time_zone_displacement_value THEN
 RETURN 'unknown';
END $$;
CREATE FUNCTION studio_guard_speech_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status <> 'RESERVED' OR NEW.dispatch_state <> 'UNDISPATCHED' THEN
  RAISE EXCEPTION 'Speech reservations must start undispatched';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER studio_speech_insert_guard BEFORE INSERT ON studio_speech_usage FOR EACH ROW EXECUTE FUNCTION studio_guard_speech_insert();
CREATE FUNCTION studio_guard_speech_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.id,NEW.session_id,NEW.epoch,NEW.operation,NEW.idempotency_key,NEW.request_digest,
     NEW.stt_seconds,NEW.tts_chars,NEW.request_count,NEW.created_at)
    IS DISTINCT FROM
    (OLD.id,OLD.session_id,OLD.epoch,OLD.operation,OLD.idempotency_key,OLD.request_digest,
     OLD.stt_seconds,OLD.tts_chars,OLD.request_count,OLD.created_at) THEN
  RAISE EXCEPTION 'Speech reservation identity and accounting are immutable';
 END IF;
 IF NEW.dispatch_state IS DISTINCT FROM OLD.dispatch_state AND NOT
   (OLD.dispatch_state='UNDISPATCHED' AND OLD.status='RESERVED'
    AND NEW.status='RESERVED' AND NEW.dispatch_state IN ('DISPATCHED','RELEASED')) THEN
  RAISE EXCEPTION 'Invalid speech dispatch transition';
 END IF;
 IF NEW.status IS DISTINCT FROM OLD.status AND NOT
   (OLD.status='RESERVED' AND OLD.dispatch_state='DISPATCHED'
    AND NEW.dispatch_state='DISPATCHED' AND NEW.status IN ('COMMITTED','UNCERTAIN')) THEN
  RAISE EXCEPTION 'Invalid speech settlement transition';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER studio_speech_update_guard BEFORE UPDATE ON studio_speech_usage FOR EACH ROW EXECUTE FUNCTION studio_guard_speech_update();
CREATE FUNCTION studio_account_deleted_usage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE usage_day text := studio_usage_day(OLD.created_at);
BEGIN
 IF TG_TABLE_NAME='studio_speech_usage' THEN
  IF OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN') AND OLD.dispatch_state <> 'RELEASED' THEN
   INSERT INTO studio_speech_deleted_daily VALUES(usage_day,OLD.request_count)
    ON CONFLICT(day) DO UPDATE SET request_count=studio_speech_deleted_daily.request_count+EXCLUDED.request_count;
   INSERT INTO studio_speech_deleted_audio VALUES(usage_day,OLD.stt_seconds,OLD.tts_chars)
    ON CONFLICT(day) DO UPDATE SET stt_seconds=studio_speech_deleted_audio.stt_seconds+EXCLUDED.stt_seconds,
      tts_chars=studio_speech_deleted_audio.tts_chars+EXCLUDED.tts_chars;
  END IF;
 ELSE
  INSERT INTO studio_model_deleted_daily VALUES(usage_day,1)
   ON CONFLICT(day) DO UPDATE SET request_count=studio_model_deleted_daily.request_count+1;
 END IF;
 RETURN OLD;
END $$;
CREATE TRIGGER studio_speech_usage_retention AFTER DELETE ON studio_speech_usage FOR EACH ROW EXECUTE FUNCTION studio_account_deleted_usage();
CREATE TRIGGER studio_model_usage_retention AFTER DELETE ON studio_model_usage FOR EACH ROW EXECUTE FUNCTION studio_account_deleted_usage();
-- All dispatchers must commit this mark before external I/O; the row update serializes
-- with release and privacy deletion. Unknown results must remain charged.
CREATE FUNCTION studio_mark_speech_dispatched(reservation_id text) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
 UPDATE studio_speech_usage SET dispatch_state='DISPATCHED'
  WHERE id=reservation_id AND status='RESERVED' AND dispatch_state='UNDISPATCHED';
 RETURN FOUND;
END $$;
CREATE FUNCTION studio_release_undispatched_speech(reservation_id text) RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
 UPDATE studio_speech_usage SET dispatch_state='RELEASED'
  WHERE id=reservation_id AND status='RESERVED' AND dispatch_state='UNDISPATCHED';
 IF NOT FOUND THEN RETURN false; END IF;
 DELETE FROM studio_speech_usage WHERE id=reservation_id AND dispatch_state='RELEASED';
 RETURN true;
END $$;
CREATE FUNCTION studio_purge_session() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.deleted_at IS NOT NULL THEN
  DELETE FROM studio_speech_usage WHERE session_id=NEW.id;
  DELETE FROM studio_model_usage WHERE session_id=NEW.id;
  DELETE FROM studio_review_cards WHERE session_id=NEW.id;
  DELETE FROM studio_diagrams WHERE session_id=NEW.id;
  DELETE FROM studio_events WHERE session_id=NEW.id;
  DELETE FROM studio_turns WHERE session_id=NEW.id;
  DELETE FROM studio_proposals WHERE session_id=NEW.id;
  DELETE FROM studio_idempotency WHERE owner_id=NEW.id;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER studio_session_tombstone AFTER UPDATE OF deleted_at ON studio_sessions FOR EACH ROW EXECUTE FUNCTION studio_purge_session();
CREATE FUNCTION studio_purge_workspace() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.deleted_at IS NOT NULL THEN
  UPDATE studio_sessions SET deleted_at=NEW.deleted_at, epoch=epoch+1 WHERE workspace_id=NEW.id AND deleted_at IS NULL;
  DELETE FROM studio_idempotency WHERE owner_id=NEW.id;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER studio_workspace_tombstone AFTER UPDATE OF deleted_at ON studio_workspaces FOR EACH ROW EXECUTE FUNCTION studio_purge_workspace();
""")
