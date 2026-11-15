-- Actual extractor/rephrasing calls share every other model operation's budget.
CREATE TABLE legacy_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 operation TEXT NOT NULL CHECK(operation IN ('claim_extraction','coaching_phrase')),
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL
);
CREATE INDEX legacy_model_usage_session ON legacy_model_usage(session_id,created_at);
CREATE TABLE legacy_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count INTEGER NOT NULL CHECK(request_count>=0)
);
CREATE TRIGGER legacy_session_model_accounting BEFORE DELETE ON sessions
BEGIN
 INSERT INTO legacy_model_deleted_daily(day,request_count)
 SELECT date(created_at),count(*) FROM legacy_model_usage
 WHERE session_id=OLD.id GROUP BY date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count;
END;
CREATE TRIGGER legacy_session_soft_delete_accounting AFTER UPDATE OF deleted_at ON sessions
WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
BEGIN
 INSERT INTO legacy_model_deleted_daily(day,request_count)
 SELECT date(created_at),count(*) FROM legacy_model_usage
 WHERE session_id=NEW.id GROUP BY date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count;
 DELETE FROM legacy_model_usage WHERE session_id=NEW.id;
END;
