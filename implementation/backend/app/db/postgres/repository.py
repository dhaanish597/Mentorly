"""Experimental authenticated PostgreSQL reads; not wired to the application.

Only session and code reads are implemented. Each operation authorizes under a
session row lock in the same transaction as the private read. Cooperating writers,
tombstone and retention workers must take the same lock; direct database writers
are outside this boundary. This is not a complete SQLite repository port.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from typing import Any

from ..repository import CodeVersionRecord
from .coaching import _lock_authorized, _require_idle


@dataclass(frozen=True)
class SessionView:
    id: str
    exercise_id: str
    spec_version: str
    spec_acknowledged: bool
    language_mode: str
    interaction_mode: str
    active_code_version_id: int
    active_turn_generation: int
    state: str
    learning_state: str
    created_at: str
    updated_at: str
    expires_at: str
    latest_client_edit_sequence: int
    voice: str | None
    spoken_language: str | None


def _digest(token: str) -> str:
    # Invalid input deliberately cannot authenticate, including against a malformed
    # stored digest. Do not expose bearer tokens to SQL or logs.
    if not isinstance(token, str) or not 1 <= len(token) <= 512:
        return ''
    return hashlib.sha256(token.encode()).hexdigest()


class PostgresRepository:
    """Authenticated reads using fresh psycopg 3 tuple-row connections.

    Expired, deleted, missing and unauthorized sessions raise the same
    AuthorizationError. A read linearizes while holding the session lock; it
    cannot retract data after it has returned. No credential hashes are returned.
    """

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def get_session(self, session_id: str, *, token: str) -> SessionView:
        with self._connect() as conn:
            _require_idle(conn)
            with conn.transaction():
                conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                _lock_authorized(conn, session_id, _digest(token))
                row = conn.execute('''SELECT id, exercise_id, spec_version, spec_acknowledged,
                    language_mode, interaction_mode, active_code_version_id, active_turn_generation,
                    state, learning_state, created_at, updated_at, expires_at,
                    latest_client_edit_sequence, voice, spoken_language
                    FROM sessions WHERE id=%s''', (session_id,)).fetchone()
                if not isinstance(row, tuple) or len(row) != 16:
                    raise RuntimeError('Session row unavailable')
                values = list(row)
                values[3] = bool(values[3])
                return SessionView(*values)

    def get_code_version(self, session_id: str, code_version_id: int, *, token: str) -> CodeVersionRecord | None:
        with self._connect() as conn:
            _require_idle(conn)
            with conn.transaction():
                conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                _lock_authorized(conn, session_id, _digest(token))
                row = conn.execute('''SELECT id, session_id, code_version_id, source_code,
                    code_hash, ast_symbols_json, created_at FROM code_versions
                    WHERE session_id=%s AND code_version_id=%s''', (session_id, code_version_id)).fetchone()
                if row is not None and (not isinstance(row, tuple) or len(row) != 7):
                    raise ValueError('PostgreSQL connection must use tuple rows')
                return CodeVersionRecord(*row) if row is not None else None
