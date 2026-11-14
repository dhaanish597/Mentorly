"""Database repository interfaces and SQLite Phase 0–Phase 7 implementation (`backend/app/db/repository.py`).

Preserves 100% of Phase 0 `SQLiteRepository` methods and migration invariants (`0001_initial.sql`)
while adding Phase 3, Phase 4, and Phase 7 persistence operations:
- `save_challenge`, `get_challenge`, `reveal_challenge`, `list_challenges`
- `record_case_history`, `get_used_case_hashes` (enforcing disjoint diagnostic vs transfer case history)
- `create_turn`, `register_turn_capture_attempt`, `update_turn_state`, `get_turn`, `supersede_active_turns`
- `save_artifact`, `get_artifact`, `list_artifacts` (enforcing server-side redaction into `HiddenEvidenceArtifactView` whenever `Challenge.reveal_state == HIDDEN`)
- `save_trace_report`, `get_trace_report` (blocking unrevealed trace leakage)
- `save_coaching_message`, `list_coaching_messages`
- `record_session_event`, `list_session_events`
- `export_session_bundle`, `purge_expired_sessions`
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal, Protocol
import uuid

from .migrations import apply_migrations, open_connection, utc_now_iso


class RepositoryError(Exception):
    """Base exception for persistence errors."""


class SessionNotFoundError(RepositoryError):
    """Raised when a target session does not exist."""


class SessionDeletedError(RepositoryError):
    """Raised when attempting to mutate or use a tombstoned session."""


class RevisionConflictError(RepositoryError):
    """Raised when a CAS or spec check fails against the persisted revision."""

    def __init__(self, message: str, *, expected: object = None, actual: object = None) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class IdempotencyConflictError(RepositoryError):
    """Raised when an idempotency key is reused with a different request digest."""


class ChallengeNotRevealedError(RepositoryError):
    """Raised when attempting to read trace or oracle details before challenge confirmation."""


@dataclass(frozen=True)
class SessionRecord:
    id: str
    token_hash: str
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
    deleted_at: str | None
    latest_client_edit_sequence: int = 0
    voice: str | None = None
    spoken_language: str | None = None


@dataclass(frozen=True)
class CodeVersionRecord:
    id: str
    session_id: str
    code_version_id: int
    source_code: str
    code_hash: str
    ast_symbols_json: str
    created_at: str


@dataclass(frozen=True)
class CodeSaveResult:
    session: SessionRecord
    code_version: CodeVersionRecord
    changed: bool


@dataclass(frozen=True)
class IdempotencyRecord:
    id: str
    session_id: str
    method: str
    route: str
    idempotency_key: str
    request_digest: str
    status: str
    response_json: str | None
    expires_at: str
    created_at: str


@dataclass(frozen=True)
class IdempotencyCheckResult:
    outcome: Literal["HIT", "MISS", "EXPIRED"]
    record: IdempotencyRecord | None


@dataclass(frozen=True)
class TurnRecord:
    id: str
    session_id: str
    turn_generation: int
    code_version_id: int
    challenge_id: str | None
    state: str
    transport_mode: str
    latest_capture_attempt_id: int
    raw_transcript: str | None
    normalized_transcript: str | None
    claim_json: str | None
    confirmed_at: str | None
    created_at: str
    updated_at: str


class SessionRepository(Protocol):
    """Persistence boundary for sessions, CAS code saves, spec acks, turns, challenges, and artifacts."""

    def initialize(self) -> list[str]: ...

    def create_session(
        self,
        *,
        session_id: str,
        token_hash: str,
        exercise_id: str,
        spec_version: str,
        language_mode: str,
        interaction_mode: str,
        starter_code: str,
        starter_code_hash: str,
        expires_at: str,
        ast_symbols_json: str = "[]",
        spec_acknowledged: bool = True,
        state: str = "READY",
        learning_state: str = "EXPLAINING",
    ) -> SessionRecord: ...

    def get_session(
        self, session_id: str, *, include_deleted: bool = False
    ) -> SessionRecord | None: ...

    def get_session_by_token_hash(self, token_hash: str) -> SessionRecord | None: ...

    def tombstone_session(
        self, session_id: str, *, deleted_at: str | None = None
    ) -> SessionRecord: ...

    def save_code_version(
        self,
        session_id: str,
        *,
        expected_code_version_id: int,
        source_code: str,
        code_hash: str,
        ast_symbols_json: str = "[]",
        client_edit_sequence: int | None = None,
    ) -> CodeSaveResult: ...

    def get_code_version(
        self, session_id: str, code_version_id: int
    ) -> CodeVersionRecord | None: ...

    def update_spec(
        self,
        session_id: str,
        *,
        spec_version: str,
        expected_code_version_id: int,
        spec_acknowledged: bool = False,
        expected_revision=None,
    ) -> SessionRecord: ...

    def acknowledge_spec(
        self, session_id: str, *, spec_version: str
    ) -> SessionRecord: ...

    def check_idempotency(
        self,
        session_id: str,
        *,
        method: str,
        route: str,
        idempotency_key: str,
        request_digest: str,
        now: str | None = None,
    ) -> IdempotencyCheckResult: ...

    def save_idempotency(
        self,
        session_id: str,
        *,
        method: str,
        route: str,
        idempotency_key: str,
        request_digest: str,
        status: str,
        response_json: str | None,
        expires_at: str,
    ) -> IdempotencyRecord: ...


def _row_to_session(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        token_hash=row["token_hash"],
        exercise_id=row["exercise_id"],
        spec_version=row["spec_version"],
        spec_acknowledged=bool(row["spec_acknowledged"]),
        language_mode=row["language_mode"],
        interaction_mode=row["interaction_mode"],
        active_code_version_id=row["active_code_version_id"],
        active_turn_generation=row["active_turn_generation"],
        state=row["state"],
        learning_state=row["learning_state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
        deleted_at=row["deleted_at"],
        latest_client_edit_sequence=int(row["latest_client_edit_sequence"]),
        voice=row['voice'] if 'voice' in row.keys() else None,
        spoken_language=row['spoken_language'] if 'spoken_language' in row.keys() else None,
    )


def _row_to_code_version(row: sqlite3.Row) -> CodeVersionRecord:
    return CodeVersionRecord(
        id=row["id"],
        session_id=row["session_id"],
        code_version_id=row["code_version_id"],
        source_code=row["source_code"],
        code_hash=row["code_hash"],
        ast_symbols_json=row["ast_symbols_json"],
        created_at=row["created_at"],
    )


def _row_to_idempotency(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        id=row["id"],
        session_id=row["session_id"],
        method=row["method"],
        route=row["route"],
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        status=row["status"],
        response_json=row["response_json"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )


def _row_to_turn(row: sqlite3.Row) -> TurnRecord:
    keys = row.keys()
    return TurnRecord(
        id=row["id"],
        session_id=row["session_id"],
        turn_generation=int(row["turn_generation"]),
        code_version_id=int(row["code_version_id"]),
        challenge_id=row["challenge_id"],
        state=row["state"],
        transport_mode=row["transport_mode"],
        latest_capture_attempt_id=int(row["latest_capture_attempt_id"]) if "latest_capture_attempt_id" in keys else 1,
        raw_transcript=row["raw_transcript"],
        normalized_transcript=row["normalized_transcript"],
        claim_json=row["claim_json"],
        confirmed_at=row["confirmed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SQLiteRepository:
    """Transactional SQLite repository implementing Phase 0 through Phase 7 contracts."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self) -> list[str]:
        return apply_migrations(self._db_path)

    def _connect(self) -> sqlite3.Connection:
        return open_connection(self._db_path)

    def _require_active_session_row(
        self, conn: sqlite3.Connection, session_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        if row["deleted_at"] is not None:
            raise SessionDeletedError(f"Session is tombstoned: {session_id}")
        return row

    def create_session(
        self,
        *,
        session_id: str,
        token_hash: str,
        exercise_id: str,
        spec_version: str,
        language_mode: str,
        interaction_mode: str,
        starter_code: str,
        starter_code_hash: str,
        expires_at: str,
        ast_symbols_json: str = "[]",
        spec_acknowledged: bool = True,
        state: str = "READY",
        learning_state: str = "EXPLAINING",
    ) -> SessionRecord:
        now = utc_now_iso()
        cv_id = str(uuid.uuid4())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO sessions (
                        id, token_hash, exercise_id, spec_version, spec_acknowledged,
                        language_mode, interaction_mode, active_code_version_id,
                        active_turn_generation, state, learning_state,
                        created_at, updated_at, expires_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL);
                    """,
                    (
                        session_id,
                        token_hash,
                        exercise_id,
                        spec_version,
                        1 if spec_acknowledged else 0,
                        language_mode,
                        interaction_mode,
                        1,
                        0,
                        state,
                        learning_state,
                        now,
                        now,
                        expires_at,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO code_versions (
                        id, session_id, code_version_id, source_code,
                        code_hash, ast_symbols_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        cv_id,
                        session_id,
                        1,
                        starter_code,
                        starter_code_hash,
                        ast_symbols_json,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                conn.execute("COMMIT;")
                assert row is not None
                return _row_to_session(row)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def get_session(
        self, session_id: str, *, include_deleted: bool = False
    ) -> SessionRecord | None:
        conn = self._connect()
        try:
            if include_deleted:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ? AND deleted_at IS NULL",
                    (session_id,),
                ).fetchone()
            return _row_to_session(row) if row is not None else None
        finally:
            conn.close()

    def get_session_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token_hash = ? AND deleted_at IS NULL",
                (token_hash,),
            ).fetchone()
            return _row_to_session(row) if row is not None else None
        finally:
            conn.close()

    def update_session_states(
        self,
        session_id: str,
        *,
        state: str | None = None,
        learning_state: str | None = None,
        active_turn_generation: int | None = None,
        expected_revision=None,
    ) -> SessionRecord:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                session_row = self._require_active_session_row(conn, session_id)
                if expected_revision is not None:
                    self._assert_revision_row(conn,session_id,expected_revision)
                    turn = conn.execute("SELECT state FROM turns WHERE session_id=? AND turn_generation=? ORDER BY created_at DESC LIMIT 1",(session_id,expected_revision.turn_generation)).fetchone()
                    if turn is not None and turn['state'] in ('CANCELLED','SUPERSEDED'):
                        raise RevisionConflictError("Logical turn was cancelled or superseded")
                next_state = state if state is not None else session_row["state"]
                next_learning = (
                    learning_state
                    if learning_state is not None
                    else session_row["learning_state"]
                )
                next_gen = (
                    active_turn_generation
                    if active_turn_generation is not None
                    else session_row["active_turn_generation"]
                )
                conn.execute(
                    """
                    UPDATE sessions
                    SET state = ?, learning_state = ?, active_turn_generation = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (next_state, next_learning, next_gen, now, session_id),
                )
                updated = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                conn.execute("COMMIT;")
                assert updated is not None
                return _row_to_session(updated)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def tombstone_session(
        self, session_id: str, *, deleted_at: str | None = None
    ) -> SessionRecord:
        ts = deleted_at or utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
                if row is None:
                    raise SessionNotFoundError(f"Session not found: {session_id}")
                old = conn.execute("SELECT pending_jobs_json FROM cleanup_obligations WHERE session_id=?", (session_id,)).fetchone()
                prior_jobs = json.loads(old[0]) if old else []
                if type(prior_jobs) is not list or any(type(job) is not str for job in prior_jobs):
                    raise ValueError("Cleanup job identities are invalid")
                jobs = conn.execute("SELECT id FROM jobs WHERE session_id=? AND status IN ('RUNNING','QUEUED','CANCEL_REQUESTED')", (session_id,)).fetchall()
                pending_jobs = sorted(set(prior_jobs) | {job[0] for job in jobs})
                conn.execute("INSERT INTO cleanup_obligations(session_id,turn_generation,audio_pending,pending_jobs_json,created_at,updated_at) VALUES (?,?,1,?,?,?) ON CONFLICT(session_id) DO UPDATE SET audio_pending=1,pending_jobs_json=excluded.pending_jobs_json,updated_at=excluded.updated_at", (session_id,row["active_turn_generation"],json.dumps(pending_jobs),ts,ts))
                if row["deleted_at"] is None:
                    conn.execute(
                        """
                        UPDATE sessions
                        SET deleted_at = ?, state = 'DELETED', updated_at = ?
                        WHERE id = ?;
                        """,
                        (ts, ts, session_id),
                    )
                    conn.execute(
                        """
                        UPDATE turns
                        SET state = 'CANCELLED', updated_at = ?
                        WHERE session_id = ? AND state NOT IN ('COACH_PROMPT_DELIVERED', 'SUPERSEDED', 'CANCELLED');
                        """,
                        (ts, session_id),
                    )
                for table in ("legacy_traces", "traces", "coaching_messages", "speech_jobs", "artifacts", "evidence_artifacts", "capture_attempts", "turns", "challenges", "case_history", "jobs", "code_versions", "session_events", "idempotency_records"):
                    conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                conn.execute("COMMIT;")
                assert row is not None
                return _row_to_session(row)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def save_code_version(
        self,
        session_id: str,
        *,
        expected_code_version_id: int,
        source_code: str,
        code_hash: str,
        ast_symbols_json: str = "[]",
        client_edit_sequence: int | None = None,
    ) -> CodeSaveResult:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                session_row = self._require_active_session_row(conn, session_id)
                current_version = session_row["active_code_version_id"]
                if client_edit_sequence is not None:
                    if type(client_edit_sequence) is not int or client_edit_sequence <= session_row["latest_client_edit_sequence"]:
                        raise RevisionConflictError("Client edit sequence is stale")
                    conn.execute("UPDATE sessions SET latest_client_edit_sequence=? WHERE id=?", (client_edit_sequence,session_id))
                if current_version != expected_code_version_id:
                    raise RevisionConflictError(
                        "Code version conflict during compare-and-swap save",
                        expected=expected_code_version_id,
                        actual=current_version,
                    )

                cv_row = conn.execute(
                    """
                    SELECT * FROM code_versions
                    WHERE session_id = ? AND code_version_id = ?;
                    """,
                    (session_id, current_version),
                ).fetchone()
                if (
                    cv_row is not None
                    and cv_row["code_hash"] == code_hash
                    and cv_row["source_code"] == source_code
                ):
                    conn.execute("COMMIT;")
                    return CodeSaveResult(
                        session=_row_to_session(session_row),
                        code_version=_row_to_code_version(cv_row),
                        changed=False,
                    )

                new_version = current_version + 1
                cv_pk = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO code_versions (
                        id, session_id, code_version_id, source_code,
                        code_hash, ast_symbols_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        cv_pk,
                        session_id,
                        new_version,
                        source_code,
                        code_hash,
                        ast_symbols_json,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE sessions
                    SET active_code_version_id = ?, active_turn_generation = active_turn_generation + 1,
                        learning_state = 'EXPLAINING', updated_at = ?
                    WHERE id = ?;
                    """,
                    (new_version, now, session_id),
                )
                # Supersede any in-flight turns from older code versions
                conn.execute(
                    """
                    UPDATE turns
                    SET state = 'SUPERSEDED', updated_at = ?
                    WHERE session_id = ? AND code_version_id < ?
                      AND state NOT IN ('COACH_PROMPT_DELIVERED', 'SUPERSEDED', 'CANCELLED');
                    """,
                    (now, session_id, new_version),
                )
                conn.execute("UPDATE jobs SET status='SUPERSEDED',updated_at=? WHERE session_id=? AND status IN ('RUNNING','QUEUED')", (now, session_id))
                updated_session = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                new_cv = conn.execute(
                    "SELECT * FROM code_versions WHERE id = ?",
                    (cv_pk,),
                ).fetchone()
                conn.execute("COMMIT;")
                assert updated_session is not None and new_cv is not None
                return CodeSaveResult(
                    session=_row_to_session(updated_session),
                    code_version=_row_to_code_version(new_cv),
                    changed=True,
                )
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def get_code_version(
        self, session_id: str, code_version_id: int
    ) -> CodeVersionRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT cv.* FROM code_versions cv
                JOIN sessions s ON s.id = cv.session_id
                WHERE cv.session_id = ? AND cv.code_version_id = ? AND s.deleted_at IS NULL;
                """,
                (session_id, code_version_id),
            ).fetchone()
            return _row_to_code_version(row) if row is not None else None
        finally:
            conn.close()

    def update_spec(
        self,
        session_id: str,
        *,
        spec_version: str,
        expected_code_version_id: int,
        spec_acknowledged: bool = False,
        expected_revision=None,
    ) -> SessionRecord:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                session_row = self._require_active_session_row(conn, session_id)
                if expected_revision is not None:
                    self._assert_revision_row(conn,session_id,expected_revision)
                if session_row["active_code_version_id"] != expected_code_version_id:
                    raise RevisionConflictError(
                        "Code version conflict during spec update",
                        expected=expected_code_version_id,
                        actual=session_row["active_code_version_id"],
                    )
                next_state = "READY" if spec_acknowledged else "SPEC_ACK_REQUIRED"
                conn.execute(
                    """
                    UPDATE sessions
                    SET spec_version = ?, spec_acknowledged = ?, state = ?, updated_at = ?,
                        active_turn_generation = active_turn_generation + 1, learning_state = 'EXPLAINING'
                    WHERE id = ?;
                    """,
                    (spec_version, 1 if spec_acknowledged else 0, next_state, now, session_id),
                )
                conn.execute("UPDATE turns SET state='SUPERSEDED',updated_at=? WHERE session_id=? AND state NOT IN ('SUPERSEDED','CANCELLED')", (now,session_id))
                conn.execute("UPDATE jobs SET status='SUPERSEDED',updated_at=? WHERE session_id=? AND status IN ('RUNNING','QUEUED')", (now,session_id))
                updated = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                conn.execute("COMMIT;")
                assert updated is not None
                return _row_to_session(updated)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def acknowledge_spec(
        self, session_id: str, *, spec_version: str
    ) -> SessionRecord:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                session_row = self._require_active_session_row(conn, session_id)
                if session_row["spec_version"] != spec_version:
                    raise RevisionConflictError(
                        "Specification version mismatch during acknowledgement",
                        expected=spec_version,
                        actual=session_row["spec_version"],
                    )
                conn.execute(
                    """
                    UPDATE sessions
                    SET spec_acknowledged = 1, state = 'READY', updated_at = ?
                    WHERE id = ?;
                    """,
                    (now, session_id),
                )
                updated = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                conn.execute("COMMIT;")
                assert updated is not None
                return _row_to_session(updated)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def check_idempotency(
        self,
        session_id: str,
        *,
        method: str,
        route: str,
        idempotency_key: str,
        request_digest: str,
        now: str | None = None,
    ) -> IdempotencyCheckResult:
        current_ts = now or utc_now_iso()
        current_dt = datetime.fromisoformat(current_ts)
        conn = self._connect()
        try:
            self._require_active_session_row(conn, session_id)
            row = conn.execute(
                """
                SELECT * FROM idempotency_records
                WHERE session_id = ? AND method = ? AND route = ? AND idempotency_key = ?;
                """,
                (session_id, method, route, idempotency_key),
            ).fetchone()
            if row is None:
                return IdempotencyCheckResult(outcome="MISS", record=None)
            record = _row_to_idempotency(row)
            expires_dt = datetime.fromisoformat(record.expires_at)
            if expires_dt <= current_dt:
                return IdempotencyCheckResult(outcome="EXPIRED", record=record)
            if record.request_digest != request_digest:
                raise IdempotencyConflictError(
                    "Idempotency key reused with a different request digest"
                )
            return IdempotencyCheckResult(outcome="HIT", record=record)
        finally:
            conn.close()

    def save_idempotency(
        self,
        session_id: str,
        *,
        method: str,
        route: str,
        idempotency_key: str,
        request_digest: str,
        status: str,
        response_json: str | None,
        expires_at: str,
    ) -> IdempotencyRecord:
        now = utc_now_iso()
        now_dt = datetime.fromisoformat(now)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                existing = conn.execute(
                    """
                    SELECT * FROM idempotency_records
                    WHERE session_id = ? AND method = ? AND route = ? AND idempotency_key = ?;
                    """,
                    (session_id, method, route, idempotency_key),
                ).fetchone()
                if existing is not None:
                    existing_expires = datetime.fromisoformat(existing["expires_at"])
                    if existing_expires > now_dt:
                        if existing["request_digest"] != request_digest:
                            raise IdempotencyConflictError(
                                "Idempotency key reused with a different request digest"
                            )
                        conn.execute(
                            """
                            UPDATE idempotency_records
                            SET status = ?, response_json = ?, expires_at = ?
                            WHERE id = ?;
                            """,
                            (status, response_json, expires_at, existing["id"]),
                        )
                        row = conn.execute(
                            "SELECT * FROM idempotency_records WHERE id = ?",
                            (existing["id"],),
                        ).fetchone()
                    else:
                        conn.execute(
                            """
                            UPDATE idempotency_records
                            SET request_digest = ?, status = ?, response_json = ?,
                                expires_at = ?, created_at = ?
                            WHERE id = ?;
                            """,
                            (
                                request_digest,
                                status,
                                response_json,
                                expires_at,
                                now,
                                existing["id"],
                            ),
                        )
                        row = conn.execute(
                            "SELECT * FROM idempotency_records WHERE id = ?",
                            (existing["id"],),
                        ).fetchone()
                else:
                    record_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO idempotency_records (
                            id, session_id, method, route, idempotency_key,
                            request_digest, status, response_json, expires_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            record_id,
                            session_id,
                            method,
                            route,
                            idempotency_key,
                            request_digest,
                            status,
                            response_json,
                            expires_at,
                            now,
                        ),
                    )
                    row = conn.execute(
                        "SELECT * FROM idempotency_records WHERE id = ?",
                        (record_id,),
                    ).fetchone()
                conn.execute("COMMIT;")
                assert row is not None
                return _row_to_idempotency(row)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Phase 3, Phase 4 & Phase 7 Extended Persistence Operations
    # ------------------------------------------------------------------

    def save_challenge(
        self,
        *,
        challenge_id: str,
        session_id: str,
        exercise_id: str,
        spec_version: str,
        code_version_id: int,
        code_hash: str,
        turn_generation: int,
        input_args: dict[str, Any],
        case_hash: str,
        purpose: str,
        reveal_state: str = "HIDDEN",
        created_at: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now_iso()
        exp = expires_at or now
        input_json = json.dumps(input_args, sort_keys=True, separators=(",", ":"))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                conn.execute(
                    """
                    INSERT INTO challenges (
                        id, session_id, exercise_id, spec_version, code_version_id,
                        code_hash, turn_generation, input_args_json, case_hash,
                        purpose, reveal_state, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        challenge_id,
                        session_id,
                        exercise_id,
                        spec_version,
                        code_version_id,
                        code_hash,
                        turn_generation,
                        input_json,
                        case_hash,
                        purpose,
                        reveal_state,
                        now,
                        exp,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO case_history (
                        id, session_id, exercise_id, spec_version, case_hash,
                        purpose, challenge_id, created_at, input_args_json, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        session_id,
                        exercise_id,
                        spec_version,
                        case_hash,
                        purpose,
                        challenge_id,
                        now,
                        input_json,
                        now,
                    ),
                )
                conn.execute("COMMIT;")
                return {
                    "challenge_id": challenge_id,
                    "session_id": session_id,
                    "exercise_id": exercise_id,
                    "spec_version": spec_version,
                    "code_version_id": code_version_id,
                    "code_hash": code_hash,
                    "turn_generation": turn_generation,
                    "input_args": json.loads(input_json),
                    "case_hash": case_hash,
                    "purpose": purpose,
                    "reveal_state": reveal_state,
                    "created_at": now,
                    "expires_at": exp,
                }
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def get_challenge(self, session_id: str, challenge_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            self._require_active_session_row(conn, session_id)
            row = conn.execute(
                "SELECT * FROM challenges WHERE id = ? AND session_id = ?;",
                (challenge_id, session_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "challenge_id": row["id"],
                "session_id": row["session_id"],
                "exercise_id": row["exercise_id"],
                "spec_version": row["spec_version"],
                "code_version_id": int(row["code_version_id"]),
                "code_hash": row["code_hash"],
                "turn_generation": int(row["turn_generation"]),
                "input_args": json.loads(row["input_args_json"]),
                "case_hash": row["case_hash"],
                "purpose": row["purpose"],
                "reveal_state": row["reveal_state"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
            }
        finally:
            conn.close()

    def reveal_challenge(self, session_id: str, challenge_id: str, *, expected_revision=None) -> dict[str, Any]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_active_session_row(conn,session_id)
            if expected_revision is not None:
                self._assert_revision_row(conn,session_id,expected_revision)
            row = conn.execute("SELECT * FROM challenges WHERE id=? AND session_id=?",(challenge_id,session_id)).fetchone()
            if row is None: raise RepositoryError("Challenge not found")
            if row["reveal_state"] != "HIDDEN": raise RevisionConflictError("Challenge was already confirmed")
            if expected_revision is not None and (row["exercise_id"] != expected_revision.exercise_id.value
                    or row["spec_version"] != expected_revision.spec_version.value
                    or row["code_version_id"] != expected_revision.code_version_id
                    or row["code_hash"] != expected_revision.code_hash
                    or row["turn_generation"] != expected_revision.turn_generation):
                raise RevisionConflictError("Challenge revision differs from confirmation")
            if datetime.fromisoformat(row["expires_at"]) <= datetime.fromisoformat(utc_now_iso()):
                raise RevisionConflictError("Challenge expired")
            changed=conn.execute("UPDATE challenges SET reveal_state='REVEALED' WHERE id=? AND session_id=? AND reveal_state='HIDDEN'",(challenge_id,session_id)).rowcount
            if changed != 1: raise RevisionConflictError("Challenge confirmation raced another request")
            conn.execute("COMMIT")
            result=dict(row);result['challenge_id']=result.pop('id');result['input_args']=json.loads(result.pop('input_args_json'));result['reveal_state']='REVEALED'
            return result
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally: conn.close()

    def get_used_case_hashes(
        self, session_id: str, exercise_id: str, spec_version: str
    ) -> set[str]:
        conn = self._connect()
        try:
            self._require_active_session_row(conn, session_id)
            rows = conn.execute(
                """
                SELECT case_hash FROM case_history
                WHERE session_id = ? AND exercise_id = ? AND spec_version = ?;
                """,
                (session_id, exercise_id, spec_version),
            ).fetchall()
            return {str(r["case_hash"]) for r in rows}
        finally:
            conn.close()

    def record_case_history(
        self,
        session_id: str,
        exercise_id: str,
        spec_version: str,
        case_hash: str,
        purpose: str,
        challenge_id: str | None = None,
    ) -> None:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO case_history (
                        id, session_id, exercise_id, spec_version, case_hash,
                        purpose, challenge_id, created_at, input_args_json, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        session_id,
                        exercise_id,
                        spec_version,
                        case_hash,
                        purpose,
                        challenge_id,
                        now,
                        "{}",
                        now,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def latest_client_edit_sequence(self, session_id: str) -> int:
        session = self.get_session(session_id)
        if session is None:
            raise SessionNotFoundError("Session not found")
        return session.latest_client_edit_sequence

    def _assert_revision_row(self, conn, session_id: str, expected):
        row = self._require_active_session_row(conn, session_id)
        cv = conn.execute("SELECT code_hash FROM code_versions WHERE session_id=? AND code_version_id=?",
                          (session_id,row["active_code_version_id"])).fetchone()
        if (str(expected.session_id) != session_id or row["exercise_id"] != expected.exercise_id.value
                or row["spec_version"] != expected.spec_version.value
                or row["active_code_version_id"] != expected.code_version_id
                or row["active_turn_generation"] != expected.turn_generation
                or cv is None or cv["code_hash"] != expected.code_hash):
            raise RevisionConflictError("Full revision no longer matches the active session")
        return row

    def publish_challenge(self, session_id: str, *, expected_revision, challenge_id: str,
                          input_args: dict, purpose: str, created_at: str, expires_at: str) -> dict:
        """Atomically allocate the logical turn and publish its immutable challenge."""
        from backend.app.exercises import registry
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._assert_revision_row(conn, session_id, expected_revision)
            if not row["spec_acknowledged"]:
                raise RevisionConflictError("Domain acknowledgement is required")
            ex_id,spec = row["exercise_id"],row["spec_version"]
            canonical = registry.validate_input(ex_id,spec,input_args)
            case_hash = registry.case_key(ex_id,spec,canonical)
            holdouts = {registry.case_key(ex_id,spec,c) for c in registry.cases(ex_id,spec,"holdout")}
            if purpose == "TRANSFER":
                used = conn.execute("SELECT 1 FROM case_history WHERE session_id=? AND exercise_id=? AND spec_version=? AND case_hash=?",
                                    (session_id,ex_id,spec,case_hash)).fetchone()
                if case_hash not in holdouts or used is not None:
                    raise RevisionConflictError("Transfer input is not fresh and reserved")
            elif case_hash in holdouts:
                raise RevisionConflictError("Diagnostic input cannot consume a transfer holdout")
            generation = row["active_turn_generation"] + 1
            revision = expected_revision.model_copy(update={"turn_generation":generation})
            conn.execute("UPDATE turns SET state='SUPERSEDED',updated_at=? WHERE session_id=? AND state NOT IN ('CANCELLED','SUPERSEDED','COACH_PROMPT_DELIVERED')",(created_at,session_id))
            learning = "FRESH_CASE_CHECK" if purpose == "TRANSFER" else "AWAITING_PREDICTION"
            conn.execute("UPDATE sessions SET active_turn_generation=?,learning_state=?,updated_at=? WHERE id=?",(generation,learning,created_at,session_id))
            conn.execute("INSERT INTO challenges (id,session_id,exercise_id,spec_version,code_version_id,code_hash,turn_generation,input_args_json,case_hash,purpose,reveal_state,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,'HIDDEN',?,?)",
                (challenge_id,session_id,ex_id,spec,revision.code_version_id,revision.code_hash,generation,json.dumps(canonical),case_hash,purpose,created_at,expires_at))
            conn.execute("INSERT INTO turns (id,session_id,turn_generation,code_version_id,challenge_id,state,transport_mode,language_mode,created_at,updated_at,latest_capture_attempt_id) VALUES (?,?,?,?,?,'CREATED','TEXT',?,?,?,0)",
                (str(uuid.uuid4()),session_id,generation,revision.code_version_id,challenge_id,row["language_mode"],created_at,created_at))
            conn.execute("INSERT OR IGNORE INTO case_history (id,session_id,exercise_id,spec_version,case_hash,purpose,challenge_id,created_at,input_args_json,first_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()),session_id,ex_id,spec,case_hash,purpose,challenge_id,created_at,json.dumps(canonical),created_at))
            conn.execute("COMMIT")
            return {"challenge_id":challenge_id,"revision":revision.model_dump(mode="json"),"input_args":canonical,
                    "case_hash":case_hash,"purpose":purpose,"reveal_state":"HIDDEN","created_at":created_at,"expires_at":expires_at}
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally: conn.close()

    def register_execution_job(self, session_id: str, job_id: str, job_type: str, revision, challenge_id: str) -> None:
        conn = self._connect()
        now = utc_now_iso()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_revision_row(conn,session_id,revision)
            turn = conn.execute("SELECT state FROM turns WHERE session_id=? AND turn_generation=?" + (' AND challenge_id=?' if challenge_id else ''),(session_id,revision.turn_generation,challenge_id) if challenge_id else (session_id,revision.turn_generation)).fetchone()
            if turn is not None and turn['state'] in ('CANCELLED','SUPERSEDED'):
                raise RevisionConflictError("Turn was cancelled before job submission")
            conn.execute("INSERT INTO jobs (id,session_id,job_type,status,turn_generation,code_version_id,created_at,updated_at,revision_json,challenge_id) VALUES (?,?,?,'RUNNING',?,?,?,?,?,?)",
                (job_id,session_id,job_type,revision.turn_generation,revision.code_version_id,now,now,revision.model_dump_json(),challenge_id))
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally: conn.close()

    def finish_execution_job(self, session_id: str, job_id: str, status: str) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_active_session_row(conn,session_id)
            changed = conn.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=? AND session_id=? AND status='RUNNING'",
                (status,utc_now_iso(),job_id,session_id)).rowcount
            if not changed:
                raise RevisionConflictError("Execution job was cancelled or superseded")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally: conn.close()

    def acknowledge_execution_cancellation(self, session_id: str, job_id: str) -> None:
        conn = self._connect()
        try:
            # UPDATE only: deleted session work can never recreate a row.
            conn.execute("UPDATE jobs SET status='CANCELLED',updated_at=? WHERE id=? AND session_id=? AND status='CANCEL_REQUESTED'",(utc_now_iso(),job_id,session_id))
        finally: conn.close()

    def request_execution_cancellation(self, session_id: str, job_id: str | None = None) -> list[str]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_active_session_row(conn,session_id)
            rows = conn.execute("SELECT id FROM jobs WHERE session_id=? AND status IN ('RUNNING','QUEUED','CANCEL_REQUESTED')" + (" AND id=?" if job_id else ""),
                (session_id,job_id) if job_id else (session_id,)).fetchall()
            ids = [r['id'] for r in rows]
            now = utc_now_iso()
            for jid in ids:
                conn.execute("UPDATE jobs SET status='CANCEL_REQUESTED',cancelled_at=?,updated_at=? WHERE id=?",(now,now,jid))
            conn.execute("UPDATE turns SET state='CANCELLED',updated_at=? WHERE session_id=? AND state NOT IN ('SUPERSEDED','CANCELLED','COACH_PROMPT_DELIVERED')",(now,session_id))
            conn.execute("COMMIT")
            return ids
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally: conn.close()

    def create_or_reuse_turn(
        self,
        *,
        session_id: str,
        code_version_id: int,
        challenge_id: str | None,
        transport_mode: str = "VOICE",
        state: str = "TRANSCRIBING_AND_PARSING",
        raw_transcript: str | None = None,
        normalized_transcript: str | None = None,
        claim_json: str | None = None,
        reuse_current_generation_on_rerecord: bool = True,
    ) -> tuple[TurnRecord, int]:
        """Create a new logical turn OR reuse the active logical turn on re-record (incrementing `capture_attempt_id`)."""
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                s_row = self._require_active_session_row(conn, session_id)
                active_gen = int(s_row["active_turn_generation"])
                if code_version_id != s_row['active_code_version_id']:
                    raise RevisionConflictError('Capture code revision was superseded')
                if challenge_id is not None:
                    bound = conn.execute('SELECT * FROM challenges WHERE id=? AND session_id=?', (challenge_id,session_id)).fetchone()
                    if bound is None or bound['turn_generation'] != active_gen or bound['code_version_id'] != code_version_id or bound['spec_version'] != s_row['spec_version'] or bound['reveal_state'] != 'HIDDEN':
                        raise RevisionConflictError('Capture requires the current hidden challenge')
                    current_turn = conn.execute('SELECT state FROM turns WHERE session_id=? AND challenge_id=? AND turn_generation=?',(session_id,challenge_id,active_gen)).fetchone()
                    if current_turn and current_turn['state'] in ('CANCELLED','SUPERSEDED','VERIFYING_AND_COACHING','COACH_PROMPT_DELIVERED'):
                        raise RevisionConflictError('This logical turn is no longer accepting captures')

                existing_turn = None
                if reuse_current_generation_on_rerecord and active_gen > 0 and challenge_id is not None:
                    existing_turn = conn.execute(
                        """
                        SELECT * FROM turns
                        WHERE session_id = ? AND turn_generation = ? AND challenge_id = ?
                          AND state IN ('CREATED', 'RECORDING_AUDIO', 'TRANSCRIBING_AND_PARSING', 'AWAITING_CLAIM_CONFIRMATION', 'CLAIM_FALLBACK_EDIT');
                        """,
                        (session_id, active_gen, challenge_id),
                    ).fetchone()

                if existing_turn is not None:
                    turn_id = str(existing_turn["id"])
                    cap_rows = conn.execute(
                        "SELECT COALESCE(MAX(attempt_number), 0) FROM capture_attempts WHERE turn_id = ?;",
                        (turn_id,),
                    ).fetchone()
                    next_attempt = int(cap_rows[0] if cap_rows else 0) + 1
                    conn.execute(
                        """
                        UPDATE capture_attempts
                        SET status = 'SUPERSEDED'
                        WHERE turn_id = ? AND attempt_number < ?;
                        """,
                        (turn_id, next_attempt),
                    )
                    conn.execute(
                        """
                        INSERT INTO capture_attempts (
                            id, turn_id, session_id, attempt_number, status,
                            raw_transcript, normalized_transcript, created_at
                        ) VALUES (?, ?, ?, ?, 'COMPLETE', ?, ?, ?);
                        """,
                        (
                            str(uuid.uuid4()),
                            turn_id,
                            session_id,
                            next_attempt,
                            raw_transcript,
                            normalized_transcript,
                            now,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE turns
                        SET state = ?, transport_mode = ?, raw_transcript = ?,
                            normalized_transcript = ?, claim_json = ?, confirmed_at = NULL, updated_at = ?, latest_capture_attempt_id = ?
                        WHERE id = ?;
                        """,
                        (
                            state,
                            transport_mode,
                            raw_transcript,
                            normalized_transcript,
                            claim_json,
                            now,
                            next_attempt,
                            turn_id,
                        ),
                    )
                    t_row = conn.execute("SELECT * FROM turns WHERE id = ?;", (turn_id,)).fetchone()
                    conn.execute("COMMIT;")
                    assert t_row is not None
                    rec = _row_to_turn(t_row)
                    return (
                        TurnRecord(
                            id=rec.id,
                            session_id=rec.session_id,
                            turn_generation=rec.turn_generation,
                            code_version_id=rec.code_version_id,
                            challenge_id=rec.challenge_id,
                            state=rec.state,
                            transport_mode=rec.transport_mode,
                            latest_capture_attempt_id=next_attempt,
                            raw_transcript=rec.raw_transcript,
                            normalized_transcript=rec.normalized_transcript,
                            claim_json=rec.claim_json,
                            confirmed_at=rec.confirmed_at,
                            created_at=rec.created_at,
                            updated_at=rec.updated_at,
                        ),
                        next_attempt,
                    )

                new_gen = active_gen + 1
                conn.execute(
                    """
                    UPDATE turns
                    SET state = 'SUPERSEDED', updated_at = ?
                    WHERE session_id = ? AND state NOT IN ('COACH_PROMPT_DELIVERED', 'SUPERSEDED', 'CANCELLED');
                    """,
                    (now, session_id),
                )
                conn.execute(
                    """
                    UPDATE sessions
                    SET active_turn_generation = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (new_gen, now, session_id),
                )
                turn_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO turns (
                        id, session_id, turn_generation, code_version_id, challenge_id,
                        state, transport_mode, raw_transcript, normalized_transcript,
                        claim_json, confirmed_at, created_at, updated_at, language_mode, latest_capture_attempt_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 1);
                    """,
                    (
                        turn_id,
                        session_id,
                        new_gen,
                        code_version_id,
                        challenge_id,
                        state,
                        transport_mode,
                        raw_transcript,
                        normalized_transcript,
                        claim_json,
                        now,
                        now,
                        s_row["language_mode"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO capture_attempts (
                        id, turn_id, session_id, attempt_number, status,
                        raw_transcript, normalized_transcript, created_at
                    ) VALUES (?, ?, ?, 1, 'COMPLETE', ?, ?, ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        turn_id,
                        session_id,
                        raw_transcript,
                        normalized_transcript,
                        now,
                    ),
                )
                t_row = conn.execute("SELECT * FROM turns WHERE id = ?;", (turn_id,)).fetchone()
                conn.execute("COMMIT;")
                assert t_row is not None
                return _row_to_turn(t_row), 1
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def update_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        state: str | None = None,
        claim_json: str | None = None,
        confirmed_at: str | None = None,
        raw_transcript: str | None = None,
        normalized_transcript: str | None = None,
        expected_capture_attempt_id: int | None = None,
    ) -> TurnRecord:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                row = conn.execute(
                    "SELECT * FROM turns WHERE id = ? AND session_id = ?;",
                    (turn_id, session_id),
                ).fetchone()
                if row is None:
                    raise RepositoryError(f"Turn not found: {turn_id}")
                if row['state'] in ('CANCELLED','SUPERSEDED') and state != row['state']:
                    raise RevisionConflictError('Cancelled or superseded turns cannot be revived')
                if expected_capture_attempt_id is not None and row['latest_capture_attempt_id'] != expected_capture_attempt_id:
                    raise RevisionConflictError('Capture attempt was superseded')
                if row['confirmed_at'] and claim_json is not None and claim_json != row['claim_json']:
                    raise RevisionConflictError('Confirmed claim is immutable')
                next_state = state if state is not None else row["state"]
                next_claim = claim_json if claim_json is not None else row["claim_json"]
                next_conf = confirmed_at if confirmed_at is not None else row["confirmed_at"]
                conn.execute(
                    """
                    UPDATE turns
                    SET state = ?, claim_json = ?, confirmed_at = ?, updated_at = ?, raw_transcript=COALESCE(?,raw_transcript), normalized_transcript=COALESCE(?,normalized_transcript)
                    WHERE id = ? AND session_id = ?;
                    """,
                    (next_state, next_claim, next_conf, now, raw_transcript, normalized_transcript, turn_id, session_id),
                )
                updated = conn.execute(
                    "SELECT * FROM turns WHERE id = ? AND session_id = ?;",
                    (turn_id, session_id),
                ).fetchone()
                conn.execute("COMMIT;")
                assert updated is not None
                return _row_to_turn(updated)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def get_turn(self, session_id: str, turn_id: str) -> TurnRecord | None:
        conn = self._connect()
        try:
            self._require_active_session_row(conn, session_id)
            row = conn.execute(
                "SELECT * FROM turns WHERE id = ? AND session_id = ?;",
                (turn_id, session_id),
            ).fetchone()
            return _row_to_turn(row) if row is not None else None
        finally:
            conn.close()

    def save_artifact(
        self,
        *,
        artifact_id: str,
        session_id: str,
        challenge_id: str,
        code_version_id: int,
        turn_generation: int,
        case_hash: str,
        confirmed_prediction: object | None,
        prediction_status: str,
        verification_status: str,
        minimization_status: str,
        artifact_json: str,
        trace_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                from backend.app.models.domain import RevisionRef
                revision = RevisionRef.model_validate(json.loads(artifact_json)["revision"])
                self._assert_revision_row(conn,session_id,revision)
                challenge = conn.execute("SELECT reveal_state FROM challenges WHERE id=? AND session_id=? AND code_version_id=? AND turn_generation=?",(challenge_id,session_id,code_version_id,turn_generation)).fetchone()
                if challenge is None:
                    raise RevisionConflictError("Artifact challenge does not bind its revision")
                turn = conn.execute("SELECT state FROM turns WHERE session_id=? AND challenge_id=? AND turn_generation=?",(session_id,challenge_id,turn_generation)).fetchone()
                if turn is not None and turn['state'] in ('CANCELLED','SUPERSEDED'):
                    raise RevisionConflictError("Artifact turn was cancelled or superseded")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO evidence_artifacts (
                        id, session_id, challenge_id, code_version_id, turn_generation,
                        case_hash, confirmed_prediction, prediction_status,
                        verification_status, minimization_status, trace_id,
                        artifact_json, created_at, confirmed_prediction_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        artifact_id,
                        session_id,
                        challenge_id,
                        code_version_id,
                        turn_generation,
                        case_hash,
                        confirmed_prediction if type(confirmed_prediction) is int else None,
                        prediction_status,
                        verification_status,
                        minimization_status,
                        trace_id,
                        artifact_json,
                        now,
                        json.dumps(confirmed_prediction, allow_nan=False) if confirmed_prediction is not None else None,
                    ),
                )
                conn.execute("COMMIT;")
                return json.loads(artifact_json)
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def get_artifact_view(self, session_id: str, artifact_id: str) -> dict[str, Any] | None:
        """Return full `EvidenceArtifact` ONLY if its bound `Challenge.reveal_state == REVEALED`; otherwise return redacted `HiddenEvidenceArtifactView`."""
        conn = self._connect()
        try:
            self._require_active_session_row(conn, session_id)
            row = conn.execute(
                """
                SELECT ea.artifact_json, c.reveal_state
                FROM evidence_artifacts ea
                JOIN challenges c ON c.id = ea.challenge_id
                WHERE ea.id = ? AND ea.session_id = ?;
                """,
                (artifact_id, session_id),
            ).fetchone()
            if row is None:
                return None
            raw_art = json.loads(row["artifact_json"])
            if str(row["reveal_state"]) != "REVEALED":
                return {
                    "schema_version": raw_art.get("schema_version", "1.0.0"),
                    "artifact_id": raw_art["artifact_id"],
                    "revision": raw_art["revision"],
                    "challenge_id": raw_art["challenge_id"],
                    "canonical_input": raw_art["canonical_input"],
                    "case_hash": raw_art["case_hash"],
                    "reveal_state": "HIDDEN",
                    "confirmed_prediction": raw_art.get("confirmed_prediction"),
                    "prediction_status": "NOT_EVALUATED",
                }
            return self._redact_foreign_counterexample(conn, session_id, raw_art)
        finally:
            conn.close()

    def save_trace_report(
        self,
        *,
        trace_id: str,
        session_id: str,
        code_version_id: int,
        turn_generation: int,
        case_hash: str,
        status: str,
        total_observed: int,
        trace_truncated: bool,
        termination_reason: str,
        runtime_version: str,
        steps_json: str,
        observation_json: str | None = None,
        created_at: str | None = None,
        revision=None,
        challenge_id: str | None = None,
    ) -> None:
        now = created_at or utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                if revision is not None:
                    self._assert_revision_row(conn,session_id,revision)
                binding = conn.execute("SELECT * FROM challenges WHERE session_id=? AND case_hash=? AND code_version_id=? AND turn_generation=?" + (" AND id=?" if challenge_id else "") + " ORDER BY created_at DESC LIMIT 1",
                    (session_id,case_hash,code_version_id,turn_generation,challenge_id) if challenge_id else (session_id,case_hash,code_version_id,turn_generation)).fetchone()
                if binding is None:
                    raise RevisionConflictError("Trace has no exactly bound challenge")
                bound_revision = {"session_id":session_id,"exercise_id":binding["exercise_id"],"spec_version":binding["spec_version"],"code_version_id":code_version_id,"code_hash":binding["code_hash"],"turn_generation":turn_generation}
                if revision is not None and bound_revision != revision.model_dump(mode="json"):
                    raise RevisionConflictError("Trace revision does not match challenge")
                challenge_id = binding["id"]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO traces (
                        id, session_id, code_version_id, turn_generation, case_hash,
                        status, total_observed, trace_truncated, termination_reason,
                        runtime_version, steps_json, observation_json, created_at, revision_json, challenge_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        trace_id,
                        session_id,
                        code_version_id,
                        turn_generation,
                        case_hash,
                        status,
                        total_observed,
                        1 if trace_truncated else 0,
                        termination_reason,
                        runtime_version,
                        steps_json,
                        observation_json,
                        now,
                        json.dumps(bound_revision),
                        challenge_id,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def get_trace_report(self, session_id: str, trace_id: str) -> dict[str, Any] | None:
        """Return trace report ONLY if associated challenge is REVEALED."""
        conn = self._connect()
        try:
            self._require_active_session_row(conn, session_id)
            row = conn.execute(
                "SELECT * FROM traces WHERE id = ? AND session_id = ?;",
                (trace_id, session_id),
            ).fetchone()
            if row is None:
                return None
            binding = conn.execute("SELECT * FROM challenges WHERE id=? AND session_id=?",(row["challenge_id"],session_id)).fetchone() if row["challenge_id"] else conn.execute(
                "SELECT * FROM challenges WHERE session_id=? AND case_hash=? AND code_version_id=? AND turn_generation=? ORDER BY created_at DESC LIMIT 1",
                (session_id,row["case_hash"],row["code_version_id"],row["turn_generation"])).fetchone()
            if binding is None or binding["reveal_state"] != "REVEALED":
                raise ChallengeNotRevealedError("Trace requires its exactly bound revealed challenge")
            original_revision = json.loads(row["revision_json"]) if row["revision_json"] else {
                "session_id":session_id,"exercise_id":binding["exercise_id"],"spec_version":binding["spec_version"],
                "code_version_id":row["code_version_id"],"code_hash":binding["code_hash"],"turn_generation":row["turn_generation"]}
            return {
                "trace_id": row["id"],
                "revision": original_revision,
                "case_hash": row["case_hash"],
                "status": row["status"],
                "steps": json.loads(row["steps_json"]),
                "total_observed": int(row["total_observed"]),
                "trace_truncated": bool(row["trace_truncated"]),
                "termination_reason": row["termination_reason"],
                "observation": json.loads(row["observation_json"]) if row["observation_json"] else None,
                "runtime_version": row["runtime_version"],
            }
        finally:
            conn.close()

    def save_coaching_message(
        self,
        *,
        message_id: str,
        session_id: str,
        turn_id: str,
        artifact_id: str | None,
        hint_level: int | None,
        source_mode: str,
        display_text: str,
        speakable_text: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO coaching_messages (
                        id, session_id, turn_id, artifact_id, hint_level,
                        source_mode, display_text, speakable_text, created_at, text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        message_id,
                        session_id,
                        turn_id,
                        artifact_id,
                        hint_level,
                        source_mode,
                        display_text,
                        speakable_text,
                        now,
                        display_text,
                    ),
                )
                conn.execute("COMMIT;")
                return {
                    "message_id": message_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "artifact_id": artifact_id,
                    "hint_level": hint_level,
                    "source_mode": source_mode,
                    "display_text": display_text,
                    "speakable_text": speakable_text,
                    "created_at": now,
                }
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def record_session_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                self._require_active_session_row(conn, session_id)
                seq_row = conn.execute(
                    "SELECT COALESCE(MAX(sequence_no), 0) FROM session_events WHERE session_id = ?;",
                    (session_id,),
                ).fetchone()
                next_seq = int(seq_row[0] if seq_row else 0) + 1
                conn.execute(
                    """
                    INSERT INTO session_events (
                        id, session_id, sequence_no, event_type, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        str(uuid.uuid4()),
                        session_id,
                        next_seq,
                        event_type,
                        json.dumps(payload, sort_keys=True),
                        now,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        finally:
            conn.close()

    def export_session_bundle(self, session_id: str) -> dict[str, Any]:
        """Export session state while redacting any unrevealed (`HIDDEN`) artifact outputs or traces."""
        now = utc_now_iso()
        conn = self._connect()
        try:
            s_row = self._require_active_session_row(conn, session_id)
            cv_row = conn.execute(
                "SELECT * FROM code_versions WHERE session_id = ? AND code_version_id = ?;",
                (session_id, s_row["active_code_version_id"]),
            ).fetchone()
            code_hash = str(cv_row["code_hash"]) if cv_row else ("0" * 64)
            revision = {
                "session_id": session_id,
                "exercise_id": s_row["exercise_id"],
                "spec_version": s_row["spec_version"],
                "code_version_id": int(s_row["active_code_version_id"]),
                "code_hash": code_hash,
                "turn_generation": int(s_row["active_turn_generation"]),
            }

            c_rows = conn.execute(
                "SELECT * FROM challenges WHERE session_id = ? ORDER BY created_at ASC;",
                (session_id,),
            ).fetchall()
            challenges: list[dict[str, Any]] = []
            reveal_by_cid: dict[str, str] = {}
            for r in c_rows:
                cid = str(r["id"])
                rev_state = str(r["reveal_state"])
                reveal_by_cid[cid] = rev_state
                challenges.append(
                    {
                        "challenge_id": cid,
                        "revision": {
                            "session_id": session_id,
                            "exercise_id": r["exercise_id"],
                            "spec_version": r["spec_version"],
                            "code_version_id": int(r["code_version_id"]),
                            "code_hash": r["code_hash"],
                            "turn_generation": int(r["turn_generation"]),
                        },
                        "input_args": json.loads(r["input_args_json"]),
                        "case_hash": r["case_hash"],
                        "purpose": r["purpose"],
                        "reveal_state": rev_state,
                        "created_at": r["created_at"],
                        "expires_at": r["expires_at"],
                    }
                )

            ea_rows = conn.execute(
                "SELECT * FROM evidence_artifacts WHERE session_id = ? ORDER BY created_at ASC;",
                (session_id,),
            ).fetchall()
            revealed_artifacts: list[dict[str, Any]] = []
            for r in ea_rows:
                cid = str(r["challenge_id"])
                if reveal_by_cid.get(cid) == "REVEALED":
                    revealed_artifacts.append(self._redact_foreign_counterexample(conn, session_id, json.loads(r["artifact_json"])))

            return {
                "export_version": "1.0.0",
                "exported_at": now,
                "session_id": session_id,
                "revision": revision,
                "challenges": challenges,
                "evidence_artifacts": revealed_artifacts,
            }
        finally:
            conn.close()

    def _redact_foreign_counterexample(self, conn: sqlite3.Connection, session_id: str, artifact: dict) -> dict:
        """A prediction for one input never unlocks another verifier input's answer."""
        from backend.app.exercises import registry
        report = artifact.get('verification_report', {})
        case = report.get('counterexample_input')
        if case is None:
            return artifact
        rev = artifact['revision']
        case_hash = registry.case_key(rev['exercise_id'],rev['spec_version'],case)
        if case_hash == artifact.get('case_hash'):
            return artifact
        revealed = conn.execute("SELECT 1 FROM challenges WHERE session_id=? AND exercise_id=? AND spec_version=? AND code_hash=? AND case_hash=? AND reveal_state='REVEALED'", (session_id,rev['exercise_id'],rev['spec_version'],rev['code_hash'],case_hash)).fetchone()
        if revealed:
            return artifact
        return {**artifact, 'verification_report':{**report, 'student_observation':None,
            'reference_output':None, 'terminal_reason':'A different failing input requires its own confirmed prediction.'}}

    def get_prior_failing_input(self, session_id: str, revision: Any, artifact_id: str | None = None) -> dict | None:
        """Use retained server evidence across code saves, never across specification changes."""
        conn = self._connect()
        try:
            self._require_active_session_row(conn,session_id)
            rows = conn.execute('SELECT artifact_json FROM evidence_artifacts WHERE session_id=?' +
                (' AND id=?' if artifact_id else '') + ' ORDER BY created_at DESC, rowid DESC',
                (session_id,artifact_id) if artifact_id else (session_id,)).fetchall()
            if artifact_id and not rows:
                raise RepositoryError('Prior artifact not found in this session')
            for row in rows:
                artifact = json.loads(row['artifact_json'])
                rev = artifact['revision']
                if rev['exercise_id'] != revision.exercise_id.value or rev['spec_version'] != revision.spec_version.value or rev['code_version_id'] > revision.code_version_id:
                    if artifact_id:
                        raise RevisionConflictError('Prior artifact belongs to another specification or future revision')
                    continue
                report = artifact['verification_report']
                if report.get('counterexample_input') is not None:
                    return report['counterexample_input']
                obs = artifact['actual_observation']
                from backend.app.exercises.registry import compare_output
                if obs['kind'] == 'RETURN' and not compare_output(obs.get('return_value'), artifact['reference_output']):
                    return artifact['canonical_input']
            return None
        finally:
            conn.close()

    def get_prior_failing_artifact_id(self, session_id: str, revision: Any) -> str | None:
        conn = self._connect()
        try:
            self._require_active_session_row(conn,session_id)
            rows = conn.execute('SELECT id,artifact_json FROM evidence_artifacts WHERE session_id=? ORDER BY created_at DESC,rowid DESC',(session_id,)).fetchall()
            for row in rows:
                artifact = json.loads(row['artifact_json'])
                rev = artifact['revision']
                if rev['exercise_id'] != revision.exercise_id.value or rev['spec_version'] != revision.spec_version.value or rev['code_version_id'] > revision.code_version_id:
                    continue
                obs = artifact['actual_observation']
                from backend.app.exercises.registry import compare_output
                if artifact['verification_report'].get('counterexample_input') is not None or (obs['kind'] == 'RETURN' and not compare_output(obs['return_value'], artifact['reference_output'])):
                    return row['id']
            return None
        finally:
            conn.close()

    def require_unlocked_hint(self, session_id: str, artifact_id: str, level: int) -> None:
        conn = self._connect()
        try:
            self._require_active_session_row(conn,session_id)
            rows = conn.execute("SELECT payload_json FROM session_events WHERE session_id=? AND event_type='HINT_DELIVERED'",(session_id,)).fetchall()
            highest = max((payload['level'] for row in rows if (payload := json.loads(row[0]))['artifact_id'] == artifact_id),default=1)
            if level < 1 or level > highest:
                raise RevisionConflictError('Request this hint level sequentially before playing it')
        finally:
            conn.close()

    def get_active_turn(self, session_id: str) -> TurnRecord | None:
        conn = self._connect()
        try:
            session = self._require_active_session_row(conn,session_id)
            row = conn.execute("SELECT * FROM turns WHERE session_id=? AND code_version_id=? AND turn_generation=? AND state NOT IN ('CANCELLED','SUPERSEDED') ORDER BY created_at DESC LIMIT 1", (session_id,session['active_code_version_id'],session['active_turn_generation'])).fetchone()
            return _row_to_turn(row) if row else None
        finally:
            conn.close()

    def confirm_turn_claim(self, session_id: str, *, revision: Any, challenge_id: str | None,
                           turn_id: str | None, claim_json: str, capture_attempt_id: int | None,
                           reveal: bool = True) -> TurnRecord:
        """Capture, cancellation, immutable claim, and reveal commit under one CAS lock."""
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._assert_revision_row(conn,session_id,revision)
            row = conn.execute('SELECT * FROM turns WHERE session_id=? AND challenge_id IS ? AND turn_generation=?' + (' AND id=?' if turn_id else ''),
                (session_id,challenge_id,revision.turn_generation,turn_id) if turn_id else (session_id,challenge_id,revision.turn_generation)).fetchone()
            if row is None or row['state'] not in ('CREATED','AWAITING_CLAIM_CONFIRMATION','CLAIM_FALLBACK_EDIT'):
                raise RevisionConflictError('This turn is no longer awaiting confirmation')
            if row['latest_capture_attempt_id'] > 1 and capture_attempt_id is None:
                raise RevisionConflictError('The accepted capture attempt identity is required after re-recording')
            if capture_attempt_id is not None and row['latest_capture_attempt_id'] != capture_attempt_id:
                raise RevisionConflictError('Capture attempt was superseded')
            if turn_id is not None and row['state'] == 'CREATED':
                raise RevisionConflictError('Capture a claim before confirming this turn')
            if reveal:
                changed = conn.execute("UPDATE challenges SET reveal_state='REVEALED' WHERE id=? AND session_id=? AND reveal_state='HIDDEN' AND turn_generation=? AND code_version_id=? AND code_hash=? AND spec_version=? AND expires_at>?", (challenge_id,session_id,revision.turn_generation,revision.code_version_id,revision.code_hash,revision.spec_version.value,utc_now_iso())).rowcount
                if changed != 1:
                    raise RevisionConflictError('Challenge confirmation was cancelled, expired, or superseded')
            now = utc_now_iso()
            conn.execute('UPDATE turns SET state=?,claim_json=?,confirmed_at=?,updated_at=? WHERE id=?',
                ('VERIFYING_AND_COACHING' if reveal else 'CLAIM_FALLBACK_EDIT',claim_json,now if reveal else None,now,row['id']))
            updated = conn.execute('SELECT * FROM turns WHERE id=?',(row['id'],)).fetchone()
            conn.execute('COMMIT')
            return _row_to_turn(updated)
        except Exception:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        finally:
            conn.close()

    def begin_execution_retry(self, session_id: str, turn_id: str, revision: Any) -> TurnRecord:
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._assert_revision_row(conn,session_id,revision)
            turn = conn.execute('SELECT * FROM turns WHERE id=? AND session_id=? AND turn_generation=?',(turn_id,session_id,revision.turn_generation)).fetchone()
            if turn is None or turn['state'] != 'COACH_PROMPT_DELIVERED' or not turn['confirmed_at']:
                raise RevisionConflictError('Retry requires an unavailable completed confirmed turn')
            row = conn.execute('SELECT artifact_json FROM evidence_artifacts WHERE session_id=? AND challenge_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(session_id,turn['challenge_id'])).fetchone()
            artifact = json.loads(row['artifact_json']) if row else None
            if not artifact or artifact['actual_observation']['kind'] != 'UNAVAILABLE' or artifact['prediction_status'] != 'NOT_EVALUATED':
                raise RevisionConflictError('Actually evaluated outcomes cannot be retried')
            report = artifact['verification_report']
            if report['status'] != 'EXECUTION_UNAVAILABLE' or report['curated_cases_run'] or report['generated_cases_run'] or report.get('counterexample_input') or report.get('executed_case_hashes') or (report.get('student_observation') and report['student_observation']['kind'] != 'UNAVAILABLE'):
                raise RevisionConflictError('Actually evaluated verification cannot be retried')
            conn.execute("UPDATE turns SET state='VERIFYING_AND_COACHING',updated_at=? WHERE id=?",(utc_now_iso(),turn_id))
            conn.execute('COMMIT')
            return _row_to_turn(turn)
        except Exception:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        finally:
            conn.close()

    def advance_hint(self, session_id: str, artifact_id: str, revision: Any, level: int) -> None:
        """Persist graduated hint access atomically so parallel requests cannot skip levels."""
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._assert_revision_row(conn,session_id,revision)
            rows = conn.execute("SELECT payload_json FROM session_events WHERE session_id=? AND event_type='HINT_DELIVERED'",(session_id,)).fetchall()
            previous = max((json.loads(r[0])['level'] for r in rows if json.loads(r[0])['artifact_id'] == artifact_id),default=0)
            if level < 1 or level > 3 or level > previous + 1:
                raise RevisionConflictError('Request hints sequentially, starting at level 1')
            seq = conn.execute('SELECT COALESCE(MAX(sequence_no),0)+1 FROM session_events WHERE session_id=?',(session_id,)).fetchone()[0]
            conn.execute('INSERT INTO session_events (id,session_id,sequence_no,event_type,payload_json,created_at) VALUES (?,?,?,?,?,?)',
                (str(uuid.uuid4()),session_id,seq,'HINT_DELIVERED',json.dumps({'artifact_id':artifact_id,'level':level}),utc_now_iso()))
            conn.execute('COMMIT')
        except Exception:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        finally:
            conn.close()
