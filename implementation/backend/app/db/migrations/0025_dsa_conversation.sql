-- Durable reply identity and provider-call accounting for DSA coaching.
CREATE TABLE dsa_conversation_replies (
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
 capture_attempt_id INTEGER NOT NULL,
 transcript_hash TEXT NOT NULL,
 learner_transcript TEXT NOT NULL,
 text TEXT NOT NULL,
 source_mode TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(turn_id,capture_attempt_id,transcript_hash)
);
CREATE TABLE dsa_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL,
 capture_attempt_id INTEGER NOT NULL,
 transcript_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(turn_id,capture_attempt_id,transcript_hash)
);
CREATE INDEX dsa_model_usage_session ON dsa_model_usage(session_id,created_at);
CREATE TABLE dsa_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count INTEGER NOT NULL CHECK(request_count>=0)
);
-- Anonymous dispatch leases outlive any private owner. Uncertain dispatches
-- require explicit settlement; deleting a learner never frees that capacity.
CREATE TABLE model_dispatch_leases (
 id TEXT PRIMARY KEY,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','UNCERTAIN')),
 created_at TEXT NOT NULL
);
-- Prior pending reservations represent real outstanding work. Their independent
-- random leases are conservatively uncertain, since migration cannot establish
-- whether a provider accepted the dispatch.
INSERT INTO model_dispatch_leases(id,status,created_at)
SELECT lower(hex(randomblob(16))),'UNCERTAIN',created_at FROM studio_model_usage
 WHERE status IN ('RESERVED','UNCERTAIN');
INSERT INTO model_dispatch_leases(id,status,created_at)
SELECT lower(hex(randomblob(16))),'UNCERTAIN',created_at FROM dsa_model_usage
 WHERE status IN ('RESERVED','UNCERTAIN');
-- Usage survives individual turn deletion; owner deletion retains anonymous
-- daily totals before the foreign-key cascade removes its original identifiers.
CREATE TRIGGER dsa_session_model_accounting BEFORE DELETE ON sessions
BEGIN
 INSERT INTO dsa_model_deleted_daily(day,request_count)
 SELECT date(created_at),count(*) FROM dsa_model_usage
 WHERE session_id=OLD.id AND status IN ('RESERVED','COMMITTED','UNCERTAIN')
 GROUP BY date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count;
END;
CREATE TRIGGER dsa_session_soft_delete_accounting AFTER UPDATE OF deleted_at ON sessions
WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
BEGIN
 INSERT INTO dsa_model_deleted_daily(day,request_count)
 SELECT date(created_at),count(*) FROM dsa_model_usage
 WHERE session_id=NEW.id AND status IN ('RESERVED','COMMITTED','UNCERTAIN')
 GROUP BY date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count;
 DELETE FROM dsa_conversation_replies WHERE session_id=NEW.id;
 DELETE FROM dsa_model_usage WHERE session_id=NEW.id;
END;
