"""Experimental PostgreSQL coaching transactions; not wired to the product.

Each call requires an idle psycopg-style connection with tuple rows. Every writer
and deleter must coordinate via the session row lock; this module does not provide
session deletion, cleanup obligations, request authentication, or a full port.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import re
import uuid


class AuthorizationError(RuntimeError):
    """The session is missing, deleted, or the supplied credential is invalid."""


class RevisionConflictError(RuntimeError):
    """The active session revision or client edit sequence is stale."""


@dataclass(frozen=True)
class Revision:
    session_id: str
    exercise_id: str
    spec_version: str
    code_version_id: int
    code_hash: str
    turn_generation: int


@dataclass(frozen=True)
class CodeSave:
    code_version_id: int
    turn_generation: int
    changed: bool
    latest_client_edit_sequence: int


def _lock_authorized(conn, session_id, token_hash):
    row = conn.execute("""SELECT token_hash, exercise_id, spec_version, active_code_version_id,
        active_turn_generation, latest_client_edit_sequence, deleted_at, expires_at
        FROM sessions WHERE id = %s FOR UPDATE""", (session_id,)).fetchone()
    if row is not None and (not isinstance(row, tuple) or len(row) != 8):
        raise ValueError("PostgreSQL connection must use tuple rows")
    valid_digest = isinstance(token_hash, str) and re.fullmatch(r"[0-9a-f]{64}", token_hash) is not None
    stored = row[0] if row else "0" * 64
    valid_stored = isinstance(stored, str) and re.fullmatch(r"[0-9a-f]{64}", stored) is not None
    authorized = hmac.compare_digest(stored if valid_stored else "0" * 64,
                                     token_hash if valid_digest else "0" * 64)
    try:
        expiry = datetime.fromisoformat(row[7]) if row is not None else None
        unexpired = expiry is not None and expiry.utcoffset() is not None and expiry > datetime.now(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        unexpired = False
    if row is None or row[6] is not None or not valid_digest or not valid_stored or not authorized or not unexpired:
        raise AuthorizationError("Session unavailable")
    return row


def _require_idle(conn):
    if getattr(getattr(conn, "info", None), "transaction_status", None) != 0:
        raise ValueError("An idle PostgreSQL connection is required")


def save_code_version(conn, *, session_id: str, token_hash: str,
                      expected: Revision, source_code: str, code_hash: str,
                      ast_symbols_json: str = "[]", client_edit_sequence: int | None = None) -> CodeSave:
    """Authorize and compare the full active revision, then atomically save code.

    A no-op save still advances a supplied client edit sequence, matching SQLite.
    Failed saves roll back the sequence change. No raw bearer token is accepted.
    """
    _require_idle(conn)
    if client_edit_sequence is not None and type(client_edit_sequence) is not int:
        raise RevisionConflictError("Client edit sequence is stale")
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        row = _lock_authorized(conn, session_id, token_hash)
        now = datetime.now(timezone.utc).isoformat()
        _, exercise, spec, version, generation, last_sequence, _, _ = row
        if client_edit_sequence is not None and client_edit_sequence <= last_sequence:
            raise RevisionConflictError("Client edit sequence is stale")
        current = conn.execute("SELECT source_code, code_hash FROM code_versions WHERE session_id=%s AND code_version_id=%s",
                               (session_id, version)).fetchone()
        if current is not None and (not isinstance(current, tuple) or len(current) != 2):
            raise ValueError("PostgreSQL connection must use tuple rows")
        if (current is None or expected.session_id != session_id or expected.exercise_id != exercise
                or expected.spec_version != spec or expected.code_version_id != version
                or expected.turn_generation != generation or expected.code_hash != current[1]):
            raise RevisionConflictError("Full revision no longer matches the active session")
        sequence = last_sequence if client_edit_sequence is None else client_edit_sequence
        if current == (source_code, code_hash):
            if client_edit_sequence is not None:
                conn.execute("UPDATE sessions SET latest_client_edit_sequence=%s WHERE id=%s", (sequence, session_id))
            return CodeSave(version, generation, False, sequence)
        new_version = version + 1
        conn.execute("""INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,ast_symbols_json,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""", (str(uuid.uuid4()),session_id,new_version,source_code,code_hash,ast_symbols_json,now))
        conn.execute("""UPDATE sessions SET active_code_version_id=%s, active_turn_generation=active_turn_generation+1,
            latest_client_edit_sequence=%s, learning_state='EXPLAINING', updated_at=%s WHERE id=%s""",
            (new_version, sequence, now, session_id))
        conn.execute("""UPDATE turns SET state='SUPERSEDED',updated_at=%s WHERE session_id=%s AND code_version_id < %s
            AND state NOT IN ('COACH_PROMPT_DELIVERED','SUPERSEDED','CANCELLED')""", (now,session_id,new_version))
        conn.execute("UPDATE jobs SET status='SUPERSEDED',updated_at=%s WHERE session_id=%s AND status IN ('RUNNING','QUEUED')", (now,session_id))
        # Job schema is optional. Logical cancellation shares the session lock;
        # external worker termination requires a separate mechanism.
        relation = conn.execute("SELECT to_regclass('viva_coaching_jobs')").fetchone()
        if not isinstance(relation, tuple) or len(relation) != 1:
            raise ValueError("PostgreSQL connection must use tuple rows")
        if relation[0] is not None:
            conn.execute("""UPDATE viva_coaching_jobs SET
                status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE 'CANCEL_REQUESTED' END,
                updated_at=clock_timestamp()
                WHERE session_id=%s AND status IN ('QUEUED','RUNNING')""", (session_id,))
        return CodeSave(new_version, generation + 1, True, sequence)
