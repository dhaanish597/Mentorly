-- DSA reply identity and provider-call accounting use the same runtime contract.
CREATE TABLE dsa_conversation_replies (
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
 capture_attempt_id BIGINT NOT NULL,
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
 capture_attempt_id BIGINT NOT NULL,
 transcript_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(turn_id,capture_attempt_id,transcript_hash)
);
CREATE INDEX dsa_model_usage_session ON dsa_model_usage(session_id,created_at);
CREATE TABLE dsa_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count BIGINT NOT NULL CHECK(request_count>=0)
);
CREATE TABLE model_dispatch_leases (
 id TEXT PRIMARY KEY,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','UNCERTAIN')),
 created_at TEXT NOT NULL
);
INSERT INTO model_dispatch_leases(id,status,created_at)
 SELECT gen_random_uuid()::text,'UNCERTAIN',created_at FROM studio_model_usage
 WHERE status IN ('RESERVED','UNCERTAIN');
INSERT INTO model_dispatch_leases(id,status,created_at)
 SELECT gen_random_uuid()::text,'UNCERTAIN',created_at FROM dsa_model_usage
 WHERE status IN ('RESERVED','UNCERTAIN');
CREATE FUNCTION trigger_dsa_session_model_accounting() RETURNS TRIGGER
LANGUAGE plpgsql AS $fn$
BEGIN
 INSERT INTO dsa_model_deleted_daily(day,request_count)
 SELECT viva_date(created_at),count(*) FROM dsa_model_usage
 WHERE session_id=OLD.id AND status IN ('RESERVED','COMMITTED','UNCERTAIN')
 GROUP BY viva_date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=dsa_model_deleted_daily.request_count+excluded.request_count;
 RETURN OLD;
END $fn$;
CREATE TRIGGER dsa_session_model_accounting BEFORE DELETE ON sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_dsa_session_model_accounting();
CREATE FUNCTION trigger_dsa_session_soft_delete_accounting() RETURNS TRIGGER
LANGUAGE plpgsql AS $fn$
BEGIN
 INSERT INTO dsa_model_deleted_daily(day,request_count)
 SELECT viva_date(created_at),count(*) FROM dsa_model_usage
 WHERE session_id=NEW.id AND status IN ('RESERVED','COMMITTED','UNCERTAIN')
 GROUP BY viva_date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=dsa_model_deleted_daily.request_count+excluded.request_count;
 DELETE FROM dsa_conversation_replies WHERE session_id=NEW.id;
 DELETE FROM dsa_model_usage WHERE session_id=NEW.id;
 RETURN NEW;
END $fn$;
CREATE TRIGGER dsa_session_soft_delete_accounting AFTER UPDATE OF deleted_at ON sessions
 FOR EACH ROW WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
 EXECUTE FUNCTION trigger_dsa_session_soft_delete_accounting();
