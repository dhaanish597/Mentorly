"""Experimental lifecycle primitives; not connected to the product runtime.

Requires PostgreSQL migrations 1 and 3. Callers must cooperate with the session
row lock, keep capabilities secret, provide an independently authenticated cleanup authority, and
commit tombstones before requesting external termination. Tombstoning blocks
access and requests cancellation but retains private rows until audio and running
worker cleanup are attested, then finalize physically cascades the session. This module exposes no acknowledgement
operation; external cleanup verification remains unimplemented and must be designed
before integration. No
external worker/audio cancellation, scheduled sweeper, HTTP validation, full
restore/export, backup deletion, or SQLite import is provided. A trusted database
role is required; authorization does not defend against direct database writers.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

from .coaching import _lock_authorized, _require_idle
from .migrations import Migration

SESSION_LIFECYCLE_MIGRATION = Migration(8, 'session_lifecycle', """
CREATE TABLE viva_session_legacy_cleanup (
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 job_id TEXT NOT NULL, PRIMARY KEY(session_id,job_id)
);
CREATE TABLE viva_session_cleanup (
 session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
 audio_pending BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
""")


def _digest(token):
    if not isinstance(token, str) or not 1 <= len(token) <= 512:
        return '0' * 64
    return hashlib.sha256(token.encode()).hexdigest()


def _text(value, name, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError('Invalid ' + name)


def create_session(conn, *, exercise_id, spec_version, language_mode, interaction_mode,
                   source_code, lifetime_seconds=86400):
    _require_idle(conn)
    for name, value in (('exercise',exercise_id),('spec',spec_version),('language',language_mode),('interaction',interaction_mode)):
        _text(value, name, 128)
    if not isinstance(source_code,str) or len(source_code) > 200000:
        raise ValueError('Invalid source code')
    if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 30*86400:
        raise ValueError('Invalid lifetime')
    sid, code_id, token = str(uuid.uuid4()), str(uuid.uuid4()), secrets.token_urlsafe(32)
    timestamp = datetime.now(timezone.utc)
    created, expiry = timestamp.isoformat(), (timestamp+timedelta(seconds=lifetime_seconds)).isoformat()
    code_hash = hashlib.sha256(source_code.encode()).hexdigest()
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        conn.execute('''INSERT INTO sessions(id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (sid,_digest(token),exercise_id,spec_version,language_mode,interaction_mode,created,created,expiry))
        conn.execute('''INSERT INTO code_versions(id,session_id,code_version_id,source_code,code_hash,created_at)
                     VALUES (%s,%s,1,%s,%s,%s)''',(code_id,sid,source_code,code_hash,created))
    return {'session_id':sid,'token':token,'expires_at':expiry,'code_hash':code_hash}


def restore_session(conn, *, session_id, token):
    _require_idle(conn)
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        row = _lock_authorized(conn, session_id, _digest(token))
        code = conn.execute('SELECT source_code,code_hash FROM code_versions WHERE session_id=%s AND code_version_id=%s', (session_id,row[3])).fetchone()
        if not isinstance(code,tuple) or len(code)!=2:
            raise RuntimeError('Active code version missing')
        return {'session_id':session_id,'exercise_id':row[1],'spec_version':row[2],
                'code_version_id':row[3],'turn_generation':row[4], 'source_code':code[0],'code_hash':code[1]}


def _tombstone_locked(conn, session_id):
    conn.execute("UPDATE sessions SET deleted_at=%s,updated_at=%s,active_turn_generation=active_turn_generation+1 WHERE id=%s AND deleted_at IS NULL", (datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat(),session_id))
    conn.execute("INSERT INTO viva_session_cleanup(session_id) VALUES (%s) ON CONFLICT DO NOTHING", (session_id,))
    conn.execute("UPDATE viva_coaching_jobs SET status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE 'CANCEL_REQUESTED' END,updated_at=clock_timestamp() WHERE session_id=%s AND status IN ('QUEUED','RUNNING')",(session_id,))
    # Legacy worker records lack fencing/cleanup proof. Persist an independent
    # obligation before changing their state, and never infer process termination.
    conn.execute("INSERT INTO viva_session_legacy_cleanup(session_id,job_id) SELECT session_id,id FROM jobs WHERE session_id=%s AND status='RUNNING' ON CONFLICT DO NOTHING",(session_id,))
    conn.execute("UPDATE jobs SET status='SUPERSEDED',updated_at=%s WHERE session_id=%s AND status IN ('QUEUED','RUNNING')",(datetime.now(timezone.utc).isoformat(),session_id))


def delete_session(conn, *, session_id, token):
    _require_idle(conn)
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        _lock_authorized(conn, session_id, _digest(token))
        _tombstone_locked(conn, session_id)


def expire_session(conn, *, session_id):
    """Trusted retention worker tombstones one expired session; malformed expiry fails closed."""
    _require_idle(conn)
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        row=conn.execute('SELECT expires_at,deleted_at FROM sessions WHERE id=%s FOR UPDATE',(session_id,)).fetchone()
        if row is None or row[1] is not None:
            return False
        try:
            expiry=datetime.fromisoformat(row[0])
            expired=expiry.utcoffset() is not None and expiry <= datetime.now(timezone.utc)
        except (TypeError,ValueError,OverflowError):
            expired=False
        if not expired: return False
        _tombstone_locked(conn,session_id)
        return True


def finalize_deletion(conn, *, session_id):
    """Trusted cleanup worker removes session only after all durable obligations clear."""
    _require_idle(conn)
    with conn.transaction():
        row=conn.execute('SELECT deleted_at FROM sessions WHERE id=%s FOR UPDATE',(session_id,)).fetchone()
        if row is None or row[0] is None: return False
        pending=conn.execute("SELECT audio_pending OR EXISTS(SELECT 1 FROM viva_coaching_jobs WHERE session_id=%s AND status IN ('RUNNING','CANCEL_REQUESTED')) OR EXISTS(SELECT 1 FROM viva_session_legacy_cleanup WHERE session_id=%s) FROM viva_session_cleanup WHERE session_id=%s",(session_id,session_id,session_id)).fetchone()
        if pending is None or pending[0]: return False
        conn.execute('DELETE FROM sessions WHERE id=%s',(session_id,))
        return True
