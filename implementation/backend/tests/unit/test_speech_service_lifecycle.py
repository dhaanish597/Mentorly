"""Offline lifecycle regressions against the coordinator-owned speech service."""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.core.config import Settings
from backend.app.db.repository import SQLiteRepository
from backend.app.models.api_schemas import AudioEvent, STTResult
from backend.app.orchestration.state_machine import CoordinatorStateMachine
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gatekeeper import SpeechBusyError
from backend.app.speech.gnani_adapter import AssembledTTSSynthesis
from backend.app.speech.service import SpeechService


@pytest.fixture
def lifecycle(tmp_path: Path):
    settings = Settings(_env_file=None, gnani_api_key=None, groq_api_key=None,
                        internal_worker_secret=None, database_path=tmp_path / 'db.sqlite',
                        tts_cache_dir=tmp_path / 'cache')
    repo = SQLiteRepository(settings.database_path)
    repo.initialize()
    sid = str(uuid4())
    source = 'def first_at_least(nums, target):\n    return -1\n'
    repo.create_session(session_id=sid, token_hash=hashlib.sha256(sid.encode()).hexdigest(),
        exercise_id='ex2_binary_search', spec_version='v1_sorted_with_duplicates',
        language_mode='en-IN', interaction_mode='TEXT', starter_code=source,
        starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    service = SpeechService(db_path=settings.database_path, cache_dir=settings.tts_cache_dir,
                            settings=settings)
    revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
    yield repo, service, sid, revision
    if service.gatekeeper._conn:
        try:
            service.close()
        except sqlite3.ProgrammingError:
            pass


def transcript(transport: str = 'REST_V3') -> STTResult:
    return STTResult(request_id='offline-result', client_request_id='offline-client',
        transport=transport, language_mode='en-IN', observed_format='transcribe',
        raw_transcript='returns minus one', normalized_transcript='returns -1',
        audio_duration_sec=0.1, latency_ms=1)


def synthesis(events: list[AudioEvent], *, cached: bool = False) -> AssembledTTSSynthesis:
    return AssembledTTSSynthesis(request_id='offline-tts', cache_key='offline-cache',
        cache_hit=cached, wav_bytes=generate_sine_wav_bytes(duration_sec=0.1), events=events,
        speakable_chunks=['Hello.'], total_chars_billed=0 if cached else 6, latency_ms=1)


@pytest.mark.parametrize('invalid', ['foreign', 'missing', 'deleted', 'generation', 'hash', 'source', 'code'])
def test_authoritative_revision_rejection_never_dispatches(lifecycle, monkeypatch, invalid: str) -> None:
    repo, service, sid, rev = lifecycle
    calls = []
    async def provider(*args, **kwargs):
        calls.append(args)
        return transcript()
    monkeypatch.setattr(service.adapter, 'transcribe_rest', provider)
    if invalid == 'foreign':
        rev = rev.model_copy(update={'session_id': uuid4()})
    elif invalid == 'missing':
        sid = str(uuid4())
        rev = rev.model_copy(update={'session_id': UUID(sid)})
    elif invalid == 'deleted':
        with repo._connect() as conn:
            conn.execute("UPDATE sessions SET deleted_at='now' WHERE id=?", (sid,))
    elif invalid == 'generation':
        rev = rev.model_copy(update={'turn_generation': rev.turn_generation + 1})
    elif invalid == 'hash':
        rev = rev.model_copy(update={'code_hash': '0' * 64})
    elif invalid == 'source':
        with repo._connect() as conn:
            conn.execute("UPDATE code_versions SET source_code='altered' WHERE session_id=?", (sid,))
    else:
        with repo._connect() as conn:
            conn.execute('DELETE FROM code_versions WHERE session_id=?', (sid,))
    async def scenario() -> None:
        with pytest.raises(SpeechBusyError):
            await service.transcribe(sid, b'', 'en-IN', rev, 1)
        assert calls == []
        assert service.gatekeeper.get_capacity_status().stt_requests_count == 0
    asyncio.run(scenario())


@pytest.mark.parametrize('transport', ['REST_V3', 'WS_V3', 'unsupported'])
def test_transcribe_routes_current_source_and_rejects_stale_attempt(lifecycle, monkeypatch, transport: str) -> None:
    repo, service, sid, rev = lifecycle
    calls = []
    async def provider(req, audio, **kwargs):
        if 'assert_current' in kwargs:
            kwargs['assert_current']()
        calls.append((req, audio))
        return transcript('WS_V3' if transport == 'WS_V3' else 'REST_V3')
    monkeypatch.setattr(service.adapter, 'transcribe_rest', provider)
    monkeypatch.setattr(service.ws, 'transcribe_stream_with_fallback', provider)
    async def scenario() -> None:
        wav = generate_sine_wav_bytes(duration_sec=0.1)
        if transport == 'unsupported':
            with pytest.raises(ValueError, match='Unsupported STT transport'):
                await service.transcribe(sid, wav, 'en-IN', rev, 2, transport)
            assert calls == []
        else:
            result = await service.transcribe(sid, wav, 'en-IN', rev, 2, transport)
            assert result.normalized_transcript == 'returns -1'
            assert result.transport == transport
            assert calls[0][0].revision == rev
            assert calls[0][0].source_code == repo.get_code_version(sid, 1).source_code
            assert calls[0][1] == ([wav] if transport == 'WS_V3' else wav)
        with pytest.raises(SpeechBusyError, match='stale'):
            await service.transcribe(sid, wav, 'en-IN', rev, 1)
        assert service._tasks == {}
    asyncio.run(scenario())


@pytest.mark.parametrize('frames', [False, True])
def test_new_capture_cancels_old_capture_and_interrupt_allows_rerecord(lifecycle, monkeypatch, frames: bool) -> None:
    _, service, sid, rev = lifecycle
    async def scenario() -> None:
        started = asyncio.Event()
        calls = []
        async def provider(req, audio, **kwargs):
            calls.append(req.capture_attempt_id)
            if req.capture_attempt_id == 1:
                started.set()
                await asyncio.Event().wait()
            return transcript('WS_V3' if frames else 'REST_V3')
        monkeypatch.setattr(service.adapter, 'transcribe_rest', provider)
        monkeypatch.setattr(service.ws, 'transcribe_live', provider)
        async def call(attempt: int):
            if frames:
                return await service.transcribe_frames(sid, iter(()), 'en-IN', rev, attempt)
            return await service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', rev, attempt)
        old = asyncio.create_task(call(1))
        await asyncio.wait_for(started.wait(), 1)
        result = await call(2)
        with pytest.raises(asyncio.CancelledError):
            await old
        assert result.requires_confirmation is True
        service.interrupt(sid, rev.turn_generation)
        with pytest.raises(SpeechBusyError):
            await call(2)
        # Rejected attempt 2 registers 3 internally; the next fresh allocation is 4.
        assert (await call(4)).normalized_transcript == 'returns -1'
        service.cancel(sid, rev.turn_generation)
        assert service.gatekeeper.is_capture_superseded(sid, rev.turn_generation, 4)
        if not frames:
            with pytest.raises(SpeechBusyError):
                await call(5)
        assert calls == [1, 2, 4]
        assert service._tasks == {}
    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['stt', 'tts'])
