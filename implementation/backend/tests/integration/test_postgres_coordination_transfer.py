"""Real PostgreSQL fenced dispatch, scheduled maintenance and transfer validation."""

import asyncio
import json
import sqlite3
import uuid
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing

import pytest
from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.db.postgres.account_dispatch import (
    AccountDispatcher,
    DispatchUnavailable,
)
from backend.app.db.postgres.maintenance import (
    claim,
    maintenance_fence,
    release,
    run_once,
)
from backend.app.db.postgres.transfer import (
    TransferError,
    export_sqlite,
    import_postgres,
    load_snapshot,
)
from backend.app.main import create_app
from backend.tests.integration.test_postgres_runtime import _workspace
from backend.tests.integration.test_postgres_runtime import runtime as runtime  # noqa: PLC0414 - pytest fixture re-export
from fastapi.testclient import TestClient


def _process_reserve(dsn, schema, key):
    from backend.app.db.postgres.runtime import PostgresTarget

    dispatcher = AccountDispatcher(
        PostgresTarget(dsn, schema), account_key=key, capacity=1
    )
    lease = dispatcher.reserve()
    return None if lease is None else (lease.id, lease.fence)


def test_real_two_process_account_cap_and_unknown_lifetime(runtime):
    _, target = runtime
    key = "synthetic-account-" + uuid.uuid4().hex
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_process_reserve, target.dsn, target.schema, key)
            for _ in range(2)
        ]
        results = [f.result() for f in futures]
    assert sum(r is not None for r in results) == 1
    from backend.app.db.postgres.account_dispatch import Lease

    result = next(r for r in results if r is not None)
    lease = Lease(*result)
    dispatcher = AccountDispatcher(target, account_key=key, capacity=1)
    dispatcher.start(lease)
    with target.connect() as conn:
        conn.execute(
            "UPDATE viva_provider_coordination.leases SET expires_at=clock_timestamp()-interval '1 hour' WHERE id=%s",
            (lease.id,),
        )
    assert dispatcher.reserve() is None, (
        "A dispatched lease cannot be freed by TTL alone"
    )
    dispatcher.finish(lease, uncertain=True)
    assert dispatcher.reserve() is None
    dispatcher.finish(lease)  # positive observed completion/quiescence, matching fence
    assert dispatcher.reserve() is not None


def test_expired_undispatched_lease_is_fenced_and_recoverable(runtime):
    _, target = runtime
    dispatcher = AccountDispatcher(
        target, account_key="synthetic-" + uuid.uuid4().hex, capacity=1
    )
    old = dispatcher.reserve()
    with target.connect() as conn:
        conn.execute(
            "UPDATE viva_provider_coordination.leases SET expires_at=clock_timestamp()-interval '1 hour' WHERE id=%s",
            (old.id,),
        )
    current = dispatcher.reserve()
    assert current is not None and current.fence > old.fence
    with pytest.raises(DispatchUnavailable):
        dispatcher.start(old)
    dispatcher.finish(current)


def test_capacity_agreement_and_tested_higher_cap(runtime):
    _, target = runtime
    key = "synthetic-" + uuid.uuid4().hex
    dispatcher = AccountDispatcher(target, account_key=key, capacity=2)
    assert dispatcher.reserve() is not None and dispatcher.reserve() is not None
    assert dispatcher.reserve() is None
    with pytest.raises(DispatchUnavailable):
        AccountDispatcher(target, account_key=key, capacity=3)


def test_quiescent_capacity_change_fences_previous_configuration(runtime):
    _, target = runtime
    key = "synthetic-" + uuid.uuid4().hex
    operator = AccountDispatcher(target, account_key=key, capacity=1)
    stale_worker = AccountDispatcher(target, account_key=key, capacity=1)
    lease = operator.reserve()
    with pytest.raises(DispatchUnavailable, match="active or uncertain"):
        operator.reconfigure_capacity(2)
    operator.start(lease)
    operator.finish(lease, uncertain=True)
    with pytest.raises(DispatchUnavailable, match="active or uncertain"):
        operator.reconfigure_capacity(2)
    operator.finish(lease)
    operator.reconfigure_capacity(2)
    with pytest.raises(DispatchUnavailable, match="differs"):
        stale_worker.reserve()
    current = AccountDispatcher(target, account_key=key, capacity=2)
    assert current.reserve() is not None and current.reserve() is not None
    assert current.reserve() is None


def test_expired_maintenance_owner_cannot_write_after_new_claim(runtime):
    _, target = runtime
    old = claim(target)
    assert old is not None and claim(target) is None
    with target.connect() as conn:
        conn.execute(
            "UPDATE runtime_maintenance_owner SET expires_at=clock_timestamp()-interval '1 hour'"
        )
    fresh = claim(target)
    assert fresh.generation > old.generation
    token = maintenance_fence.set(old)
    try:
        with (
            closing(open_connection(target)) as conn,
            pytest.raises(sqlite3.OperationalError, match="superseded"),
        ):
            conn.execute("BEGIN IMMEDIATE")
    finally:
        maintenance_fence.reset(token)
    release(target, old)
    assert claim(target) is None, "Old completion cannot release a new owner"
    release(target, fresh)


def test_scheduled_maintenance_expiry_without_asgi_background_loop(runtime):
    client, target = runtime
    assert client.app.state.retention._task is None
    wid, _, _ = _workspace(client)
    with open_connection(target) as conn:
        conn.execute(
            "UPDATE studio_workspaces SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (wid,),
        )
    report = asyncio.run(run_once(client.app))
    assert report["status"] == "COMPLETE"
    with open_connection(target) as conn:
        assert (
            conn.execute(
                "SELECT deleted_at FROM studio_workspaces WHERE id=?", (wid,)
            ).fetchone()[0]
            is not None
        )


