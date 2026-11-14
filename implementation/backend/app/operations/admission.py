"""Durable fixed-window admission and single-coordinator connection capacity.

Run the normal migrations before serving requests. Construction opens no database.
Creation limits are per direct peer; proxies' forwarding headers are never trusted.
SQLite work runs off the event loop; inflight slots cover the entire HTTP/WS lifetime.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Callable

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.logging import get_logger, get_request_id
from backend.app.db.migrations import open_connection

_SESSION_PATH = re.compile(r"^/api/v1/sessions/([^/]+)(?:/|$)")
_STUDIO_PATH = re.compile(r"^/api/v1/studio/sessions/([^/]+)(?:/|$)")
_MAX_OPENING_FRAME = 8192
_LOGGER = get_logger("vcc.admission")


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    status_code: int = 200
    code: str = ""
    retry_after: int = 0
    session_charged: bool = False


class AdmissionController:
    def __init__(
        self, database_path: str | Path, window_seconds: int = 60,
        per_ip_limit: int = 180, per_session_limit: int = 120,
        global_limit: int = 900, session_creation_limit: int = 6,
        max_inflight: int = 32, *, wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        values = (window_seconds, per_ip_limit, per_session_limit, global_limit,
                  session_creation_limit, max_inflight)
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Admission windows and limits must be positive integers.")
        self.database_path = database_path
        self.window_seconds = window_seconds
        self.per_ip_limit = per_ip_limit
        self.per_session_limit = per_session_limit
        self.global_limit = global_limit
        self.session_creation_limit = session_creation_limit
        self.max_inflight = max_inflight
        self._wall_clock, self._monotonic_clock = wall_clock, monotonic_clock
        # Only synchronization state is mutable; decisions and bucket inputs are immutable.
        self._lock = threading.Lock()
        self._inflight = 0
        self._clock_anchor: tuple[float, float] | None = None

    def try_acquire(self) -> bool:
        """Reserve one process-local slot without waiting for a free slot."""
        with self._lock:
            if self._inflight >= self.max_inflight:
                return False
            self._inflight += 1
            return True

    def release(self) -> None:
        """Release a previously acquired slot; misuse must not weaken the bound."""
        with self._lock:
            if self._inflight <= 0:
                raise RuntimeError("No admission slot is held.")
            self._inflight -= 1

    def _now(self) -> float:
        with self._lock:
            wall, monotonic = self._wall_clock(), self._monotonic_clock()
            if self._clock_anchor is None:
                self._clock_anchor = (wall, monotonic)
            anchor_wall, anchor_monotonic = self._clock_anchor
            now = max(wall, anchor_wall + monotonic - anchor_monotonic)
            self._clock_anchor = (now, monotonic)
            return now

    @staticmethod
    def _digest(subject: str) -> str:
        return hashlib.sha256(subject.encode("utf-8")).hexdigest()

    def _session_subject(self, conn: sqlite3.Connection, scope: Scope,
                         token: str | None, now: float) -> str | None:
        match = _SESSION_PATH.match(scope["path"])
        studio = _STUDIO_PATH.match(scope["path"])
        match = match or studio
        if not match:
            return None
        from uuid import UUID
        try:
            session_id = str(UUID(match.group(1)))
        except ValueError:
            return None
        if token is None:
            header = next((value for key, value in scope.get("headers", [])
                           if key.lower() == b"authorization"), b"")
            token = header[7:].decode("utf-8", errors="replace") if header.startswith(b"Bearer ") else ""
        table = "studio_sessions" if studio else "sessions"
        row = conn.execute(f"SELECT token_hash, deleted_at, expires_at FROM {table} WHERE id = ?",
                           (session_id,)).fetchone()
        try:
            digest = self._digest(token)
        except UnicodeError:
            return None
        matches = hmac.compare_digest(row["token_hash"] if row else "0" * 64, digest)
        if not row or not token or not matches or row["deleted_at"] is not None:
            return None
        try:
            expiry = datetime.fromisoformat(row["expires_at"])
            if expiry.tzinfo is None or expiry <= datetime.fromtimestamp(now, timezone.utc):
                return None
        except (ValueError, TypeError):
            return None
        return self._digest(session_id)

    def admit(self, scope: Scope, *, token: str | None = None,
              session_only: bool = False) -> AdmissionDecision:
        """Atomically charge applicable buckets; invalid capabilities charge no session.

        ``session_only`` is for the authenticated first WS frame, after connection-level
        global/IP admission. All initial-request buckets use one BEGIN IMMEDIATE.
        """
        now = self._now()
        window = int(now // self.window_seconds) * self.window_seconds
        retry_after = max(1, math.ceil(window + self.window_seconds - now))
        with closing(open_connection(self.database_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                subject = self._session_subject(conn, scope, token, now)
                buckets: tuple[tuple[str, str, int], ...] = ()
                if not session_only:
                    client = scope.get("client")
                    peer = self._digest(str(client[0]) if client else "unknown-peer")
                    buckets = (("global", self._digest("global"), self.global_limit),
                               ("ip", peer, self.per_ip_limit))
                    if scope["path"].rstrip("/") in ("/api/v1/sessions", "/api/v1/studio/sessions", "/api/v1/studio/workspaces") and scope.get("method") == "POST":
                        buckets += (("creation", peer, self.session_creation_limit),)
                if subject:
                    buckets += (("session", subject, self.per_session_limit),)
                conn.execute("DELETE FROM admission_counters WHERE window_start < ?", (window,))
                for bucket, hashed_subject, limit in buckets:
                    row = conn.execute("SELECT request_count FROM admission_counters "
                                       "WHERE bucket=? AND subject_hash=? AND window_start=?",
                                       (bucket, hashed_subject, window)).fetchone()
                    if row and row["request_count"] >= limit:
                        conn.execute("ROLLBACK")
                        return AdmissionDecision(False, 429, "RATE_LIMITED", retry_after)
                for bucket, hashed_subject, _limit in buckets:
                    conn.execute("INSERT INTO admission_counters VALUES (?, ?, ?, 1) "
                                 "ON CONFLICT(bucket, subject_hash, window_start) DO UPDATE "
                                 "SET request_count = request_count + 1",
                                 (bucket, hashed_subject, window))
                conn.execute("COMMIT")
                return AdmissionDecision(True, session_charged=subject is not None)
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise


class AdmissionMiddleware:
    def __init__(self, app: ASGIApp, controller: AdmissionController) -> None:
        self.app, self.controller = app, controller

    async def _admit(self, scope: Scope, **kwargs: object) -> AdmissionDecision:
        try:
            return await run_in_threadpool(self.controller.admit, scope, **kwargs)
        except sqlite3.Error as exc:
            _LOGGER.error("Admission database unavailable (%s)", type(exc).__name__)
            return AdmissionDecision(False, 503, "ADMISSION_UNAVAILABLE")

    @staticmethod
    async def _deny(scope: Scope, receive: Receive, send: Send,
                    decision: AdmissionDecision) -> None:
        if scope["type"] == "websocket":
            code = 4429 if decision.status_code == 429 else 1013
            await send({"type": "websocket.close", "code": code, "reason": decision.code})
            return
        message = "Request rate limit reached." if decision.status_code == 429 else "Service is busy; retry shortly."
        headers = {"Retry-After": str(decision.retry_after)} if decision.retry_after else {}
        from uuid import uuid4
        correlation_id = get_request_id()
        if correlation_id in ("-", ""):
            correlation_id = str(uuid4())
        headers = {**headers, "X-Request-ID": correlation_id, "Cache-Control": "no-store"}
        response = JSONResponse({"code": decision.code, "message": message,
                                 "request_id": correlation_id, "retryable": True,
                                 "turn_id": None, "job_id": None},
                                status_code=decision.status_code, headers=headers)
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] not in ("http", "websocket") or not (path == "/api/v1" or path.startswith("/api/v1/")):
            await self.app(scope, receive, send)
            return
        if not self.controller.try_acquire():
            await self._deny(scope, receive, send, AdmissionDecision(False, 503, "QUEUE_FULL"))
            return
        try:
            decision = await self._admit(scope)
            if not decision.allowed:
                await self._deny(scope, receive, send, decision)
            elif scope["type"] == "websocket" and not decision.session_charged:
                await self._websocket(scope, receive, send)
            else:
                await self.app(scope, receive, send)
        finally:
            self.controller.release()

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        first_frame, denied = True, False

        async def guarded_receive() -> Message:
            nonlocal first_frame, denied
            if denied:
                return {"type": "websocket.disconnect", "code": 4429}
            message = await receive()
            if not first_frame or message["type"] != "websocket.receive":
                return message
            first_frame = False
            text = message.get("text")
            if isinstance(text, str) and len(text) <= _MAX_OPENING_FRAME:
                try:
                    opening = json.loads(text)
                except (ValueError, RecursionError):
                    opening = None
                token = opening.get("token") if isinstance(opening, dict) else None
                if isinstance(token, str) and token:
                    decision = await self._admit(scope, token=token, session_only=True)
                    if not decision.allowed:
                        denied = True
                        await self._deny(scope, receive, send, decision)
                        return {"type": "websocket.disconnect", "code": 4429 if decision.status_code == 429 else 1013}
            return message

        async def guarded_send(message: Message) -> None:
            if not denied:
                await send(message)

        await self.app(scope, guarded_receive, guarded_send)