def test_queued_source_edit_releases_budget_without_provider_dispatch(lifecycle, monkeypatch, operation: str) -> None:
    repo, service, sid, rev = lifecycle
    async def forbidden(*args, **kwargs):
        pytest.fail('Superseded queued work reached provider')
    monkeypatch.setattr(service.adapter, 'transcribe_rest', forbidden)
    monkeypatch.setattr(service.adapter, 'synthesize_tts', forbidden)
    async def scenario() -> None:
        gate = service.gatekeeper
        await gate._acquire_single_slot()
        call = service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', rev, 1) if operation == 'stt' else service.synthesize(sid, 'Hello.', rev)
        task = asyncio.create_task(call)
        for _ in range(100):
            if gate.get_capacity_status().queued_requests:
                break
            await asyncio.sleep(0)
        assert gate.get_capacity_status().queued_requests == 1
        repo.save_code_version(sid, expected_code_version_id=1,
            source_code='def first_at_least(nums, target):\n    return 0\n', code_hash='0' * 64)
        gate._release_single_slot()
        with pytest.raises(SpeechBusyError, match='superseded'):
            await task
        cap = gate.get_capacity_status()
        assert cap.uncertain_requests_count == 0
        assert cap.stt_seconds_reserved == cap.tts_chars_reserved == 0
        assert gate._conn.execute('SELECT status FROM usage_reservations').fetchone()[0] == 'RELEASED'
    asyncio.run(scenario())


