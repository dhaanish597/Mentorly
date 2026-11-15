"""Cloud wiring acceptance against a disposable local PostgreSQL cluster.

No external credentials, provider requests or cloud mutations are used.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import shutil
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.db.postgres.runtime import PostgresTarget, _raw_connection
from backend.app.db.postgres import cloud
from backend.app.db.repository import SQLiteRepository
from backend.app.speech.service import SpeechService
from backend.app.speech.gatekeeper import SpeechBusyError
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.operations.admission import AdmissionController
from backend.app.operations.readiness import _database_ready
from backend.app.models.api_schemas import STTRequest
from backend.app.speech.gnani_adapter import GnaniTransportError
from backend.app.speech.audio_utils import wrap_raw_pcm_as_wav

DSN = os.environ.get('VIVA_POSTGRES_RUNTIME_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='set VIVA_POSTGRES_RUNTIME_TEST_DSN to a disposable local cluster')


@pytest.fixture
def target():
    psycopg = pytest.importorskip('psycopg')
    host = psycopg.conninfo.conninfo_to_dict(DSN).get('host', '')
    assert host.startswith('/') or host in ('localhost', '127.0.0.1', '::1')
    value = PostgresTarget(DSN, schema='viva_cloud_test_' + uuid.uuid4().hex, allow_local=True)
    try:
        apply_migrations(value)
        yield value
    finally:
        with _raw_connection(value) as conn:
            conn.execute(psycopg.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(psycopg.sql.Identifier(value.schema)))


def session(target):
    repo = SQLiteRepository(target)
    sid = str(uuid.uuid4())
    source = 'def shortest_subarray_ge_target(nums, target):\n    return 0\n'
    repo.create_session(session_id=sid, token_hash=sid, exercise_id='ex1_shortest_subarray',
        spec_version='v1_positive_only', language_mode='en-IN', interaction_mode='TEXT',
        starter_code=source, starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    return repo, sid


def service(target, tmp_path):
    return SpeechService(db_path=target, cache_dir=tmp_path / 'must-not-create-local-audio',
                         settings=Settings(env='test', gnani_api_key=None, groq_api_key=None))


def test_shared_admission_capacity_and_crash_expiry(target):
    first, second = AdmissionController(target, max_inflight=1), AdmissionController(target, max_inflight=1)
    lease = first.try_acquire()
    assert lease is not None and second.try_acquire() is None
    with pytest.raises(RuntimeError, match='owned'):
        second.release(lease)
    first.release(lease)
    abandoned = first.try_acquire()
    with closing(open_connection(target)) as conn:
        conn.execute('UPDATE cloud_leases SET expires_at=0 WHERE id=?', (abandoned.id,))
    recovered = second.try_acquire()
    assert recovered is not None
    second.release(recovered)
    assert cloud.count(target, kind='request') == 0


def test_competing_instances_cannot_oversubscribe_shared_capacity(target):
    controllers = [AdmissionController(target, max_inflight=3) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        leases = list(pool.map(lambda controller: controller.try_acquire(), controllers))
    assert sum(lease is not None for lease in leases) == 3
    for controller, lease in zip(controllers, leases):
        if lease is not None:
            controller.release(lease)
    assert cloud.count(target, kind='request') == 0


def test_all_instances_share_provider_slot_and_unknown_outcome_stays_blocked(target, tmp_path):
    _, sid = session(target)
    first, second = service(target, tmp_path), service(target, tmp_path)

    async def run():
        lease = await first.gatekeeper._acquire_single_slot(sid)
        with pytest.raises(SpeechBusyError, match='Shared'):
            await second.gatekeeper._acquire_single_slot(sid)
        first.gatekeeper._start_single_slot(lease)
        first.gatekeeper._release_single_slot(lease, uncertain=True)
        with closing(open_connection(target)) as conn:
            conn.execute('UPDATE cloud_leases SET expires_at=0 WHERE id=?', (lease.id,))
        with pytest.raises(SpeechBusyError, match='Shared'):
            await second.gatekeeper._acquire_single_slot(sid)
        assert await second.cancel_session(sid, 0) == 1
        assert second.gatekeeper.get_capacity_status().deployment_topology == 'DISTRIBUTED_POSTGRES_LEASE'
        # Test-only operator reconciliation; never automatically discard a STARTED/uncertain call.
        cloud.finish(target, lease)
        replacement = await second.gatekeeper._acquire_single_slot(sid)
        second.gatekeeper._release_single_slot(replacement)
        await first.aclose(); await second.aclose()

    asyncio.run(run())
    assert not (tmp_path / 'must-not-create-local-audio').exists()


def test_second_instance_startup_does_not_settle_active_usage_and_recovery_is_idempotent(target, tmp_path):
    _, sid = session(target)
    first = service(target, tmp_path)
    rid = first.gatekeeper._reserve_usage(session_id=sid, turn_generation=0,
                                          operation_type='STT', est_stt_sec=2.0)
    second = service(target, tmp_path)
    with closing(open_connection(target)) as conn:
        assert conn.execute('SELECT status FROM usage_reservations WHERE id=?', (rid,)).fetchone()[0] == 'RESERVED'
        conn.execute('UPDATE usage_reservations SET created_at=? WHERE id=?',
                     ((datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat(), rid))
    first.gatekeeper.recover_pending_usage()
    second.gatekeeper.recover_pending_usage()
    with closing(open_connection(target)) as conn:
        assert conn.execute('SELECT status,uncertain,stt_seconds FROM usage_reservations WHERE id=?', (rid,)).fetchone()[:] == ('COMMITTED', 1, 2.0)
        assert conn.execute('SELECT count(*) FROM usage_ledger WHERE reservation_id=?', (rid,)).fetchone()[0] == 1
    first.close(); second.close()


@pytest.mark.parametrize('status', [None, 429])
def test_actual_mocked_provider_failure_preserves_unknown_lease_only(target, tmp_path, status):
    _, sid = session(target)
    first, second = service(target, tmp_path), service(target, tmp_path)
    first.gatekeeper.max_429_retries = 0
    wav = wrap_raw_pcm_as_wav(b'\x01\x00' * 8000, sample_rate_hz=16000, num_channels=1, sample_width_bytes=2)

    async def failing_provider(req, data):
        raise GnaniTransportError('Controlled mocked boundary', status_code=status, retryable=False)

    async def run():
        with pytest.raises(GnaniTransportError):
            await first.gatekeeper.execute_stt(STTRequest(session_id=sid, turn_generation=0),
                                              wav, transcribe_fn=failing_provider)
        assert cloud.count(target, kind='speech') == (1 if status is None else 0)
        if status is None:
            with pytest.raises(SpeechBusyError):
                await second.gatekeeper._acquire_single_slot(sid)
        else:
            lease = await second.gatekeeper._acquire_single_slot(sid)
            second.gatekeeper._release_single_slot(lease)
        with closing(open_connection(target)) as conn:
            row = conn.execute('SELECT status,uncertain,request_count FROM usage_reservations WHERE session_id=?', (sid,)).fetchone()
            assert row[:] == ('COMMITTED', 1 if status is None else 0, 1)
        await first.aclose(); await second.aclose()

    asyncio.run(run())


def test_private_audio_survives_another_instance_and_cannot_return_after_delete(target):
    repo, sid = session(target)
    _, other = session(target)
    first, second = cloud.PostgresTTSCache(target), cloud.PostgresTTSCache(target)
    pcm = b'\x01\x00' * 200
    wav = first.put_completed_stream('first', pcm, stream_completed=True, session_id=sid)
    assert second.get_wav('first', session_id=sid) == wav
    assert second.get_wav('first', session_id=other) is None
    with pytest.raises(ValueError):
        first.put_completed_stream('partial', pcm, stream_completed=False, session_id=sid)
    public = first.put_completed_stream('orientation', pcm, stream_completed=True, scope='PUBLIC_GENERIC', session_id=sid)
    repo.tombstone_session(sid)
    assert second.evict_session(sid) == 1
    with pytest.raises(ValueError, match='deleted'):
        first.put_completed_stream('late', pcm, stream_completed=True, session_id=sid)
    assert second.get_wav('first', session_id=sid) is None
    assert second.get_wav('orientation', scope='PUBLIC_GENERIC', session_id=other) == public
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT count(*) FROM cloud_audio WHERE scope='SESSION_SCOPED' AND session_id=?", (sid,)).fetchone()[0] == 0


def test_real_asgi_startup_uses_postgres_and_operator_probe_reports_database(target, tmp_path):
    class LocalSettings(Settings):
        @property
        def database_target(self):
            return target

    settings = LocalSettings(env='test', cloud_runtime=True, gnani_api_key=None, groq_api_key=None,
                             tts_cache_dir=tmp_path / 'must-not-create-local-audio')
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get('/api/v1/meta/health')
        assert response.status_code == 200
        assert app.state.speech.gatekeeper.db_path == target
        assert isinstance(app.state.speech.cache, cloud.PostgresTTSCache)
        assert _database_ready(target)
        assert cloud.count(target, kind='request') == 0
    assert not (tmp_path / 'must-not-create-local-audio').exists()


def test_speech_migration_upgrades_prior_runtime_without_losing_reservations(target, tmp_path):
    from dataclasses import replace
    other = replace(target, schema='viva_speech_upgrade_' + uuid.uuid4().hex)
    source = Path(__file__).resolve().parents[2] / 'app' / 'db' / 'postgres' / 'runtime_migrations'
    directory = tmp_path / 'prior-runtime'
    directory.mkdir()
    try:
        for path in source.glob('*.sql'):
            if path.name.split('_', 1)[0] < '0006':
                shutil.copy2(path, directory / path.name)
        apply_migrations(other, directory)
        _, sid = session(other)
        now = datetime.now(timezone.utc).isoformat()
        with closing(open_connection(other)) as conn:
            conn.execute('INSERT INTO usage_reservations VALUES(?,?,?,?,?,?,?,?,?)',
                         ('old-reservation', sid, 'STT', 2.0, 3, 1, 'RESERVED', now, now))
        shutil.copy2(source / '0006_speech_ledger.sql', directory / '0006_speech_ledger.sql')
        assert apply_migrations(other, directory) == ['0006']
        with closing(open_connection(other)) as conn:
            row = conn.execute('SELECT reservation_id,reserved_stt_sec,reserved_tts_chars,status FROM usage_reservations WHERE id=?', ('old-reservation',)).fetchone()
            assert row[:] == ('old-reservation', 2.0, 3, 'RESERVED')
            assert conn.execute("SELECT julianday('2026-11-15'),julianday('invalid')").fetchone()[:] == (2461359.5, None)
    finally:
        psycopg = pytest.importorskip('psycopg')
        with _raw_connection(other) as conn:
            conn.execute(psycopg.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(psycopg.sql.Identifier(other.schema)))