def test_private_export_import_reconcile_replay_and_conflict_preservation(
    runtime, tmp_path
):
    client, target = runtime
    source = tmp_path / "source.sqlite3"
    snapshot = tmp_path / "backup.json"
    settings = Settings(
        _env_file=None,
        database_path=source,
        database_url=None,
        tts_cache_dir=tmp_path / "source-audio",
        gnani_api_key=None,
        groq_api_key=None,
        env="test",
        retention_interval_seconds=86400,
    )
    with TestClient(create_app(settings)) as original:
        wid, token, headers = _workspace(original)
        lesson = original.post(
            "/api/v1/learning/sessions",
            headers=headers,
            json={
                "lesson_id": "dsa-complexity",
                "mode": "practice",
                "language_mode": "en-IN",
            },
        ).json()
        response = original.post(
            f"/api/v1/learning/sessions/{lesson['id']}/answers",
            headers=headers,
            json={
                "expected_epoch": lesson["epoch"],
                "question_id": lesson["question"]["id"],
                "answer": "O(n)",
            },
        )
        assert response.status_code == 200
    exported = export_sqlite(source, snapshot)
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert token not in snapshot.read_text()
    imported = import_postgres(target, snapshot)
    assert (
        imported["status"] == "IMPORTED"
        and imported["content_hash"] == exported["content_hash"]
    )
    assert import_postgres(target, snapshot)["status"] == "ALREADY_IMPORTED"
    result = client.get("/api/v1/learning/progress", headers=headers)
    assert result.status_code == 200 and result.json()["lessons_completed"] == 1
    with open_connection(target) as conn:
        conn.execute(
            "UPDATE studio_workspaces SET expires_at=? WHERE id=?",
            ("2099-01-01T00:00:00+00:00", wid),
        )
    with pytest.raises(TransferError, match="reconciliation"):
        import_postgres(target, snapshot)
    with open_connection(target) as conn:
        assert (
            conn.execute("SELECT expires_at FROM studio_workspaces WHERE id=?", (wid,))
            .fetchone()[0]
            .startswith("2099")
        )
    corrupted = json.loads(snapshot.read_text())
    corrupted["tables"]["studio_workspaces"]["rows"][0][0] = "malicious"
    damaged = tmp_path / "damaged.json"
    damaged.write_text(json.dumps(corrupted))
    with pytest.raises(TransferError, match="integrity"):
        load_snapshot(damaged)


def test_rejected_private_import_rolls_back_and_redacts_driver_details(
    runtime, tmp_path
):
    _, target = runtime
    from backend.app.db.postgres.transfer import _canonical, _rows_hash

    source = tmp_path / "source.sqlite3"
    snapshot = tmp_path / "snapshot.json"
    settings = Settings(
        _env_file=None,
        database_path=source,
        database_url=None,
        tts_cache_dir=tmp_path / "audio",
        gnani_api_key=None,
        groq_api_key=None,
        env="test",
    )
    with TestClient(create_app(settings)) as original:
        _workspace(original)
    export_sqlite(source, snapshot)
    payload = json.loads(snapshot.read_text())
    table = payload["tables"]["studio_workspaces"]
    table["rows"][0][table["columns"].index("id")] = "private-learner-identity"
    table["rows"][0][table["columns"].index("expires_at")] = None
    table["hash"] = _rows_hash(table["rows"])
    import hashlib

    payload["content_hash"] = hashlib.sha256(
        _canonical({k: v for k, v in payload.items() if k != "content_hash"})
    ).hexdigest()
    snapshot.write_bytes(_canonical(payload))
    with pytest.raises(TransferError) as rejected:
        import_postgres(target, snapshot)
    assert "private-learner-identity" not in str(rejected.value)
    assert "rolled back" in str(rejected.value)
    with open_connection(target) as conn:
        assert conn.execute("SELECT count(*) FROM studio_workspaces").fetchone()[0] == 0
        assert (
            conn.execute("SELECT count(*) FROM runtime_transfer_history").fetchone()[0]
            == 0
        )


def test_scheduled_import_crash_recovery_fences_late_parser_publication(
    runtime, monkeypatch
):
    client, target = runtime
    from backend.app.db.postgres.maintenance import recover_stale_imports
    from backend.app.repo_learning import service

    wid, _, _ = _workspace(client)
    snapshot_id = service.queue(target, wid, "zip_upload")
    with open_connection(target) as conn:
        conn.execute(
            "UPDATE repo_snapshots SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (snapshot_id,),
        )
    fence = claim(target)
    original_structure = service.structure

    def paused_parser(*args):
        token = maintenance_fence.set(fence)
        try:
            assert recover_stale_imports(target) == 1
        finally:
            maintenance_fence.reset(token)
        return original_structure(*args)

    monkeypatch.setattr(service, "structure", paused_parser)
    try:
        with pytest.raises(ValueError, match="cancelled"):
            service.create(
                target,
                wid,
                "zip_upload",
                {"main.py": "def run():\n    return 1\n"},
                {"total": 1, "skipped": 0},
                snapshot_id,
            )
    finally:
        release(target, fence)
    with open_connection(target) as conn:
        row = conn.execute(
            "SELECT status,failure_code FROM repo_snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        assert tuple(row) == ("FAILED", "INTERRUPTED")
        assert (
            conn.execute(
                "SELECT count(*) FROM repo_files WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM repo_chunks WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()[0]
            == 0
        )
    assert asyncio.run(run_once(client.app))["recovered_imports"] == 0