def test_completed_response_is_not_returned_after_source_edit(lifecycle, monkeypatch) -> None:
    repo, service, sid, rev = lifecycle
    async def provider(req, audio):
        repo.save_code_version(sid, expected_code_version_id=1,
            source_code='def first_at_least(nums, target):\n    return 0\n', code_hash='0' * 64)
        return transcript()
    monkeypatch.setattr(service.adapter, 'transcribe_rest', provider)
    async def scenario() -> None:
        with pytest.raises(SpeechBusyError, match='superseded'):
            await service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', rev, 1)
        assert service.gatekeeper.get_capacity_status().stt_requests_count == 1
        assert service._tasks == {}
    asyncio.run(scenario())


@pytest.mark.parametrize('cached', [False, True])
def test_stream_preserves_events_playback_identity_and_cache_delivery(lifecycle, monkeypatch, cached: bool) -> None:
    _, service, sid, rev = lifecycle
    events = [AudioEvent(event_type=kind, request_id='offline-stream', playback_id='playback')
              for kind in ['start', 'chunk', 'complete']]
    async def execute(req, *, on_event, assert_current):
        assert req.revision == rev and req.playback_id == 'playback' and req.turn_id == 'turn'
        assert_current()
        await asyncio.sleep(0.12)  # Exercise queue timeout while provider is legitimately silent.
        if not cached:
            for event in events:
                await on_event(event)
        return synthesis(events, cached=cached)
    monkeypatch.setattr(service.gatekeeper, 'execute_tts', execute)
    async def scenario() -> None:
        output = [event async for event in service.stream_synthesize(sid, 'Hello.', rev, 'playback', 'turn')]
        assert output == events
        assert service._tasks == {}
    asyncio.run(scenario())


def test_closing_stream_cancels_producer_and_does_not_deliver_late_audio(lifecycle, monkeypatch) -> None:
    _, service, sid, rev = lifecycle
    async def scenario() -> None:
        cancelled = asyncio.Event()
        async def execute(req, *, on_event, assert_current):
            try:
                await on_event(AudioEvent(event_type='start', request_id='offline'))
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(service.gatekeeper, 'execute_tts', execute)
        stream = service.stream_synthesize(sid, 'Hello.', rev)
        assert (await asyncio.wait_for(anext(stream), 1)).event_type == 'start'
        await stream.aclose()
        assert cancelled.is_set()
        assert service._tasks == {}
    asyncio.run(scenario())


def test_cancel_session_timeout_reports_pending_then_drains_without_touching_other_session(lifecycle) -> None:
    _, service, sid, rev = lifecycle
    async def scenario() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        async def resistant():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
            return 'drained'
        tracked = asyncio.create_task(service._track(sid, rev.turn_generation, resistant()))
        await started.wait()
        service.gatekeeper.register_capture_attempt('other-session', 0, 1)
        assert await service.cancel_session(sid, rev.turn_generation, timeout_seconds=0) == 1
        assert not tracked.done()
        release.set()
        assert await tracked == 'drained'
        assert await service.cancel_session(sid, rev.turn_generation) == 0
        assert 'other-session' in service.gatekeeper._session_captures
        assert service._tasks == {}
    asyncio.run(scenario())


def test_async_shutdown_cancels_tracked_work_and_closes_database(lifecycle) -> None:
    _, service, sid, rev = lifecycle
    async def scenario() -> None:
        started = asyncio.Event()
        async def waiting():
            started.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(service._track(sid, rev.turn_generation, waiting()))
        await started.wait()
        await service.aclose()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(sqlite3.ProgrammingError):
            service.gatekeeper._conn.execute('SELECT 1')
        assert service._tasks == {}
    asyncio.run(scenario())


@pytest.mark.parametrize('shutdown', ['interrupt', 'close'])
def test_inflight_shutdown_cancels_audio_and_releases_reservation(lifecycle, monkeypatch, shutdown: str) -> None:
    _, service, sid, rev = lifecycle
    async def scenario() -> None:
        started = asyncio.Event()
        async def provider(req, **kwargs):
            assert req.revision == rev
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(service.adapter, 'synthesize_tts', provider)
        task = asyncio.create_task(service.synthesize(sid, 'Hello.', rev))
        await asyncio.wait_for(started.wait(), 1)
        if shutdown == 'interrupt':
            service.interrupt(sid, rev.turn_generation)
        else:
            service.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service._tasks == {}
        if shutdown == 'interrupt':
            assert service.gatekeeper.get_capacity_status().tts_chars_reserved == 0
            assert service.gatekeeper.get_capacity_status().uncertain_requests_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('frames', [False, True])
