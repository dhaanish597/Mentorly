"""Opt-in experimental job coordination tests, dedicated PostgreSQL DB only."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import uuid
import pytest
from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.coaching import AuthorizationError, Revision, RevisionConflictError, save_code_version
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.speech_coordination import SPEECH_MIGRATION
from backend.app.db.postgres.jobs import JOBS_MIGRATION, Job, JobError, admit, claim, cancel, finish

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_TEST_DSN to a dedicated test database")


def test_job_admission_ownership_fencing_and_stale_results():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    schema = "viva_job_test_" + uuid.uuid4().hex
    token = "a" * 64
    revision = Revision("s", "e", "v", 1, "hash", 0)
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            def connect():
                c = psycopg.connect(DSN)
                c.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                c.commit()
                return c
            def args():
                return dict(session_id="s",token_hash=token,revision=revision)
            with connect() as c:
                apply_migrations(c, [CORE_MIGRATION,SPEECH_MIGRATION,JOBS_MIGRATION])
                c.execute("INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES ('s',%s,'e','v','en','text','t','t','2099-01-01T00:00:00+00:00')", (token,))
                c.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES ('cv','s',1,'code','hash','t')")
                c.commit()
                with pytest.raises(AuthorizationError):
                    admit(c,session_id="s",token_hash="b"*64,revision=revision,idempotency_key="bad",request_digest="digest")
            barrier = threading.Barrier(4)
            def attempt(i):
                with connect() as c:
                    barrier.wait(timeout=10)
                    try:
                        return admit(c,**args(),idempotency_key=f"key{i}",request_digest="digest")
                    except JobError:
                        return None
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [f.result(timeout=15) for f in [pool.submit(attempt,i) for i in range(4)]]
            job = next(item for item in results if item is not None)
            assert sum(item is not None for item in results) == 1
            winning = results.index(job)
            owner = str(uuid.uuid4())
            with connect() as c:
                assert admit(c,**args(),idempotency_key=f"key{winning}",request_digest="digest") == job
                with pytest.raises(JobError):
                    admit(c,**args(),idempotency_key=f"key{winning}",request_digest="other")
                claim(c,**args(),job=job,owner=owner,lease_seconds=5)
                with pytest.raises(JobError):
                    finish(c,**args(),job=job,owner=str(uuid.uuid4()),result_json="{}")
                with pytest.raises(JobError):
                    finish(c,**args(),job=Job(job.job_id,job.status,job.fence+1),owner=owner,result_json="{}")
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute("DELETE FROM sessions WHERE id='s'")
                c.rollback()
                assert c.execute("SELECT status FROM viva_coaching_jobs WHERE id=%s", (job.job_id,)).fetchone() == ("RUNNING",)
                c.rollback()
                cancel(c,**args(),job=job)
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute("DELETE FROM sessions WHERE id='s'")
                c.rollback()
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute("DELETE FROM viva_coaching_jobs WHERE id=%s", (job.job_id,))
                c.rollback()
                with pytest.raises(JobError):
                    finish(c,**args(),job=job,owner=owner,result_json="{}")
                status, retained_owner, lease = c.execute(
                    "SELECT status,owner,lease_expires_at FROM viva_coaching_jobs WHERE id=%s", (job.job_id,)
                ).fetchone()
                assert (status, str(retained_owner)) == ("CANCEL_REQUESTED", owner)
                assert lease is not None
                c.rollback()
                with pytest.raises(JobError):
                    admit(c,**args(),idempotency_key="second",request_digest="digest")
                # Lease expiry is not proof that the worker physically stopped.
                c.execute("UPDATE viva_coaching_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job.job_id,))
                c.commit()
                with pytest.raises(JobError):
                    admit(c,**args(),idempotency_key="expired",request_digest="digest")
                with pytest.raises(JobError):
                    finish(c,**args(),job=job,owner=owner,result_json="{}")
                # Independent session verifies queued cancellation and normal completion.
                token3 = "d" * 64
                c.execute("INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES ('s3',%s,'e','v','en','text','t','t','2099-01-01T00:00:00+00:00')", (token3,))
                c.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES ('cv3','s3',1,'code','hash','t')")
                c.commit()
                rev3 = Revision("s3","e","v",1,"hash",0)
                args3 = dict(session_id="s3",token_hash=token3,revision=rev3)
                queued = admit(c,**args3,idempotency_key="queued",request_digest="digest")
                # A queued job has no worker and does not prevent session deletion.
                c.execute("DELETE FROM sessions WHERE id='s3'")
                c.commit()
                assert c.execute("SELECT id FROM viva_coaching_jobs WHERE id=%s", (queued.job_id,)).fetchone() is None
                c.rollback()
                c.execute("INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES ('s3',%s,'e','v','en','text','t','t','2099-01-01T00:00:00+00:00')", (token3,))
                c.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES ('cv3','s3',1,'code','hash','t')")
                c.commit()
                queued = admit(c,**args3,idempotency_key="queued",request_digest="digest")
                cancel(c,**args3,job=queued)
                done = admit(c,**args3,idempotency_key="done",request_digest="digest")
                claim(c,**args3,job=done,owner=owner,lease_seconds=5)
                finish(c,**args3,job=done,owner=owner,result_json="{}")
                assert c.execute("SELECT status,result_json FROM viva_coaching_jobs WHERE id=%s", (done.job_id,)).fetchone() == ("DONE","{}")
                c.rollback()
                # Race a real code save against admission on a separate session.
                token2 = "c" * 64
                c.execute("INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES ('s2',%s,'e','v','en','text','t','t','2099-01-01T00:00:00+00:00')", (token2,))
                c.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES ('cv2','s2',1,'old','oldhash','t')")
                c.commit()
            race_revision = Revision("s2","e","v",1,"oldhash",0)
            gate = threading.Barrier(2)
            def racing_save():
                with connect() as connection:
                    gate.wait(timeout=10)
                    return save_code_version(connection,session_id="s2",token_hash=token2,expected=race_revision,source_code="new",code_hash="newhash")
            def racing_admit():
                with connect() as connection:
                    gate.wait(timeout=10)
                    try:
                        return admit(connection,session_id="s2",token_hash=token2,revision=race_revision,idempotency_key="race",request_digest="digest")
                    except RevisionConflictError:
                        return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                save_future = pool.submit(racing_save)
                admit_future = pool.submit(racing_admit)
                assert save_future.result(timeout=15).changed
                old_job = admit_future.result(timeout=15)
            with connect() as c:
                if old_job is not None:
                    assert c.execute("SELECT status FROM viva_coaching_jobs WHERE id=%s", (old_job.job_id,)).fetchone() == ("CANCELLED",)
                    c.rollback()
                current_revision = Revision("s2","e","v",2,"newhash",1)
                new_job = admit(c,session_id="s2",token_hash=token2,revision=current_revision,idempotency_key="new",request_digest="digest")
                assert new_job.status == "QUEUED"
                claim(c,session_id="s2",token_hash=token2,revision=current_revision,job=new_job,owner=owner,lease_seconds=5)
                assert save_code_version(c,session_id="s2",token_hash=token2,expected=current_revision,source_code="newer",code_hash="newerhash").changed
                status, retained_owner, lease = c.execute("SELECT status,owner,lease_expires_at FROM viva_coaching_jobs WHERE id=%s", (new_job.job_id,)).fetchone()
                assert (status, str(retained_owner)) == ("CANCEL_REQUESTED", owner)
                assert lease is not None
                c.rollback()
                with pytest.raises(RevisionConflictError):
                    finish(c,session_id="s2",token_hash=token2,revision=current_revision,job=new_job,owner=owner,result_json="{}")
                latest = Revision("s2","e","v",3,"newerhash",2)
                with pytest.raises(JobError):
                    admit(c,session_id="s2",token_hash=token2,revision=latest,idempotency_key="latest",request_digest="digest")
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
