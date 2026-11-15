"""Single-Concurrency Speech Gatekeeper & Durable Usage Ledger (`gatekeeper.py`).

Implements Plan §8.6 / Phase 2 Prompt §B.6 & Fix P2-06:
- Enforces `max_concurrency = 1` across all outbound Gnani STT and TTS requests via an
  in-process `asyncio.Semaphore(1)` and bounded FIFO wait queue (`max_waiting = 10`,
  `queue_wait_timeout_sec = 6.0`).
- Phase 0 & Phase 2 SQLite Schema Compatibility:
  - Works seamlessly on both a brand-new `:memory:` / file SQLite DB AND an existing Phase 0
    database initialized by `SQLiteRepository(db_path).initialize()` (`0001_initial.sql`).
  - Inspects existing columns of `usage_reservations` and `usage_ledger`, idempotently adds
    Phase 2 columns (`reservation_id`, `entry_id`, `turn_generation`, `reserved_stt_sec`,
    `reserved_tts_chars`, `cache_hit`, `uncertain`) via `ALTER TABLE`, and inserts a synthetic
    placeholder session row into `sessions` when `PRAGMA foreign_keys = ON` is active and
    `session_id` is not yet present in `sessions`.
- Atomic Budget Admission (`BEGIN IMMEDIATE`):
  - Computes `committed + reserved + uncertain` usage inside a transaction (`SELECT COALESCE(SUM(stt_seconds), 0.0), COALESCE(SUM(tts_chars), 0) FROM usage_reservations WHERE status IN ('RESERVED', 'COMMITTED')`)
    BEFORE inserting a new `'RESERVED'` row so concurrent reservations can never oversubscribe the budget.
- Guaranteed Reservation Release on Queue Overflow / Timeout / Cancellation:
  - Places `await self._acquire_single_slot()` inside the `try:` block covered by
    `finally: self._finalize_reservation(...)` while tracking `slot_acquired = False` so queue
    overflows, queue wait timeouts, or cancellations always transition `'RESERVED'` to `'RELEASED'`.
- Post-Provider Freshness Recheck & Uncertain Usage Tracking:
  - Rechecks freshness both BEFORE and immediately AFTER `await self.adapter.transcribe_rest(...)`
    and `await self.adapter.synthesize_tts(...)`. If superseded while in flight, records the real
    provider work in the ledger (`COMMITTED` or `uncertain=1` if aborted mid-stream) and raises
    `SpeechBusyError` so stale results never overwrite a newer capture or turn.
  - Tracks network drops/timeouts after request dispatch (`GnaniTransportError` with `status_code is None`)
    as `uncertain=1` (`stt_seconds_uncertain`, `tts_chars_uncertain`, `uncertain_requests_count`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3
import threading
import uuid
from dataclasses import dataclass

from backend.app.models.api_schemas import (
    SpeechCapacityStatus,
    STTRequest,
    STTResult,
    TTSRequest,
)
from backend.app.models.enums import ExerciseId, SpecVersion, SpeechDegradationStatus
from backend.app.speech.gnani_adapter import (
    AssembledTTSSynthesis,
    GnaniSpeechAdapter,
    GnaniTransportError,
)
from backend.app.speech.pre_tts_normalizer import to_speakable
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.db.postgres import cloud


class SpeechBusyError(RuntimeError):
    """Raised when the single-concurrency queue is full, wait timeout expires, or request is superseded."""


class SpeechQuotaExhaustedError(RuntimeError):
    """Raised when speech usage budgets (`max_stt_seconds` or `max_tts_chars`) are exhausted."""


@dataclass
class _TurnCaptureTracker:
    turn_generation: int
    latest_capture_attempt_id: int
    cancelled_attempts: set[int]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def accounted_speech_totals(conn: sqlite3.Connection) -> tuple[float, int]:
    """Global audio budgets count legacy, studio and common-module reservations."""
    seconds = 0.0
    chars = 0
    for table in ('usage_reservations', 'studio_speech_usage', 'module_speech_usage'):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        row = conn.execute(f"SELECT COALESCE(SUM(stt_seconds),0),COALESCE(SUM(tts_chars),0) FROM {table} WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN')").fetchone()
        seconds += row[0]
        chars += row[1]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_speech_deleted_totals'").fetchone():
        # Duration/character caps are lifetime budgets, unlike the daily call limit.
        retained = conn.execute('SELECT COALESCE(SUM(stt_seconds),0),COALESCE(SUM(tts_chars),0) FROM module_speech_deleted_totals').fetchone()
        seconds += retained[0]
        chars += retained[1]
    return seconds, chars


class SpeechGatekeeper:
    """Single-concurrency dispatcher and durable SQLite usage ledger for Gnani Speech APIs."""

    def __init__(
        self,
        adapter: GnaniSpeechAdapter,
        *,
        db_path: Path | str = ":memory:",
        max_concurrency: int = 1,
        max_waiting: int = 10,
        queue_wait_timeout_sec: float = 6.0,
        max_stt_seconds_budget: float = 7200.0,
        max_tts_chars_budget: int = 250_000,
        retry_backoff_base_sec: float = 0.25,
        max_429_retries: int = 2,
        per_session_stt_seconds: float | None = None,
        per_session_tts_chars: int | None = None,
        global_daily_call_limit: int | None = None,
    ) -> None:
        if max_concurrency != 1:
            raise ValueError("Gnani constraint requires max_concurrency == 1.")
        self.adapter = adapter
        self.db_path = db_path if isinstance(db_path, PostgresTarget) else str(db_path)
        self._cloud = isinstance(db_path, PostgresTarget)
        self.max_concurrency = 1
        self.max_waiting = max_waiting
        self.queue_wait_timeout_sec = queue_wait_timeout_sec
        self.max_stt_seconds_budget = max_stt_seconds_budget
        self.max_tts_chars_budget = max_tts_chars_budget
        self.retry_backoff_base_sec = retry_backoff_base_sec
        self.max_429_retries = max_429_retries
        self.per_session_stt_seconds = per_session_stt_seconds
        self.per_session_tts_chars = per_session_tts_chars
        self.global_daily_call_limit = global_daily_call_limit

        self._semaphore = asyncio.Semaphore(1)
        self._active_count = 0
        self._waiting_count = 0
        self._degradation = SpeechDegradationStatus.HEALTHY
        self._session_captures: dict[str, _TurnCaptureTracker] = {}
        self._cancelled_turns: set[tuple[str, int]] = set()
        self._db_lock = threading.RLock()

        if self._cloud:
            from backend.app.db.migrations import open_connection
            self._conn = open_connection(self.db_path)
        else:
            if self.db_path != ":memory:" and not self.db_path.startswith("file:"):
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._init_db()

    def _table_columns(self, table_name: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table_name});").fetchall()
        return {str(row[1]) for row in rows}

    def recover_pending_usage(self) -> int:
        """Recover abandoned reservations once at single-coordinator startup.

        Provider work may have happened before a crash. Retain its reserved
        upper bound as uncertain rather than releasing potentially billed use.
        This method must not run while another coordinator is serving requests.
        """
        with self._db_lock:
            clause = ' AND created_at<?' if self._cloud else ''
            parameters = ((datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat(),) if self._cloud else ()
            rows = self._conn.execute(
                "SELECT * FROM usage_reservations WHERE status='RESERVED' "
                "AND operation_type IN ('STT','TTS')" + clause, parameters
            ).fetchall()
        for row in rows:
            self._finalize_reservation(
                row["id"],
                session_id=row["session_id"],
                turn_generation=row["turn_generation"],
                operation_type=row["operation_type"],
                committed=False,
                uncertain=True,
                actual_stt_sec=row["stt_seconds"],
                actual_tts_chars=row["tts_chars"],
            )
        return len(rows)

    def _ensure_column(self, table_name: str, col_name: str, col_ddl: str) -> None:
        if col_name not in self._table_columns(table_name):
            self._conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_ddl};"
            )

    def _init_db(self) -> None:
        with self._db_lock:
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")

            # Create P0-compatible sessions, usage_reservations, and usage_ledger if absent
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    exercise_id TEXT NOT NULL,
                    spec_version TEXT NOT NULL,
                    spec_acknowledged INTEGER NOT NULL DEFAULT 1 CHECK (spec_acknowledged IN (0, 1)),
                    language_mode TEXT NOT NULL,
                    interaction_mode TEXT NOT NULL,
                    active_code_version_id INTEGER NOT NULL DEFAULT 1,
                    active_turn_generation INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'READY',
                    learning_state TEXT NOT NULL DEFAULT 'EXPLAINING',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_reservations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    operation_type TEXT NOT NULL,
                    stt_seconds REAL NOT NULL DEFAULT 0.0,
                    tts_chars INTEGER NOT NULL DEFAULT 0,
                    request_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    operation_type TEXT NOT NULL,
                    stt_seconds REAL NOT NULL DEFAULT 0.0,
                    tts_chars INTEGER NOT NULL DEFAULT 0,
                    request_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Idempotently add Phase 2 columns on both brand-new and existing Phase 0 tables
            self._ensure_column("usage_reservations", "reservation_id", "TEXT")
            self._ensure_column(
                "usage_reservations", "turn_generation", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "usage_reservations", "reserved_stt_sec", "REAL NOT NULL DEFAULT 0.0"
            )
            self._ensure_column(
                "usage_reservations", "reserved_tts_chars", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "usage_reservations", "uncertain", "INTEGER NOT NULL DEFAULT 0"
            )

            self._ensure_column("usage_ledger", "entry_id", "TEXT")
            self._ensure_column(
                "usage_ledger", "reservation_id", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(
                "usage_ledger", "turn_generation", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "usage_ledger", "cache_hit", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "usage_ledger", "uncertain", "INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_session_row_in_tx(self, session_id: str) -> None:
        """Ensure `session_id` exists in `sessions` when `PRAGMA foreign_keys = ON` is active."""
        existing = self._conn.execute(
            "SELECT deleted_at FROM sessions WHERE id = ? LIMIT 1;",
            (session_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] is not None:
                raise SpeechBusyError("Session deleted; speech is cancelled.")
            return
        if self._cloud:
            raise SpeechBusyError('Shared speech session is unavailable')
        now_iso = _utc_now_iso()
        exp_iso = _utc_future_iso(24)
        token_hash = hashlib.sha256(
            f"gatekeeper_auto_{session_id}".encode("utf-8")
        ).hexdigest()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO sessions (
                id, token_hash, exercise_id, spec_version, spec_acknowledged,
                language_mode, interaction_mode, active_code_version_id,
                active_turn_generation, state, learning_state,
                created_at, updated_at, expires_at, deleted_at
            ) VALUES (?, ?, ?, ?, 1, 'en-IN', 'VOICE', 1, 0, 'READY', 'EXPLAINING', ?, ?, ?, NULL);
            """,
            (
                session_id,
                token_hash,
                ExerciseId.EX1_SHORTEST_SUBARRAY.value,
                SpecVersion.EX1_V1_POSITIVE_ONLY.value,
                now_iso,
                now_iso,
                exp_iso,
            ),
        )

    def register_capture_attempt(
        self,
        session_id: str,
        turn_generation: int,
        capture_attempt_id: int | None = None,
    ) -> int:
        """Register a microphone capture attempt without incrementing `turn_generation`.

        If the learner re-records on the same `turn_generation`, all prior `capture_attempt_id`s
        for that turn are marked superseded/cancelled and the incremented `capture_attempt_id`
        is returned.
        """
        tracker = self._session_captures.get(session_id)
        if tracker is None or tracker.turn_generation != turn_generation:
            attempt_id = capture_attempt_id if capture_attempt_id is not None else 1
            self._session_captures[session_id] = _TurnCaptureTracker(
                turn_generation=turn_generation,
                latest_capture_attempt_id=attempt_id,
                cancelled_attempts=set(),
            )
            return attempt_id

        prev_attempt = tracker.latest_capture_attempt_id
        next_attempt = (
            capture_attempt_id
            if (capture_attempt_id is not None and capture_attempt_id > prev_attempt)
            else prev_attempt + 1
        )
        # is_capture_superseded compares monotonic IDs; never allocate a set
        # proportional to an untrusted capture-attempt integer.
        tracker.latest_capture_attempt_id = next_attempt
        return next_attempt

    def is_capture_superseded(
        self,
        session_id: str,
        turn_generation: int,
        capture_attempt_id: int,
    ) -> bool:
        if self._cloud:
            with self._db_lock:
                row = self._conn.execute('SELECT s.deleted_at,s.expires_at,s.active_turn_generation,MAX(t.latest_capture_attempt_id) AS capture FROM sessions s LEFT JOIN turns t ON t.session_id=s.id AND t.turn_generation=s.active_turn_generation WHERE s.id=? GROUP BY s.id', (session_id,)).fetchone()
                cancelled = self._conn.execute("SELECT 1 FROM turns WHERE session_id=? AND turn_generation=? AND latest_capture_attempt_id=? AND state IN ('CANCELLED','SUPERSEDED')", (session_id, turn_generation, capture_attempt_id)).fetchone()
            if (not row or row['deleted_at'] is not None or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc)
                    or row['active_turn_generation'] != turn_generation or (row['capture'] is not None and row['capture'] > capture_attempt_id) or cancelled):
                return True
        if (session_id, turn_generation) in self._cancelled_turns:
            return True
        tracker = self._session_captures.get(session_id)
        if tracker is None:
            return False
        if tracker.turn_generation > turn_generation:
            return True
        if tracker.turn_generation == turn_generation:
            if capture_attempt_id in tracker.cancelled_attempts:
                return True
            if capture_attempt_id < tracker.latest_capture_attempt_id:
                return True
        return False

    def cancel_turn_speech(self, session_id: str, turn_generation: int) -> None:
        """Cancel any queued or in-flight STT/TTS operation for `(session_id, turn_generation)`."""
        self._cancelled_turns.add((session_id, turn_generation))
        tracker = self._session_captures.get(session_id)
        if tracker and tracker.turn_generation == turn_generation:
            tracker.cancelled_attempts.add(tracker.latest_capture_attempt_id)

    def get_capacity_status(self) -> SpeechCapacityStatus:
        with self._db_lock:
            res_row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(stt_seconds), 0.0),
                    COALESCE(SUM(tts_chars), 0)
                FROM usage_reservations
                WHERE status = 'RESERVED';
                """
            ).fetchone()
            stt_reserved = round(float(res_row[0] if res_row else 0.0), 4)
            tts_reserved = int(res_row[1] if res_row else 0)

            led_row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status = 'COMMITTED' AND COALESCE(uncertain, 0) = 0 THEN stt_seconds ELSE 0.0 END), 0.0),
                    COALESCE(SUM(CASE WHEN status = 'COMMITTED' AND COALESCE(uncertain, 0) = 1 THEN stt_seconds ELSE 0.0 END), 0.0),
                    COALESCE(SUM(CASE WHEN status = 'COMMITTED' AND COALESCE(uncertain, 0) = 0 THEN tts_chars ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'COMMITTED' AND COALESCE(uncertain, 0) = 1 THEN tts_chars ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN operation_type = 'STT' AND status = 'COMMITTED' AND COALESCE(uncertain, 0) = 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN operation_type = 'TTS' AND status = 'COMMITTED' AND COALESCE(cache_hit, 0) = 0 AND COALESCE(uncertain, 0) = 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'COMMITTED' AND COALESCE(uncertain, 0) = 1 THEN 1 ELSE 0 END), 0)
                FROM usage_ledger;
                """
            ).fetchone()

            stt_used = round(float(led_row[0] if led_row else 0.0), 4)
            stt_uncertain = round(float(led_row[1] if led_row else 0.0), 4)
            tts_used = int(led_row[2] if led_row else 0)
            tts_uncertain = int(led_row[3] if led_row else 0)
            stt_reqs = int(led_row[4] if led_row else 0)
            tts_reqs = int(led_row[5] if led_row else 0)
            uncertain_reqs = int(led_row[6] if led_row else 0)

        active = cloud.count(self.db_path, kind='speech') if self._cloud else self._active_count
        return SpeechCapacityStatus(
            deployment_topology="DISTRIBUTED_POSTGRES_LEASE" if self._cloud else "SINGLE_PROCESS_LOCAL_SEMAPHORE",
            max_concurrency=self.max_concurrency,
            active_requests=active,
            queued_requests=self._waiting_count,
            max_waiting=self.max_waiting,
            degradation_status=self._degradation,
            stt_seconds_used=stt_used,
            stt_seconds_reserved=stt_reserved,
            stt_seconds_uncertain=stt_uncertain,
            tts_chars_used=tts_used,
            tts_chars_reserved=tts_reserved,
            tts_chars_uncertain=tts_uncertain,
            stt_requests_count=stt_reqs,
            tts_requests_count=tts_reqs,
            uncertain_requests_count=uncertain_reqs,
            credit_remaining_status="UNKNOWN_UNVERIFIED_TARIFF",
        )

    def _reserve_usage(
        self,
        *,
        session_id: str,
        turn_generation: int,
        operation_type: str,
        est_stt_sec: float = 0.0,
        est_tts_chars: int = 0,
        provider_calls: int = 1,
    ) -> str:
        """Atomically admit and record a `RESERVED` usage entry inside `BEGIN IMMEDIATE` (Fix P2-06)."""
        res_id = f"res_{uuid.uuid4().hex[:16]}"
        now_iso = _utc_now_iso()

        with self._db_lock:
            self._conn.execute("BEGIN IMMEDIATE;")
            try:
                self._ensure_session_row_in_tx(session_id)
                accounted_stt_sec, accounted_tts_chars = accounted_speech_totals(self._conn)

                if (
                    operation_type == "STT"
                    and accounted_stt_sec + est_stt_sec > self.max_stt_seconds_budget
                ) or (
                    operation_type == "TTS"
                    and accounted_tts_chars + est_tts_chars > self.max_tts_chars_budget
                ):
                    self._conn.execute("ROLLBACK;")
                    self._degradation = (
                        SpeechDegradationStatus.QUOTA_EXHAUSTED_TEXT_ONLY
                    )
                    raise SpeechQuotaExhaustedError(
                        f"Speech {operation_type} quota exhausted; falling back to text mode."
                    )

                session_usage = self._conn.execute("SELECT COALESCE(SUM(stt_seconds),0), COALESCE(SUM(tts_chars),0) FROM usage_reservations WHERE session_id=? AND status IN ('RESERVED','COMMITTED')", (session_id,)).fetchone()
                day_count = self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM usage_reservations WHERE status IN ('RESERVED','COMMITTED') AND date(created_at)=date(?)", (now_iso,)).fetchone()[0]
                if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_speech_usage'").fetchone():
                    day_count += self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM studio_speech_usage WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)", (now_iso,)).fetchone()[0]
                    day_count += self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM studio_speech_deleted_daily WHERE day=date(?)", (now_iso,)).fetchone()[0]
                if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_speech_usage'").fetchone():
                    day_count += self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM module_speech_usage WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)", (now_iso,)).fetchone()[0]
                if ((self.per_session_stt_seconds is not None and session_usage[0]+est_stt_sec > self.per_session_stt_seconds)
                    or (self.per_session_tts_chars is not None and session_usage[1]+est_tts_chars > self.per_session_tts_chars)
                    or (self.global_daily_call_limit is not None and day_count + provider_calls > self.global_daily_call_limit)):
                    self._conn.execute("ROLLBACK")
                    raise SpeechQuotaExhaustedError("Configured session or daily speech budget exhausted; use typed input.")
                self._conn.execute(
                    """
                    INSERT INTO usage_reservations (
                        id, reservation_id, session_id, turn_generation, operation_type,
                        stt_seconds, reserved_stt_sec, tts_chars, reserved_tts_chars,
                        request_count, uncertain, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'RESERVED', ?, ?);
                    """,
                    (
                        res_id,
                        res_id,
                        session_id,
                        turn_generation,
                        operation_type,
                        est_stt_sec,
                        est_stt_sec,
                        est_tts_chars,
                        est_tts_chars,
                        provider_calls,
                        now_iso,
                        now_iso,
                    ),
                )
                self._conn.execute("COMMIT;")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK;")
                raise

        return res_id

    def _finalize_reservation(
        self,
        reservation_id: str,
        *,
        session_id: str,
        turn_generation: int,
        operation_type: str,
        committed: bool,
        uncertain: bool = False,
        actual_stt_sec: float = 0.0,
        actual_tts_chars: int = 0,
        cache_hit: bool = False,
        actual_provider_calls: int | None = None,
    ) -> None:
        effective_committed = committed or uncertain or bool(actual_provider_calls)
        final_status = "COMMITTED" if effective_committed else "RELEASED"
        uncertain_flag = 1 if uncertain else 0
        recorded_stt = actual_stt_sec if effective_committed else 0.0
        recorded_tts = actual_tts_chars if effective_committed else 0
        entry_id = f"led_{uuid.uuid4().hex[:16]}"
        now_iso = _utc_now_iso()

        with self._db_lock:
            self._conn.execute("BEGIN IMMEDIATE;")
            try:
                # Never recreate a deleted session when a late provider request settles.
                session = self._conn.execute(
                    "SELECT deleted_at FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
                if session is None:
                    self._conn.execute("COMMIT;")
                    return
                reservation = self._conn.execute('SELECT status FROM usage_reservations WHERE id=? OR reservation_id=?', (reservation_id, reservation_id)).fetchone()
                if reservation is None or reservation['status'] != 'RESERVED':
                    self._conn.execute('COMMIT')
                    return
                if effective_committed:
                    self._conn.execute(
                        """
                        UPDATE usage_reservations
                        SET status = ?,
                            stt_seconds = ?,
                            reserved_stt_sec = ?,
                            tts_chars = ?,
                            reserved_tts_chars = ?,
                            uncertain = ?,
                            updated_at = ?
                        WHERE id = ? OR reservation_id = ?;
                        """,
                        (
                            final_status,
                            recorded_stt,
                            recorded_stt,
                            recorded_tts,
                            recorded_tts,
                            uncertain_flag,
                            now_iso,
                            reservation_id,
                            reservation_id,
                        ),
                    )
                else:
                    self._conn.execute(
                        """
                        UPDATE usage_reservations
                        SET status = 'RELEASED',
                            uncertain = 0,
                            updated_at = ?
                        WHERE id = ? OR reservation_id = ?;
                        """,
                        (now_iso, reservation_id, reservation_id),
                    )

                if actual_provider_calls is not None:
                    self._conn.execute('UPDATE usage_reservations SET request_count=? WHERE id=?',
                                       (actual_provider_calls, reservation_id))
                else:
                    count_row = self._conn.execute('SELECT request_count FROM usage_reservations WHERE id=?', (reservation_id,)).fetchone()
                    actual_provider_calls = 0 if cache_hit else (count_row[0] if count_row else 1)
                self._conn.execute(
                    """
                    INSERT INTO usage_ledger (
                        id, entry_id, reservation_id, session_id, turn_generation,
                        operation_type, stt_seconds, tts_chars, request_count,
                        cache_hit, uncertain, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        entry_id,
                        entry_id,
                        reservation_id,
                        session_id,
                        turn_generation,
                        operation_type,
                        recorded_stt,
                        recorded_tts,
                        actual_provider_calls,
                        1 if cache_hit else 0,
                        uncertain_flag,
                        final_status,
                        now_iso,
                        now_iso,
                    ),
                )
                self._conn.execute("COMMIT;")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK;")
                raise

    async def _acquire_single_slot(self, session_id: str | None = None):
        if self._waiting_count >= self.max_waiting:
            self._degradation = SpeechDegradationStatus.SPEECH_BUSY_TEXT_FALLBACK
            raise SpeechBusyError(
                f"Speech queue full ({self._waiting_count} waiting); falling back to text input."
            )
        self._waiting_count += 1
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.queue_wait_timeout_sec,
            )
        except TimeoutError as exc:
            self._degradation = SpeechDegradationStatus.SPEECH_BUSY_TEXT_FALLBACK
            raise SpeechBusyError(
                f"Timed out waiting {self.queue_wait_timeout_sec:.1f}s for single-concurrency speech slot."
            ) from exc
        finally:
            self._waiting_count -= 1
        self._active_count += 1
        if self._cloud:
            try:
                admission = asyncio.create_task(asyncio.to_thread(cloud.acquire, self.db_path,
                    kind='speech', owner=session_id or str(uuid.uuid4()), limit=1, seconds=60))
                try:
                    lease = await asyncio.shield(admission)
                except asyncio.CancelledError:
                    lease = await admission
                    if lease is not None:
                        await asyncio.to_thread(cloud.finish, self.db_path, lease)
                    raise
                if lease is None:
                    raise SpeechBusyError('Shared speech provider is busy or awaiting reconciliation')
                return lease
            except BaseException:
                self._active_count = max(0, self._active_count - 1)
                self._semaphore.release()
                raise
        return None

    def _start_single_slot(self, lease) -> None:
        if lease is not None:
            cloud.start(self.db_path, lease)

    def _release_single_slot(self, lease=None, *, uncertain: bool = False) -> None:
        try:
            if lease is not None:
                cloud.finish(self.db_path, lease, uncertain=uncertain)
        finally:
            self._active_count = max(0, self._active_count - 1)
            self._semaphore.release()

    def _reserve_retry_calls(self, reservation_id: str, total_calls: int) -> None:
        """Re-admit physical retries atomically against the shared daily call budget."""
        with self._db_lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                today = _utc_now_iso()
                count = self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM usage_reservations WHERE status IN ('RESERVED','COMMITTED') AND id!=? AND date(created_at)=date(?)", (reservation_id, today)).fetchone()[0]
                if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_speech_usage'").fetchone():
                    count += self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM studio_speech_usage WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)", (today,)).fetchone()[0]
                    count += self._conn.execute('SELECT COALESCE(SUM(request_count),0) FROM studio_speech_deleted_daily WHERE day=date(?)', (today,)).fetchone()[0]
                if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_speech_usage'").fetchone():
                    count += self._conn.execute("SELECT COALESCE(SUM(request_count),0) FROM module_speech_usage WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)", (today,)).fetchone()[0]
                if self.global_daily_call_limit is not None and count + total_calls > self.global_daily_call_limit:
                    raise SpeechQuotaExhaustedError('Speech retry would exceed the daily budget; continue with text.')
                self._conn.execute('UPDATE usage_reservations SET request_count=? WHERE id=?', (total_calls, reservation_id))
                self._conn.execute('COMMIT')
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute('ROLLBACK')
                raise

    async def execute_stt(
        self,
        req: STTRequest,
        wav_bytes: bytes,
        *,
        transcribe_fn: Callable[[STTRequest, bytes], Awaitable[STTResult]]
        | None = None,
        assert_current: Callable[[], None] | None = None,
    ) -> STTResult:
        """Execute a single-concurrency Gnani STT request with durable reservation & freshness recheck."""
        if self.is_capture_superseded(
            req.session_id, req.turn_generation, req.capture_attempt_id
        ):
            raise SpeechBusyError(
                "Capture attempt superseded by newer recording or turn cancellation."
            )

        est_sec = min(30.0, max(0.5, len(wav_bytes) / 32000.0))
        res_id = self._reserve_usage(
            session_id=req.session_id,
            turn_generation=req.turn_generation,
            operation_type="STT",
            est_stt_sec=est_sec,
        )

        slot_acquired = False
        committed = False
        uncertain = False
        actual_sec = 0.0
        physical_calls = 0
        dispatched = False
        slot = None
        lease_started = False
        try:
            slot = await self._acquire_single_slot(req.session_id) if self._cloud else await self._acquire_single_slot()
            slot_acquired = True

            if self.is_capture_superseded(
                req.session_id, req.turn_generation, req.capture_attempt_id
            ):
                raise SpeechBusyError(
                    "Capture attempt cancelled while waiting in speech queue."
                )

            attempt = 0
            while True:
                try:
                    if assert_current is not None:
                        assert_current()
                    if not lease_started:
                        self._start_single_slot(slot)
                        lease_started = True
                    dispatched = True
                    physical_calls += 1
                    result = await asyncio.wait_for((transcribe_fn or self.adapter.transcribe_rest)(req, wav_bytes), timeout=60.0)
                    committed = True
                    actual_sec = result.audio_duration_sec

                    # Post-provider freshness recheck (Fix P2-06)
                    if self.is_capture_superseded(
                        req.session_id, req.turn_generation, req.capture_attempt_id
                    ):
                        raise SpeechBusyError(
                            "Capture attempt or turn superseded while provider request was in flight."
                        )

                    self._degradation = SpeechDegradationStatus.HEALTHY
                    return result
                except GnaniTransportError as exc:
                    if exc.status_code is not None:
                        dispatched = False  # Known rejection, not unknown billed audio.
                    if (
                        exc.status_code == 429
                        and exc.retryable
                        and attempt < self.max_429_retries
                    ):
                        self._reserve_retry_calls(res_id, physical_calls + 1)
                        attempt += 1
                        await asyncio.sleep(
                            self.retry_backoff_base_sec * (2 ** (attempt - 1))
                        )
                        if self.is_capture_superseded(
                            req.session_id, req.turn_generation, req.capture_attempt_id
                        ):
                            raise SpeechBusyError(
                                "Capture attempt superseded during 429 retry backoff."
                            ) from exc
                        continue
                    if exc.status_code is None:
                        # Network drop or timeout after request dispatch: provider ack lost
                        uncertain = True
                        actual_sec = est_sec
                    self._degradation = (
                        SpeechDegradationStatus.STT_UNAVAILABLE_TEXT_FALLBACK
                    )
                    raise
        except asyncio.CancelledError:
            uncertain = dispatched and not committed
            actual_sec = actual_sec or (est_sec if uncertain else 0.0)
            raise
        except Exception as exc:
            # The dispatcher has handed off work: browser/protocol errors can
            # occur after provider contact just as transport failures can.
            # Known provider rejections retain their explicit accounting;
            # unknown post-dispatch failures keep the reserved upper bound.
            if dispatched and not committed and not isinstance(exc, GnaniTransportError):
                uncertain = True
                actual_sec = est_sec
            raise
        finally:
            settled = False
            try:
                self._finalize_reservation(res_id, session_id=req.session_id,
                    turn_generation=req.turn_generation, operation_type='STT', committed=committed,
                    uncertain=uncertain, actual_stt_sec=actual_sec, actual_provider_calls=physical_calls)
                settled = True
            finally:
                if slot_acquired:
                    self._release_single_slot(slot, uncertain=uncertain or (dispatched and not settled))

    async def execute_tts(
        self, req: TTSRequest, *, on_event=None, assert_current: Callable[[], None] | None = None
    ) -> AssembledTTSSynthesis:
        """Execute a single-concurrency Gnani SSE TTS request with durable reservation & freshness recheck."""
        if (req.session_id, req.turn_generation) in self._cancelled_turns:
            raise SpeechBusyError("Turn already cancelled before TTS synthesis.")

        speakable_chunks = to_speakable(req.text)
        get_cached = getattr(self.adapter, "get_cached_tts", None)
        cached = get_cached(req) if get_cached else None
        est_chars = 0 if cached is not None else (sum(len(c) for c in speakable_chunks) or len(req.text))
        res_id = self._reserve_usage(
            session_id=req.session_id,
            turn_generation=req.turn_generation,
            operation_type="TTS",
            est_tts_chars=est_chars,
            provider_calls=0 if cached is not None else len(speakable_chunks),
        )

        slot_acquired = False
        committed = False
        uncertain = False
        billed_chars = 0
        was_cache_hit = False
        physical_calls = 0
        dispatched = False
        slot = None
        lease_started = False
        try:
            slot = await self._acquire_single_slot(req.session_id) if self._cloud else await self._acquire_single_slot()
            slot_acquired = True

            if (req.session_id, req.turn_generation) in self._cancelled_turns:
                raise SpeechBusyError("Turn cancelled while waiting in TTS queue.")

            attempt = 0
            while True:
                try:
                    if assert_current is not None:
                        assert_current()
                    if cached is None and not lease_started:
                        self._start_single_slot(slot)
                        lease_started = True
                    dispatched = cached is None
                    kwargs = {
                        "is_cancelled": lambda: (
                            (req.session_id, req.turn_generation)
                            in self._cancelled_turns
                        )
                    }
                    if on_event is not None:
                        kwargs["on_event"] = on_event
                    synthesis = cached if cached is not None else await asyncio.wait_for(self.adapter.synthesize_tts(req, **kwargs), timeout=60.0)
                    committed = True
                    billed_chars = synthesis.total_chars_billed
                    was_cache_hit = synthesis.cache_hit
                    physical_calls += 0 if was_cache_hit else (getattr(synthesis, 'provider_calls', 0) or len(speakable_chunks))

                    # Post-provider freshness recheck (Fix P2-06)
                    if (req.session_id, req.turn_generation) in self._cancelled_turns:
                        raise SpeechBusyError(
                            "Capture attempt or turn superseded while provider request was in flight."
                        )

                    self._degradation = SpeechDegradationStatus.HEALTHY
                    return synthesis
                except GnaniTransportError as exc:
                    physical_calls += exc.dispatched_calls if exc.dispatched_calls is not None else 1
                    if exc.status_code is not None and exc.completed_chars == 0 and not exc.audio_emitted:
                        dispatched = False
                    if (
                        exc.status_code == 429
                        and exc.completed_chars == 0
                        and not exc.audio_emitted
                        and exc.retryable
                        and attempt < self.max_429_retries
                    ):
                        self._reserve_retry_calls(res_id, physical_calls + len(speakable_chunks))
                        attempt += 1
                        await asyncio.sleep(
                            self.retry_backoff_base_sec * (2 ** (attempt - 1))
                        )
                        if (
                            req.session_id,
                            req.turn_generation,
                        ) in self._cancelled_turns:
                            raise SpeechBusyError(
                                "Turn cancelled during TTS 429 retry backoff."
                            ) from exc
                        continue
                    if (req.session_id, req.turn_generation) in self._cancelled_turns:
                        # Cancelled mid-stream while provider request was in flight
                        uncertain = True
                        billed_chars = est_chars
                        raise SpeechBusyError(
                            "Capture attempt or turn superseded while provider request was in flight."
                        ) from exc
                    if exc.status_code is None or exc.completed_chars > 0:
                        uncertain = True
                        billed_chars = est_chars
                    self._degradation = (
                        SpeechDegradationStatus.TTS_UNAVAILABLE_READ_FALLBACK
                    )
                    raise
        except asyncio.CancelledError:
            uncertain = dispatched and not committed
            billed_chars = billed_chars or (est_chars if uncertain else 0)
            raise
        except Exception as exc:
            if dispatched and not committed and not isinstance(exc, GnaniTransportError):
                uncertain = True
                billed_chars = est_chars
            raise
        finally:
            settled = False
            try:
                self._finalize_reservation(res_id, session_id=req.session_id,
                    turn_generation=req.turn_generation, operation_type='TTS', committed=committed,
                    uncertain=uncertain, actual_tts_chars=billed_chars, cache_hit=was_cache_hit,
                    actual_provider_calls=physical_calls if not uncertain else max(physical_calls, len(speakable_chunks)))
                settled = True
            finally:
                if slot_acquired:
                    self._release_single_slot(slot, uncertain=uncertain or (dispatched and not settled))