@pytest.mark.parametrize('streaming', [False, True])
def test_new_turn_capture_cancels_superseded_tts_and_retains_uncertain_usage(
    lifecycle, monkeypatch, frames: bool, streaming: bool,
) -> None:
    repo, service, sid, old_rev = lifecycle

    async def scenario() -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def tts(req, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                assert kwargs['is_cancelled']()
                cancelled.set()

        async def stt(req, audio):
            assert cancelled.is_set()
            capacity = service.gatekeeper.get_capacity_status()
            assert capacity.active_requests == capacity.max_concurrency == 1
            return transcript('WS_V3' if frames else 'REST_V3')

        async def live(req, frame_source, **kwargs):
            return await service.gatekeeper.execute_stt(
                req, generate_sine_wav_bytes(duration_sec=0.1), **kwargs,
            )

        monkeypatch.setattr(service.adapter, 'synthesize_tts', tts)
        monkeypatch.setattr(service.adapter, 'transcribe_rest', stt)
        monkeypatch.setattr(service.ws, 'transcribe_live', live)

        async def voice():
            if streaming:
                return [event async for event in service.stream_synthesize(sid, 'Hello.', old_rev)]
            return await service.synthesize(sid, 'Hello.', old_rev)

        old = asyncio.create_task(voice())
        await asyncio.wait_for(started.wait(), 1)
        turn, attempt = repo.create_or_reuse_turn(
            session_id=sid, code_version_id=old_rev.code_version_id, challenge_id=None,
        )
        revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
        assert revision.turn_generation == old_rev.turn_generation + 1 == turn.turn_generation
        try:
            operation = service.transcribe_frames(sid, iter(()), 'en-IN', revision, attempt) if frames else service.transcribe(
                sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', revision, attempt,
            )
            result = await asyncio.wait_for(operation, 1)
            assert result.normalized_transcript == 'returns -1'
            expected = (SpeechBusyError, asyncio.CancelledError) if streaming else SpeechBusyError
            with pytest.raises(expected):
                await old
            capacity = service.gatekeeper.get_capacity_status()
            assert capacity.active_requests == capacity.queued_requests == 0
            assert capacity.uncertain_requests_count == 1
            assert capacity.tts_chars_uncertain == len('Hello.')
            assert capacity.tts_chars_reserved == capacity.stt_seconds_reserved == 0
            assert capacity.stt_requests_count == 1
            assert service._tasks == {}
            # Cancelling the superseded generation must not poison the new turn.
            assert (sid, revision.turn_generation) not in service.gatekeeper._cancelled_turns
            assert not service.gatekeeper.is_capture_superseded(sid, revision.turn_generation, attempt)
        finally:
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)

    asyncio.run(scenario())


