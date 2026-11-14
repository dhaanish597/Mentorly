"""Local operational regressions; no learner execution or provider calls."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import os
import sqlite3
from uuid import uuid4

import pytest

from backend.app.db.repository import SQLiteRepository
from backend.app.models.api_schemas import TTSAudioConfig
from backend.app.operations.backup import create_verified_backup, restore_verified_backup, verify_database
from backend.app.operations.retention import RetentionService
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.service import SpeechService
from backend.app.speech.tts_cache import TTSDiskCache


def make_session(repo, *, expired=False):
    sid = str(uuid4())
    source = "def first_at_least(nums, target):\n    return -1\n"
    repo.create_session(
        session_id=sid, token_hash=hashlib.sha256(sid.encode()).hexdigest(),
        exercise_id="ex2_binary_search", spec_version="v1_sorted_with_duplicates",
        language_mode="en-IN", interaction_mode="TEXT", starter_code=source,
        starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)).isoformat(),
    )
    return sid


def put_audio(cache, sid, key="a"*64):
    wav = generate_sine_wav_bytes(duration_sec=0.05, sample_rate_hz=16000)
    cache.put_completed_stream(key, wav, stream_completed=True,
        audio_config=TTSAudioConfig(container="wav", sample_rate=16000), session_id=sid)
    return wav


def test_retention_removes_expired_private_data_without_touching_active_session(tmp_path):
    async def scenario():
        repo = SQLiteRepository(tmp_path / "sessions.db")
        repo.initialize()
        expired, active = make_session(repo, expired=True), make_session(repo)
        speech = SpeechService(db_path=repo.db_path, cache_dir=tmp_path / "tts")
        try:
            put_audio(speech.cache, expired)
            put_audio(speech.cache, active)
            result = await RetentionService(repo, speech).run_once()
            assert result.expired_sessions == 1
            assert result.pending_audio_cancellations == 0
            assert repo.get_session(expired, include_deleted=True).deleted_at is not None
            assert repo.get_code_version(expired, 1) is None
            assert speech.cache.get_wav("a"*64, session_id=expired) is None
            assert repo.get_code_version(active, 1) is not None
            assert speech.cache.get_wav("a"*64, session_id=active) is not None
            assert (await RetentionService(repo, speech).run_once()).expired_sessions == 0
        finally:
            await speech.aclose()
    asyncio.run(scenario())


def test_retention_waits_for_cancelled_audio_before_final_cache_eviction(tmp_path):
    async def scenario():
        repo = SQLiteRepository(tmp_path / "race.db")
        repo.initialize()
        sid = make_session(repo, expired=True)
        speech = SpeechService(db_path=repo.db_path, cache_dir=tmp_path / "tts")
        started = asyncio.Event()
        async def delayed_cache_writer():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                put_audio(speech.cache, sid)
        task = asyncio.create_task(delayed_cache_writer())
        speech._tasks[(sid, 0)] = {task}
        try:
            await started.wait()
            report = await RetentionService(repo, speech).run_once()
            assert task.done()
            assert report.pending_audio_cancellations == 0
            assert speech.cache.get_wav("a"*64, session_id=sid) is None
        finally:
            await speech.aclose()
    asyncio.run(scenario())


def test_http_delete_tombstones_then_waits_for_audio_before_eviction(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.core.config import Settings
    from backend.app.main import create_app
    settings = Settings(_env_file=None, database_path=tmp_path / "delete.db", tts_cache_dir=tmp_path / "tts")
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/v1/sessions", json={"exercise_id":"ex2_binary_search", "spec_version":"v1_sorted_with_duplicates"}).json()
        sid = created["session_id"]
        speech = client.app.state.speech
        barrier_called = []
        async def barrier(session_id, generation, **kwargs):
            assert SQLiteRepository(settings.database_path).get_session(session_id, include_deleted=True).deleted_at is not None
            put_audio(speech.cache, session_id)
            barrier_called.append(session_id)
            return 0
        speech.cancel_session = barrier
        response = client.delete("/api/v1/sessions/" + sid, headers={"Authorization":"Bearer " + created["session_token"], "X-Idempotency-Key":str(uuid4())})
        assert response.status_code == 200
        assert barrier_called == [sid]
        assert speech.cache.get_wav("a"*64, session_id=sid) is None


def test_operator_readiness_is_protected_and_never_bypasses_isolation(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.core.config import Settings
    from backend.app.main import create_app
    token = "test-operator-capability-" + "x"*40
    settings = Settings(_env_file=None, database_path=tmp_path / "readiness.db", tts_cache_dir=tmp_path / "tts", operations_token=token)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/ops/readiness").status_code == 403
        assert client.get("/api/v1/ops/readiness", params={"token":token}).status_code == 403
        response = client.get("/api/v1/ops/readiness", headers={"Authorization":"Bearer " + token})
        assert response.status_code == 200
        data = response.json()
        assert data["database_ready"] is True
        assert data["execution_ready"] is False
        assert data["canary_status"] == "NOT_RUN"
        assert data["status"] == "BLOCKED_EXTERNAL"
        assert token not in response.text


def test_pending_cleanup_survives_service_restart(tmp_path):
    async def scenario():
        repo = SQLiteRepository(tmp_path / "restart.db")
        repo.initialize()
        sid = make_session(repo, expired=True)
        speech = SpeechService(db_path=repo.db_path, cache_dir=tmp_path / "tts")
        put_audio(speech.cache, sid)
        async def pending(*args, **kwargs):
            return 1
        speech.cancel_session = pending
        first = await RetentionService(repo, speech).run_once()
        assert first.pending_audio_cancellations > 0
        assert speech.cache.get_wav("a"*64, session_id=sid) is not None
        await speech.aclose()
        fresh = SpeechService(db_path=repo.db_path, cache_dir=tmp_path / "tts")
        try:
            await RetentionService(repo, fresh).run_once()
            assert fresh.cache.get_wav("a"*64, session_id=sid) is None
        finally:
            await fresh.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_restore_preserves_existing_destination_sidecars(tmp_path, suffix):
    repo = SQLiteRepository(tmp_path / "source.sqlite3")
    repo.initialize()
    destination = tmp_path / "new.sqlite3"
    sidecar = destination.with_name(destination.name + suffix)
    sidecar.write_bytes(b"preserve this sidecar")
    with pytest.raises(FileExistsError):
        restore_verified_backup(repo.db_path, destination)
    assert not destination.exists()
    assert sidecar.read_bytes() == b"preserve this sidecar"


def test_backup_rejects_shared_writable_destination_directory(tmp_path):
    repo = SQLiteRepository(tmp_path / "source.sqlite3")
    repo.initialize()
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    with pytest.raises(ValueError, match="private"):
        create_verified_backup(repo.db_path, shared / "backup.sqlite3")
    assert list(shared.iterdir()) == []


def test_broker_cleanup_identity_survives_restart(tmp_path):
    async def scenario():
        from backend.app.orchestration.state_machine import CoordinatorStateMachine
        repo = SQLiteRepository(tmp_path / "broker-restart.db")
        repo.initialize()
        sid = make_session(repo, expired=True)
        revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
        job_id = str(uuid4())
        repo.register_execution_job(sid, job_id, "VERIFY", revision, None)
        speech = SpeechService(db_path=repo.db_path, cache_dir=tmp_path / "tts")
        try:
            await RetentionService(repo, speech).run_once()
            class Broker:
                def __init__(self): self.calls = []
                def cancel(self, job): self.calls.append(str(job)); return True
            broker = Broker()
            await RetentionService(repo, speech, worker_client=broker).run_once()
            assert broker.calls == [job_id]
            with sqlite3.connect(repo.db_path) as conn:
                assert conn.execute("SELECT count(*) FROM cleanup_obligations WHERE session_id=?", (sid,)).fetchone()[0] == 0
        finally:
            await speech.aclose()
    asyncio.run(scenario())


def test_cleanup_completion_preserves_jobs_captured_after_cancellation_snapshot(tmp_path):
    from backend.app.orchestration.state_machine import CoordinatorStateMachine
    repo = SQLiteRepository(tmp_path / "cleanup-race.db")
    repo.initialize()
    sid = make_session(repo)
    revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
    first, late = str(uuid4()), str(uuid4())
    repo.register_execution_job(sid, first, "VERIFY", revision, None)
    repo.request_execution_cancellation(sid)
    repo.register_execution_job(sid, late, "VERIFY", revision, None)
    repo.tombstone_session(sid)
    speech = SpeechService(db_path=repo.db_path, cache_dir=tmp_path / "tts")
    try:
        RetentionService(repo, speech).record_cleanup(sid, audio_pending=False, confirmed_jobs=[first])
        with sqlite3.connect(repo.db_path) as conn:
            row = conn.execute("SELECT pending_jobs_json FROM cleanup_obligations WHERE session_id=?", (sid,)).fetchone()
        import json
        assert json.loads(row[0]) == [late]
    finally:
        speech.close()


def test_backup_rejects_symlink_and_relative_paths_through_unsafe_ancestry(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "source.sqlite3")
    repo.initialize()
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    private = unsafe / "private"
    private.mkdir(mode=0o700)
    link = tmp_path / "trusted-link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError, match="private"):
        create_verified_backup(repo.db_path, link / "backup.sqlite3")
    monkeypatch.chdir(private)
    with pytest.raises(ValueError, match="private"):
        create_verified_backup(repo.db_path, "relative.sqlite3")
    assert list(private.iterdir()) == []


def test_backup_uses_the_validated_resolution_without_resolving_again(tmp_path, monkeypatch):
    from pathlib import Path
    repo = SQLiteRepository(tmp_path / "source.sqlite3")
    repo.initialize()
    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    unsafe_parent = tmp_path / "unsafe-parent"
    unsafe_parent.mkdir()
    unsafe_parent.chmod(0o777)
    unsafe = unsafe_parent / "private"
    unsafe.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(safe, target_is_directory=True)
    original = Path.resolve
    calls = []
    def changing_resolution(path, *args, **kwargs):
        if path == link:
            calls.append(path)
            if len(calls) > 1:
                return unsafe
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", changing_resolution)
    create_verified_backup(repo.db_path, link / "backup.sqlite3")
    assert (safe / "backup.sqlite3").is_file()
    assert list(unsafe.iterdir()) == []


def test_cache_enforces_total_bytes_and_ttl(tmp_path):
    wav = generate_sine_wav_bytes(duration_sec=0.05, sample_rate_hz=16000)
    cache = TTSDiskCache(tmp_path / "tts", max_bytes=len(wav)*2, max_age_seconds=60)
    for letter in "abc":
        put_audio(cache, "session", letter*64)
    assert sum(p.stat().st_size for p in cache.cache_root.rglob("*.wav")) <= len(wav)*2
    path = cache._target_path("c"*64, session_id="session")
    os.utime(path, (1, 1))
    assert cache.get_wav("c"*64, session_id="session") is None
    assert not path.exists()


def test_oversized_audio_is_delivered_without_persisting_over_cache_cap(tmp_path):
    cache = TTSDiskCache(tmp_path / "tts", max_bytes=32, max_age_seconds=60)
    wav = put_audio(cache, "session")
    assert wav
    assert list(cache.cache_root.rglob("*.wav")) == []


def test_verified_online_backup_and_restore_preserve_migrations_and_data(tmp_path):
    repo = SQLiteRepository(tmp_path / "live.db")
    repo.initialize()
    sid = make_session(repo)
    backup = tmp_path / "backup.sqlite3"
    report = create_verified_backup(repo.db_path, backup)
    assert report.sha256 == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert backup.stat().st_mode & 0o777 == 0o600
    restored = tmp_path / "restored.sqlite3"
    restore_verified_backup(backup, restored)
    assert verify_database(restored).integrity_ok
    assert SQLiteRepository(restored).get_code_version(sid, 1).source_code == repo.get_code_version(sid, 1).source_code


def test_backup_and_restore_never_overwrite_existing_files(tmp_path):
    repo = SQLiteRepository(tmp_path / "live.db")
    repo.initialize()
    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"preserved")
    with pytest.raises(FileExistsError):
        create_verified_backup(repo.db_path, target)
    assert target.read_bytes() == b"preserved"
    backup = tmp_path / "valid.sqlite3"
    create_verified_backup(repo.db_path, backup)
    with pytest.raises(FileExistsError):
        restore_verified_backup(backup, target)
    assert target.read_bytes() == b"preserved"


def test_restore_rejects_corrupt_or_migration_drifted_backup(tmp_path):
    corrupt = tmp_path / "bad.sqlite3"
    corrupt.write_bytes(b"not a database")
    destination = tmp_path / "never-promoted.sqlite3"
    with pytest.raises(ValueError):
        restore_verified_backup(corrupt, destination)
    assert not destination.exists()
    repo = SQLiteRepository(tmp_path / "drift.sqlite3")
    repo.initialize()
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE schema_migrations SET checksum=? WHERE version='0001'", ("0"*64,))
    with pytest.raises(ValueError, match="migration"):
        restore_verified_backup(repo.db_path, destination)
    assert not destination.exists()
