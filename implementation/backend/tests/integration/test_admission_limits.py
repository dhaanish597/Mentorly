"""Admission behavior against real migrated SQLite and in-process ASGI transports."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest
from starlette.testclient import TestClient

from backend.app.db.migrations import apply_migrations
from backend.app.operations.admission import AdmissionController, AdmissionMiddleware


class Clock:
    def __init__(self, now: float = 1_800_000_000) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "admission.db"
    apply_migrations(path)
    return path


@pytest.fixture
def clock() -> Clock:
    return Clock()


def controller(database: Path, clock: Clock, **limits: Any) -> AdmissionController:
    defaults = dict(per_ip_limit=100, per_session_limit=100, global_limit=100,
                    session_creation_limit=100)
    return AdmissionController(database, **{**defaults, **limits},
                               wall_clock=clock, monotonic_clock=clock)


def scope(path: str = "/api/v1/meta", *, ip: str = "192.0.2.1",
          method: str = "GET", token: str | None = None,
          kind: str = "http", extra_headers: tuple = ()) -> dict:
    headers = [] if token is None else [(b"authorization", f"Bearer {token}".encode())]
    return {"type": kind, "path": path, "method": method,
            "client": (ip, 1234), "headers": headers + list(extra_headers)}


def session(database: Path, clock: Clock, sid: str = "ba93b544-62b5-4a0d-8c78-8cdb09ca5cb8", token: str = "secret",
            *, expires: float | None = None, deleted: bool = False) -> str:
    timestamp = datetime.fromtimestamp(clock(), timezone.utc).isoformat()
    expiry = datetime.fromtimestamp(clock() + 3600 if expires is None else expires,
                                    timezone.utc).isoformat()
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO sessions (id, token_hash, exercise_id, spec_version, "
            "language_mode, interaction_mode, created_at, updated_at, expires_at, deleted_at) "
            "VALUES (?, ?, 'ex1', 'v1', 'en-IN', 'TEXT', ?, ?, ?, ?)",
            (sid, hashlib.sha256(token.encode()).hexdigest(), timestamp, timestamp,
             expiry, timestamp if deleted else None),
        )
    return f"/api/v1/sessions/{sid}"


@pytest.mark.parametrize("alias", ["BA93B544-62B5-4A0D-8C78-8CDB09CA5CB8", "ba93b54462b54a0d8c788cdb09ca5cb8"])
def test_uuid_aliases_share_the_session_admission_bucket(database, clock, alias):
    canonical = session(database, clock)
    control = controller(database, clock, per_session_limit=1)
    assert control.admit(scope(canonical, token="secret")).allowed
    rejected = control.admit(scope("/api/v1/sessions/" + alias + "/speech/ws", kind="websocket"), token="secret", session_only=True)
    assert rejected.allowed is False
    assert rejected.status_code == 429


def counters(database: Path) -> list[tuple]:
    with sqlite3.connect(database) as conn:
        return conn.execute("SELECT bucket, subject_hash, window_start, request_count "
                            "FROM admission_counters ORDER BY bucket, subject_hash").fetchall()


@pytest.mark.parametrize("bucket", ["global", "ip", "creation", "session"])
def test_each_limit_denies_and_does_not_partially_increment(database: Path, clock: Clock,
                                                         bucket: str) -> None:
    limits = {"global": "global_limit", "ip": "per_ip_limit",
              "creation": "session_creation_limit", "session": "per_session_limit"}
    control = controller(database, clock, **{limits[bucket]: 2})
    path = session(database, clock) if bucket == "session" else "/api/v1/sessions"
    request = scope(path, method="POST", token="secret" if bucket == "session" else None)
    assert control.admit(request).allowed
    assert control.admit(request).allowed
    before = counters(database)
    denied = control.admit(request)
    assert not denied.allowed
    assert (denied.status_code, denied.code, denied.retry_after) == (429, "RATE_LIMITED", 60)
    assert counters(database) == before


def test_global_is_shared_across_ips_and_controller_restart(database: Path, clock: Clock) -> None:
    first = controller(database, clock, global_limit=2)
    assert first.admit(scope(ip="192.0.2.1")).allowed
    second = controller(database, clock, global_limit=2)
    assert second.admit(scope(ip="192.0.2.2")).allowed
    assert not first.admit(scope(ip="192.0.2.3")).allowed
    assert not second.admit(scope(ip="192.0.2.4")).allowed


def test_creation_limit_is_per_peer_and_only_post_collection(database: Path, clock: Clock) -> None:
    control = controller(database, clock, session_creation_limit=1)
    assert control.admit(scope("/api/v1/sessions", method="POST")).allowed
    assert not control.admit(scope("/api/v1/sessions/", method="POST")).allowed
    assert control.admit(scope("/api/v1/sessions", method="POST", ip="192.0.2.2")).allowed
    assert control.admit(scope("/api/v1/sessions", method="GET")).allowed
    assert control.admit(scope("/api/v1/sessions/unknown/action", method="POST")).allowed


@pytest.mark.parametrize("token", [None, "", "wrong", "秘密' OR 1=1; --"])
def test_unauthorized_requests_cannot_exhaust_victim_bucket(database: Path, clock: Clock,
                                                          token: str | None) -> None:
    path = session(database, clock)
    control = controller(database, clock, per_session_limit=1)
    for _ in range(3):
        assert control.admit(scope(path, token=token)).allowed
    assert all(row[0] != "session" for row in counters(database))
    assert control.admit(scope(path, token="secret", ip="192.0.2.2")).allowed
    assert not control.admit(scope(path, token="secret", ip="192.0.2.3")).allowed


@pytest.mark.parametrize("state", ["unknown", "deleted", "expired", "expires-now", "bad-expiry"])
def test_inactive_session_not_charged_but_global_and_ip_are(database: Path, clock: Clock,
                                                          state: str) -> None:
    path = "/api/v1/sessions/missing"
    if state != "unknown":
        expires = clock() if state == "expires-now" else clock() - 1 if state == "expired" else None
        path = session(database, clock, expires=expires, deleted=state == "deleted")
        if state == "bad-expiry":
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE sessions SET expires_at='invalid'")
    control = controller(database, clock, per_ip_limit=2, per_session_limit=1)
    assert control.admit(scope(path, token="secret")).allowed
    assert control.admit(scope(path, token="secret")).allowed
    assert not control.admit(scope(path, token="secret")).allowed
    assert {row[0] for row in counters(database)} == {"global", "ip"}


def test_session_is_shared_across_peers_but_other_sessions_are_independent(database: Path,
                                                                        clock: Clock) -> None:
    path = session(database, clock)
    other = session(database, clock, "other", "other-secret")
    control = controller(database, clock, per_session_limit=1)
    assert control.admit(scope(path, token="secret")).allowed
    assert not control.admit(scope(path + "/export", token="secret", ip="192.0.2.2")).allowed
    assert control.admit(scope(other, token="other-secret")).allowed


def test_forwarded_headers_are_not_trusted_and_missing_peer_is_bounded(database: Path,
                                                                     clock: Clock) -> None:
    control = controller(database, clock, per_ip_limit=1)
    assert control.admit(scope(extra_headers=((b"x-forwarded-for", b"192.0.2.8"),))).allowed
    assert not control.admit(scope(extra_headers=((b"x-forwarded-for", b"192.0.2.9"),))).allowed
    missing = {**scope(), "client": None}
    assert control.admit(missing).allowed
    assert not control.admit({**missing, "headers": [(b"forwarded", b"for=192.0.2.10")]}).allowed


def test_subjects_are_hashes_and_payloads_are_not_persisted(database: Path, clock: Clock) -> None:
    path = session(database, clock, "86ef0b90-5df0-4e27-ad4d-c2d8b09ff117", "capability-秘密")
    control = controller(database, clock)
    assert control.admit(scope(path, ip="192.0.2.44", token="capability-秘密")).allowed
    rows = counters(database)
    assert {row[0] for row in rows} == {"global", "ip", "session"}
    assert all(len(row[1]) == 64 and all(c in "0123456789abcdef" for c in row[1]) for row in rows)
    assert all(secret not in str(rows) for secret in ("192.0.2.44", "capability-秘密", "秘密-session"))


def test_fixed_window_boundary_retry_after_and_expiry_purge(database: Path, clock: Clock) -> None:
    control = controller(database, clock, window_seconds=10, per_ip_limit=1)
    assert control.admit(scope()).allowed
    clock.advance(9.1)
    assert control.admit(scope()).retry_after == 1
    clock.advance(0.9)
    assert control.admit(scope()).allowed
    assert len(counters(database)) == 2
    assert all(row[2] == int(clock()) for row in counters(database))


def test_monotonic_clock_prevents_backward_wall_clock_reset(database: Path, clock: Clock) -> None:
    monotonic = Clock(10)
    control = AdmissionController(database, window_seconds=10, per_ip_limit=1,
                                  wall_clock=clock, monotonic_clock=monotonic)
    assert control.admit(scope()).allowed
    clock.advance(-3600)
    assert not control.admit(scope()).allowed
    monotonic.advance(10)
    assert control.admit(scope()).allowed


def test_observed_forward_wall_jump_cannot_be_rolled_back_to_reset_limits(database: Path,
                                                                       clock: Clock) -> None:
    monotonic = Clock(10)
    control = AdmissionController(database, window_seconds=10, per_ip_limit=1,
                                  wall_clock=clock, monotonic_clock=monotonic)
    assert control.admit(scope()).allowed
    clock.advance(30)
    assert control.admit(scope()).allowed
    clock.advance(-30)
    assert not control.admit(scope()).allowed


@pytest.mark.parametrize("bucket", ["global", "ip", "creation", "session"])
def test_atomic_concurrency_no_overflow_across_independent_controllers(database: Path,
                                                                    clock: Clock,
                                                                    bucket: str) -> None:
    setting = {"global": "global_limit", "ip": "per_ip_limit",
               "creation": "session_creation_limit", "session": "per_session_limit"}[bucket]
    controls = [controller(database, clock, **{setting: 17}) for _ in range(4)]
    path = session(database, clock) if bucket == "session" else "/api/v1/sessions"
    def attempt(index: int) -> bool:
        peer = f"192.0.2.{index}" if bucket in ("global", "session") else "192.0.2.1"
        request = scope(path, method="POST", ip=peer,
                        token="secret" if bucket == "session" else None)
        return controls[index % 4].admit(request).allowed
    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(attempt, range(80)))
    assert sum(accepted) == 17
    rows = counters(database)
    assert next(row[3] for row in rows if row[0] == "global") == 17
    assert sum(row[3] for row in rows if row[0] == "ip") == 17
    assert all(row[3] <= 17 for row in rows)


def test_purge_removes_large_old_counter_population(database: Path, clock: Clock) -> None:
    with sqlite3.connect(database) as conn:
        conn.executemany("INSERT INTO admission_counters VALUES ('ip', ?, ?, 1)",
                         ((hashlib.sha256(str(i).encode()).hexdigest(), int(clock()) - 60)
                          for i in range(10_001)))
    assert controller(database, clock).admit(scope()).allowed
    assert len(counters(database)) == 2


@pytest.mark.parametrize("setting,value", [("window_seconds", 0), ("per_ip_limit", -1),
    ("per_session_limit", None), ("global_limit", "3"), ("session_creation_limit", True),
    ("max_inflight", 0), ("window_seconds", 1.5)])
def test_invalid_configuration_fails_fast(database: Path, setting: str, value: Any) -> None:
    with pytest.raises(ValueError):
        AdmissionController(database, **{setting: value})


def test_controller_construction_does_not_run_migrations(tmp_path: Path, clock: Clock) -> None:
    database = tmp_path / "after-startup.db"
    control = controller(database, clock)
    assert not database.exists()
    apply_migrations(database)
    assert control.admit(scope()).allowed


async def echo_app(request: dict, receive: Any, send: Any) -> None:
    if request["type"] == "lifespan":
        while True:
            message = await receive()
            await send({"type": message["type"] + ".complete"})
            if message["type"] == "lifespan.shutdown":
                return
    elif request["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    else:
        assert (await receive())["type"] == "websocket.connect"
        await send({"type": "websocket.accept"})
        message = await receive()
        if message["type"] == "websocket.disconnect":
            return
        await send({"type": "websocket.send", "text": message.get("text", "binary")})
        await send({"type": "websocket.close", "code": 1000})


def test_http_rate_error_contract_all_api_paths_and_non_api_bypass(database: Path, clock: Clock) -> None:
    control = controller(database, clock, global_limit=1)
    with TestClient(AdmissionMiddleware(echo_app, control)) as client:
        assert client.get("/api/v1/health").status_code == 200
        denied = client.post("/api/v1/anything/new", content="private request")
        assert denied.status_code == 429
        assert denied.headers["retry-after"] == "60"
        assert denied.json()["code"] == "RATE_LIMITED"
        assert denied.json()["retryable"] is True
        assert set(denied.json()) == {"code", "message", "request_id", "retryable", "turn_id", "job_id"}
        assert "private request" not in denied.text
        assert client.get("/health").status_code == 200
        assert client.get("/api/v10/not-covered").status_code == 200
        assert client.get("/api/v1").status_code == 429


def test_asgi_lifespan_initializes_database_after_controller_construction(tmp_path: Path, clock: Clock) -> None:
    database = tmp_path / "lifespan.db"
    async def startup_app(request: dict, receive: Any, send: Any) -> None:
        if request["type"] == "lifespan":
            apply_migrations(database)
        await echo_app(request, receive, send)
    with TestClient(AdmissionMiddleware(startup_app, controller(database, clock))) as client:
        assert client.get("/api/v1/meta").status_code == 200


def test_websocket_rate_denied_before_accept(database: Path, clock: Clock) -> None:
    control = controller(database, clock, global_limit=1)
    with TestClient(AdmissionMiddleware(echo_app, control)) as client:
        assert client.get("/api/v1/meta").status_code == 200
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/v1/speech/ws"):
                pytest.fail("Rate-limited connection was accepted")
        assert exc.value.code == 4429


def test_websocket_first_frame_session_capability_accounting(database: Path, clock: Clock) -> None:
    path = session(database, clock)
    control = controller(database, clock, per_session_limit=1)
    with TestClient(AdmissionMiddleware(echo_app, control)) as client:
        for token in ("wrong", "secret"):
            opening = json.dumps({"token": token, "revision": {"code_version_id": 1}})
            with client.websocket_connect(path + "/speech/ws") as ws:
                ws.send_text(opening)
                assert ws.receive_text() == opening
        from starlette.websockets import WebSocketDisconnect
        with client.websocket_connect(path + "/speech/ws") as ws:
            ws.send_json({"token": "secret"})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 4429
    rows = counters(database)
    assert next(row[3] for row in rows if row[0] == "session") == 1
    assert next(row[3] for row in rows if row[0] == "global") == 3


@pytest.mark.parametrize("opening", ["invalid-json", "[]", "null", '{"token": null}',
    '{"token": 42}', "x" * 8193, '{"unrelated": "value"}', '{"token": "\\ud800"}'])
def test_websocket_invalid_opening_is_passed_through_without_session_charge(database: Path,
                                                                          clock: Clock,
                                                                          opening: str) -> None:
    path = session(database, clock)
    with TestClient(AdmissionMiddleware(echo_app, controller(database, clock))) as client:
        with client.websocket_connect(path + "/speech/ws") as ws:
            ws.send_text(opening)
            assert ws.receive_text() == opening
    assert all(row[0] != "session" for row in counters(database))


def test_websocket_header_auth_not_counted_twice(database: Path, clock: Clock) -> None:
    path = session(database, clock)
    with TestClient(AdmissionMiddleware(echo_app, controller(database, clock, per_session_limit=1))) as client:
        with client.websocket_connect(path + "/speech/ws", headers={"authorization": "Bearer secret"}) as ws:
            ws.send_json({"token": "secret"})
            assert json.loads(ws.receive_text()) == {"token": "secret"}
    assert next(row[3] for row in counters(database) if row[0] == "session") == 1


@pytest.mark.parametrize("kind", ["http", "websocket"])
@pytest.mark.parametrize("exit_mode", ["normal", "error", "cancel"])
def test_capacity_rejects_immediately_and_releases_on_all_exit_paths(database: Path, clock: Clock,
                                                                  kind: str, exit_mode: str) -> None:
    async def exercise() -> None:
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = 0
        async def blocking_app(request: dict, receive: Any, send: Any) -> None:
            nonlocal calls
            calls += 1
            entered.set()
            await finish.wait()
            if exit_mode == "error":
                raise RuntimeError("downstream error")
        control = controller(database, clock, max_inflight=1)
        app = AdmissionMiddleware(blocking_app, control)
        messages: list[dict] = []
        async def receive() -> dict:
            return {"type": "http.disconnect" if kind == "http" else "websocket.disconnect"}
        async def send(message: dict) -> None:
            messages.append(message)
        active = asyncio.create_task(app(scope(kind=kind), receive, send))
        await asyncio.wait_for(entered.wait(), timeout=2)
        before = counters(database)
        await asyncio.wait_for(app(scope(kind=kind), receive, send), timeout=0.5)
        assert calls == 1
        assert counters(database) == before
        if kind == "http":
            assert messages[0]["status"] == 503
            assert json.loads(messages[1]["body"])["code"] == "QUEUE_FULL"
        else:
            assert messages == [{"type": "websocket.close", "code": 1013, "reason": "QUEUE_FULL"}]
        if exit_mode == "cancel":
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
        else:
            finish.set()
            if exit_mode == "error":
                with pytest.raises(RuntimeError, match="downstream error"):
                    await active
            else:
                await active
        assert control.try_acquire()
        control.release()
    asyncio.run(exercise())


def test_websocket_frames_after_opening_remain_unchanged_and_denied_sends_are_suppressed(
    database: Path, clock: Clock,
) -> None:
    path = session(database, clock)
    control = controller(database, clock, per_session_limit=1)
    async def stream_app(request: dict, receive: Any, send: Any) -> None:
        if request["type"] != "websocket":
            await echo_app(request, receive, send)
            return
        await receive()
        await send({"type": "websocket.accept"})
        opening = await receive()
        if opening["type"] == "websocket.disconnect":
            assert (await receive())["type"] == "websocket.disconnect"
            await send({"type": "websocket.send", "text": "must not be delivered"})
            await send({"type": "websocket.close", "code": 1000})
            return
        await send({"type": "websocket.send", "text": opening["text"]})
        binary = await receive()
        await send({"type": "websocket.send", "bytes": binary["bytes"]})
        await send({"type": "websocket.close", "code": 1000})
    with TestClient(AdmissionMiddleware(stream_app, control)) as client:
        with client.websocket_connect(path + "/speech/ws") as ws:
            ws.send_json({"token": "secret"})
            assert json.loads(ws.receive_text()) == {"token": "secret"}
            ws.send_bytes(b"\\x00\\x01")
            assert ws.receive_bytes() == b"\\x00\\x01"
        with client.websocket_connect(path + "/speech/ws") as ws:
            ws.send_json({"token": "secret"})
            assert ws.receive() == {"type": "websocket.close", "code": 4429, "reason": "RATE_LIMITED"}
    assert next(row[3] for row in counters(database) if row[0] == "session") == 1


def test_concurrent_capacity_reservations_never_exceed_bound(database: Path, clock: Clock) -> None:
    control = controller(database, clock, max_inflight=7)
    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(lambda _: control.try_acquire(), range(100)))
    assert sum(accepted) == 7
    assert not control.try_acquire()
    for _ in range(7):
        control.release()
    assert control.try_acquire()
    control.release()


def test_release_without_slot_fails_without_increasing_capacity(database: Path, clock: Clock) -> None:
    control = controller(database, clock, max_inflight=1)
    with pytest.raises(RuntimeError):
        control.release()
    assert control.try_acquire()
    assert not control.try_acquire()
    control.release()


def test_database_write_error_rolls_back_all_buckets(database: Path, clock: Clock) -> None:
    control = controller(database, clock)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TRIGGER fail_ip BEFORE INSERT ON admission_counters "
                     "WHEN NEW.bucket='ip' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        control.admit(scope())
    assert counters(database) == []


def test_rate_denial_releases_capacity(database: Path, clock: Clock) -> None:
    control = controller(database, clock, global_limit=1, max_inflight=1)
    with TestClient(AdmissionMiddleware(echo_app, control)) as client:
        assert client.get("/api/v1/meta").status_code == 200
        assert client.get("/api/v1/meta").status_code == 429
        clock.advance(60)
        assert client.get("/api/v1/meta").status_code == 200


def test_database_error_fails_closed_without_leaks_and_releases_capacity(database: Path, clock: Clock) -> None:
    control = controller(database, clock, max_inflight=1)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE admission_counters")
    with TestClient(AdmissionMiddleware(echo_app, control)) as client:
        response = client.get("/api/v1/meta")
        assert response.status_code == 503
        assert response.json()["code"] == "ADMISSION_UNAVAILABLE"
        assert str(database) not in response.text
        assert "admission_counters" not in response.text
    assert control.try_acquire()
    control.release()