def test_new_turn_capture_releases_queued_old_tts_without_uncertain_billing(lifecycle, monkeypatch) -> None:
    repo, service, sid, old_rev = lifecycle

    async def forbidden(*args, **kwargs):
        pytest.fail('Superseded queued TTS reached the provider')

    monkeypatch.setattr(service.adapter, 'synthesize_tts', forbidden)
    monkeypatch.setattr(service.adapter, 'transcribe_rest', lambda *args: asyncio.sleep(0, result=transcript()))

    async def scenario() -> None:
        gate = service.gatekeeper
        await gate._acquire_single_slot()
        old = asyncio.create_task(service.synthesize(sid, 'Hello.', old_rev))
        for _ in range(100):
            if gate.get_capacity_status().queued_requests:
                break
            await asyncio.sleep(0)
        assert gate.get_capacity_status().queued_requests == 1
        _, attempt = repo.create_or_reuse_turn(session_id=sid, code_version_id=old_rev.code_version_id, challenge_id=None)
        revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
        capture = asyncio.create_task(service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', revision, attempt))
        try:
            with pytest.raises(SpeechBusyError):
                await asyncio.wait_for(asyncio.shield(old), 1)
            capacity = gate.get_capacity_status()
            assert capacity.tts_chars_reserved == capacity.uncertain_requests_count == 0
            row = gate._conn.execute("SELECT status FROM usage_reservations WHERE operation_type='TTS'").fetchone()
            assert row['status'] == 'RELEASED'
        finally:
            gate._release_single_slot()
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        assert (await capture).normalized_transcript == 'returns -1'
        assert gate.get_capacity_status().active_requests == 0

    asyncio.run(scenario())


def test_new_capture_does_not_cancel_other_session_tts_or_bypass_its_slot(lifecycle, monkeypatch) -> None:
    repo, service, sid, revision = lifecycle
    other_sid = str(uuid4())
    source = repo.get_code_version(sid, revision.code_version_id).source_code
    repo.create_session(session_id=other_sid, token_hash='test-only', exercise_id=revision.exercise_id.value,
        spec_version=revision.spec_version.value, language_mode='en-IN', interaction_mode='VOICE',
        starter_code=source, starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    other_rev = CoordinatorStateMachine(repo).build_revision_ref(other_sid)

    async def scenario() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def tts(req, **kwargs):
            started.set()
            await release.wait()
            assert not kwargs['is_cancelled']()
            return synthesis([])

        monkeypatch.setattr(service.adapter, 'synthesize_tts', tts)
        monkeypatch.setattr(service.adapter, 'transcribe_rest', lambda *args: asyncio.sleep(0, result=transcript()))
        service.gatekeeper.queue_wait_timeout_sec = 0.01
        other = asyncio.create_task(service.synthesize(other_sid, 'Hello.', other_rev))
        await asyncio.wait_for(started.wait(), 1)
        try:
            with pytest.raises(SpeechBusyError, match='Timed out waiting'):
                await service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', revision, 1)
            assert not other.done()
            capacity = service.gatekeeper.get_capacity_status()
            assert capacity.active_requests == capacity.max_concurrency == 1
            assert capacity.uncertain_requests_count == capacity.stt_seconds_reserved == 0
        finally:
            release.set()
            await other
        assert (await service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', revision, 2)).requires_confirmation

    asyncio.run(scenario())


def test_superseded_cancellation_resistant_tts_keeps_slot_until_cleanup(lifecycle, monkeypatch) -> None:
    repo, service, sid, old_rev = lifecycle

    async def scenario() -> None:
        started, cancellation_seen, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def tts(req, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release.wait()
            return synthesis([])

        monkeypatch.setattr(service.adapter, 'synthesize_tts', tts)
        monkeypatch.setattr(service.adapter, 'transcribe_rest', lambda *args: asyncio.sleep(0, result=transcript()))
        service.gatekeeper.queue_wait_timeout_sec = 0.01
        old = asyncio.create_task(service.synthesize(sid, 'Hello.', old_rev))
        await asyncio.wait_for(started.wait(), 1)
        _, attempt = repo.create_or_reuse_turn(session_id=sid, code_version_id=old_rev.code_version_id, challenge_id=None)
        revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
        try:
            with pytest.raises(SpeechBusyError, match='Timed out waiting'):
                await service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', revision, attempt)
            assert cancellation_seen.is_set()
            assert not old.done()
            capacity = service.gatekeeper.get_capacity_status()
            assert capacity.active_requests == capacity.max_concurrency == 1
            assert capacity.tts_chars_reserved == len('Hello.')
            assert capacity.stt_requests_count == capacity.uncertain_requests_count == 0
        finally:
            release.set()
            if not cancellation_seen.is_set():
                old.cancel()
            with pytest.raises(SpeechBusyError):
                await old
        assert (await service.transcribe(sid, generate_sine_wav_bytes(duration_sec=0.1), 'en-IN', revision, attempt + 1)).requires_confirmation
        assert service.gatekeeper.get_capacity_status().active_requests == 0

    asyncio.run(scenario())


def test_synthesize_returns_typed_audio_bound_to_turn_and_playback(lifecycle, monkeypatch) -> None:
    _, service, sid, rev = lifecycle
    expected = synthesis([])
    async def provider(req, **kwargs):
        assert req.revision == rev
        assert req.turn_id == 'turn-id' and req.playback_id == 'playback-id'
        assert req.model == service.settings.gnani_tts_model
        assert req.voice == service.settings.gnani_tts_voice
        return expected
    monkeypatch.setattr(service.adapter, 'synthesize_tts', provider)
    async def scenario() -> None:
        result = await service.synthesize(sid, 'Hello.', rev, 'turn-id', 'playback-id')
        assert result == expected
        assert result.wav_bytes.startswith(b'RIFF')
        assert service._tasks == {}
        assert service.gatekeeper.get_capacity_status().tts_chars_reserved == 0
    asyncio.run(scenario())
