"""Experimental job transactions; no product runtime or worker integration.

Every session writer/deleter must lock its session row first. Leases fence only
these database transitions: they cannot cancel an external computation. Expired
running jobs remain active until explicitly cancelled; there is no automatic
reclaim, provider cancellation, result delivery, or verified worker-termination workflow.
Running cancellations remain CANCEL_REQUESTED and consume admission indefinitely.
External worker termination must be enforced and proven before future recovery.
A database trigger prevents deletion of a running cleanup obligation, including
through session cascade deletion; there is no bypass or recovery API here.
"""
from dataclasses import dataclass
import uuid

from .coaching import Revision, RevisionConflictError, _lock_authorized, _require_idle
from .migrations import Migration

JOBS_MIGRATION = Migration(3, "job_coordination", """
CREATE TABLE viva_coaching_jobs (
 id UUID PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 idempotency_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,
 exercise_id TEXT NOT NULL, spec_version TEXT NOT NULL,
 code_version_id INTEGER NOT NULL, code_hash TEXT NOT NULL, turn_generation INTEGER NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','CANCEL_REQUESTED','CANCELLED','DONE')),
 owner UUID, fence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
 lease_expires_at TIMESTAMPTZ, result_json TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE (session_id,idempotency_key),
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id),
 CHECK ((status IN ('RUNNING','CANCEL_REQUESTED') AND owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status NOT IN ('RUNNING','CANCEL_REQUESTED') AND owner IS NULL AND lease_expires_at IS NULL))
);
CREATE UNIQUE INDEX viva_one_active_coaching_job ON viva_coaching_jobs(session_id)
 WHERE status IN ('QUEUED','RUNNING','CANCEL_REQUESTED');
CREATE FUNCTION viva_prevent_running_job_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status IN ('RUNNING', 'CANCEL_REQUESTED') THEN
  RAISE EXCEPTION 'Cannot delete a running job cleanup obligation' USING ERRCODE = '23514';
 END IF;
 RETURN OLD;
END;
$$;
CREATE TRIGGER viva_guard_running_job_delete BEFORE DELETE ON viva_coaching_jobs
 FOR EACH ROW EXECUTE FUNCTION viva_prevent_running_job_delete();
""")


class JobError(RuntimeError):
    """Job admission, ownership, or lifecycle conflict."""


@dataclass(frozen=True)
class Job:
    job_id: str
    status: str
    fence: int


def _begin(conn, session_id, token_hash, revision):
    conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    row = _lock_authorized(conn, session_id, token_hash)
    cv = conn.execute("SELECT code_hash FROM code_versions WHERE session_id=%s AND code_version_id=%s", (session_id,row[3])).fetchone()
    if (not isinstance(cv,tuple) or len(cv) != 1 or revision.session_id != session_id
            or (revision.exercise_id,revision.spec_version,revision.code_version_id,revision.code_hash,revision.turn_generation)
            != (row[1],row[2],row[3],cv[0],row[4])):
        raise RevisionConflictError("Full revision no longer matches the active session")


def _key(value, name, limit=256):
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise ValueError(f"Invalid {name}")


def admit(conn, *, session_id: str, token_hash: str, revision: Revision,
          idempotency_key: str, request_digest: str) -> Job:
    _key(idempotency_key, "idempotency key")
    _key(request_digest, "request digest")
    _require_idle(conn)
    with conn.transaction():
        _begin(conn, session_id, token_hash, revision)
        prior = conn.execute("""SELECT id,status,fence,request_digest,exercise_id,spec_version,code_version_id,code_hash,turn_generation
            FROM viva_coaching_jobs WHERE session_id=%s AND idempotency_key=%s""", (session_id,idempotency_key)).fetchone()
        if prior:
            if (prior[3],*prior[4:]) != (request_digest,revision.exercise_id,revision.spec_version,revision.code_version_id,revision.code_hash,revision.turn_generation):
                raise JobError("Idempotency conflict")
            return Job(str(prior[0]),prior[1],prior[2])
        active = conn.execute("SELECT id FROM viva_coaching_jobs WHERE session_id=%s AND status IN ('QUEUED','RUNNING','CANCEL_REQUESTED')", (session_id,)).fetchone()
        if active:
            raise JobError("Session already has an active job")
        job_id = str(uuid.uuid4())
        row = conn.execute("""INSERT INTO viva_coaching_jobs(id,session_id,idempotency_key,request_digest,
            exercise_id,spec_version,code_version_id,code_hash,turn_generation,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'QUEUED') RETURNING fence""",
            (job_id,session_id,idempotency_key,request_digest,revision.exercise_id,revision.spec_version,
             revision.code_version_id,revision.code_hash,revision.turn_generation)).fetchone()
        return Job(job_id,"QUEUED",row[0])


def claim(conn, *, session_id: str, token_hash: str, revision: Revision, job: Job,
          owner: str, lease_seconds: int):
    if not isinstance(owner,str):
        raise ValueError("Invalid owner")
    try:
        uuid.UUID(owner)
    except ValueError as exc:
        raise ValueError("Invalid owner") from exc
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise ValueError("Invalid lease duration")
    _require_idle(conn)
    with conn.transaction():
        _begin(conn, session_id, token_hash, revision)
        row = conn.execute("""UPDATE viva_coaching_jobs SET status='RUNNING',owner=%s,
            lease_expires_at=clock_timestamp()+make_interval(secs => %s),updated_at=clock_timestamp()
            WHERE id=%s AND session_id=%s AND fence=%s AND status='QUEUED'
            AND exercise_id=%s AND spec_version=%s AND code_version_id=%s AND code_hash=%s AND turn_generation=%s RETURNING id""",
            (owner,lease_seconds,job.job_id,session_id,job.fence,revision.exercise_id,revision.spec_version,revision.code_version_id,revision.code_hash,revision.turn_generation)).fetchone()
        if row is None:
            raise JobError("Job cannot be claimed")


def cancel(conn, *, session_id: str, token_hash: str, revision: Revision, job: Job):
    """Cancel queued work or retain a durable running-worker cleanup obligation."""
    _require_idle(conn)
    with conn.transaction():
        _begin(conn,session_id,token_hash,revision)
        row = conn.execute("""UPDATE viva_coaching_jobs SET status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE 'CANCEL_REQUESTED' END,
            updated_at=clock_timestamp()
            WHERE id=%s AND session_id=%s AND fence=%s AND status IN ('QUEUED','RUNNING') RETURNING id""", (job.job_id,session_id,job.fence)).fetchone()
        if row is None:
            raise JobError("Job cannot be cancelled")


def finish(conn, *, session_id: str, token_hash: str, revision: Revision, job: Job,
           owner: str, result_json: str):
    _key(result_json, "result", 2_000_000)
    _require_idle(conn)
    with conn.transaction():
        _begin(conn,session_id,token_hash,revision)
        row = conn.execute("""UPDATE viva_coaching_jobs SET status='DONE',owner=NULL,lease_expires_at=NULL,
            result_json=%s,updated_at=clock_timestamp() WHERE id=%s AND session_id=%s AND fence=%s
            AND status='RUNNING' AND owner=%s AND lease_expires_at > clock_timestamp()
            AND exercise_id=%s AND spec_version=%s AND code_version_id=%s AND code_hash=%s AND turn_generation=%s RETURNING id""",
            (result_json,job.job_id,session_id,job.fence,owner,revision.exercise_id,revision.spec_version,revision.code_version_id,revision.code_hash,revision.turn_generation)).fetchone()
        if row is None:
            raise JobError("Job result is stale or owner is fenced")
