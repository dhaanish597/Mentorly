-- Fixed zero-cost ceilings. Reservations are never refunded, including unknown creates.
CREATE TABLE cloud_execution_budget (
    period_kind TEXT NOT NULL CHECK(period_kind IN ('MONTH','DAY')),
    period TEXT NOT NULL,
    invocations BIGINT NOT NULL DEFAULT 0 CHECK(invocations>=0 AND invocations<=CASE WHEN period_kind='MONTH' THEN 500 ELSE 100 END),
    PRIMARY KEY(period_kind,period)
);
-- Cancellation survives deleted application jobs and process restarts.
CREATE TABLE cloud_execution_jobs (
    job_id TEXT PRIMARY KEY,
    owner_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX cloud_execution_single_job ON cloud_execution_jobs(active) WHERE active;
ALTER TABLE cloud_execution_budget ENABLE ROW LEVEL SECURITY;
ALTER TABLE cloud_execution_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON cloud_execution_budget,cloud_execution_jobs FROM PUBLIC;
DO $roles$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
        REVOKE ALL ON cloud_execution_budget,cloud_execution_jobs FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
        REVOKE ALL ON cloud_execution_budget,cloud_execution_jobs FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON cloud_execution_budget,cloud_execution_jobs TO service_role;
    END IF;
END $roles$;
