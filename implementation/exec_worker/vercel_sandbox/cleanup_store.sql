-- Apply through the PostgreSQL runtime migration runner in its private schema.
-- No job foreign key: cleanup obligations must survive job/session deletion.
CREATE TABLE viva_sandbox_cleanup (
    sandbox_name TEXT PRIMARY KEY CHECK (sandbox_name ~ '^viva-inv-[a-f0-9]{24}$'),
    job_id UUID NOT NULL,
    owner_id UUID NOT NULL,
    creation_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    cleanup_required BOOLEAN NOT NULL DEFAULT FALSE,
    recovery_not_before TIMESTAMPTZ NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '120 seconds'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX viva_sandbox_cleanup_recovery ON viva_sandbox_cleanup (recovery_not_before, created_at);
ALTER TABLE viva_sandbox_cleanup ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON viva_sandbox_cleanup FROM PUBLIC;
DO $roles$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON viva_sandbox_cleanup FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON viva_sandbox_cleanup FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON viva_sandbox_cleanup TO service_role;
    END IF;
END $roles$;
