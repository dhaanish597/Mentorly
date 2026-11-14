"""Bounded expiry cleanup; tombstone before cancelling/evicting private work."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
import time

from backend.app.core.logging import get_logger
from backend.app.db.repository import SQLiteRepository
from backend.app.speech.service import SpeechService

_LOGGER = get_logger("vcc.retention")
CANCELLATION_WINDOW_SECONDS = 3.0


@dataclass(frozen=True)
class RetentionReport:
    expired_sessions: int = 0
    evicted_audio_files: int = 0
    unconfirmed_broker_cancellations: int = 0
    pending_audio_cancellations: int = 0
    errors: int = 0


class RetentionService:
    def __init__(self, repository: SQLiteRepository, speech: SpeechService, *,
                 worker_client=None, interval_seconds: float = 60, batch_size: int = 100) -> None:
        if interval_seconds <= 0 or not 1 <= batch_size <= 1000:
            raise ValueError("Retention intervals and batch size must be bounded and positive")
        self.repository = repository
        self.speech = speech
        self.worker_client = worker_client
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self._sweep_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.last_report = RetentionReport()

    def _expired(self, now: datetime) -> list[tuple[str, int]]:
        with closing(self.repository._connect()) as conn:
            rows = conn.execute(
                "SELECT id,active_turn_generation FROM sessions WHERE deleted_at IS NULL "
                "AND julianday(expires_at) <= julianday(?) ORDER BY expires_at LIMIT ?",
                (now.isoformat(), self.batch_size),
            ).fetchall()
        return [(row["id"], row["active_turn_generation"]) for row in rows]

    async def _cancel_broker_jobs(self, jobs: list[str]) -> list[str]:
        from uuid import UUID
        deadline = time.monotonic() + CANCELLATION_WINDOW_SECONDS
        remaining = list(jobs)
        for job in jobs:
            if self.worker_client is None or time.monotonic() >= deadline:
                break
            try:
                accepted = await asyncio.wait_for(
                    asyncio.to_thread(self.worker_client.cancel, UUID(job)),
                    timeout=max(0.01, deadline - time.monotonic()),
                )
                if accepted:
                    remaining = [candidate for candidate in remaining if candidate != job]
            except Exception:
                _LOGGER.warning("Expiry broker cancellation remains unconfirmed")
        return remaining

    async def _evict_after_audio_barrier(self, session_id: str, generation: int) -> tuple[int, int]:
        pending = await self.speech.cancel_session(session_id, generation)
        if pending:
            return 0, pending
        removed = await asyncio.to_thread(self.speech.cache.evict_session, session_id)
        return removed, 0

    async def run_once(self, *, now: datetime | None = None) -> RetentionReport:
        async with self._sweep_lock:
            return await self._run_once(now=now)

    async def _run_once(self, *, now: datetime | None = None) -> RetentionReport:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("Retention timestamps must include a timezone")
        expired = await asyncio.to_thread(self._expired, current)
        expired_count = evicted = broker_pending = audio_pending = errors = 0
        for session_id, generation in expired:
            try:
                await asyncio.to_thread(self.repository.request_execution_cancellation, session_id)
                await asyncio.to_thread(self.repository.tombstone_session, session_id)
                expired_count += 1
            except Exception:
                errors += 1
                _LOGGER.exception("Expired session cleanup did not complete")
        obligations = await asyncio.to_thread(self._cleanup_obligations)
        for obligation in obligations:
            try:
                session_id = obligation["session_id"]
                incomplete_audio = False
                if obligation["audio_pending"]:
                    try:
                        removed, pending = await self._evict_after_audio_barrier(session_id, obligation["turn_generation"])
                        evicted += removed
                        audio_pending += pending
                        incomplete_audio = bool(pending)
                    except Exception:
                        incomplete_audio = True
                        errors += 1
                        _LOGGER.exception("Private audio eviction remains pending")
                remaining = await self._cancel_broker_jobs(obligation["pending_jobs"])
                broker_pending += len(remaining)
                await asyncio.to_thread(self.record_cleanup, session_id, audio_pending=incomplete_audio,
                    confirmed_jobs=[job for job in obligation["pending_jobs"] if job not in remaining])
            except Exception:
                errors += 1
                _LOGGER.exception("Durable private cleanup remains pending")
        try:
            evicted += await asyncio.to_thread(self.speech.cache.enforce_limits)
            await asyncio.to_thread(self.speech.cache.cleanup_partial_temps)
        except Exception:
            errors += 1
            _LOGGER.exception("Audio cache maintenance failed")
        self.last_report = RetentionReport(expired_count, evicted, broker_pending, audio_pending, errors)
        return self.last_report

    def _cleanup_obligations(self) -> list[dict]:
        import json
        with closing(self.repository._connect()) as conn:
            rows = conn.execute("SELECT * FROM cleanup_obligations ORDER BY updated_at LIMIT ?", (self.batch_size,)).fetchall()
        return [{"session_id": row["session_id"], "turn_generation": row["turn_generation"],
                 "audio_pending": bool(row["audio_pending"]), "pending_jobs": json.loads(row["pending_jobs_json"])} for row in rows]

    def record_cleanup(self, session_id: str, *, audio_pending: bool, confirmed_jobs: list[str]) -> int:
        import json
        with closing(self.repository._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT pending_jobs_json FROM cleanup_obligations WHERE session_id=?", (session_id,)).fetchone()
            current_jobs = json.loads(row[0]) if row else []
            confirmed = set(confirmed_jobs)
            remaining = [job for job in current_jobs if job not in confirmed]
            if row is None and audio_pending:
                timestamp = datetime.now(timezone.utc).isoformat()
                conn.execute("INSERT INTO cleanup_obligations(session_id,turn_generation,audio_pending,pending_jobs_json,created_at,updated_at) SELECT id,active_turn_generation,1,'[]',?,? FROM sessions WHERE id=? AND deleted_at IS NOT NULL", (timestamp,timestamp,session_id))
            if not audio_pending and not remaining:
                conn.execute("DELETE FROM cleanup_obligations WHERE session_id=?", (session_id,))
            else:
                conn.execute("UPDATE cleanup_obligations SET audio_pending=?,pending_jobs_json=?,updated_at=? WHERE session_id=?",
                    (int(audio_pending), json.dumps(remaining), datetime.now(timezone.utc).isoformat(), session_id))
            conn.execute("COMMIT")
            return len(remaining)

    def defer_cache_cleanup(self, session_id: str) -> None:
        with closing(self.repository._connect()) as conn:
            timestamp = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT INTO cleanup_obligations(session_id,turn_generation,audio_pending,pending_jobs_json,created_at,updated_at) SELECT id,active_turn_generation,1,'[]',?,? FROM sessions WHERE id=? AND deleted_at IS NOT NULL ON CONFLICT(session_id) DO UPDATE SET audio_pending=1,updated_at=excluded.updated_at", (timestamp,timestamp,session_id))

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Retention loop already started")
        self._task = asyncio.create_task(self._run(), name="vcc-retention")

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                _LOGGER.exception("Retention sweep failed")
            await asyncio.sleep(self.interval_seconds)

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
