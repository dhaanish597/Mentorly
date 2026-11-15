"""Real session speech routes, capability auth and durable replay; no execution or network."""
from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import asyncio
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.core.config import Settings
from backend.app.db.repository import SQLiteRepository
from backend.app.main import create_app
from backend.app.models.api_schemas import AudioEvent, STTResult
from backend.app.models.domain import EvidenceArtifact, ExecutionObservation, RevisionRef, VerificationReport
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechQuotaExhaustedError
from backend.app.speech.gnani_adapter import AssembledTTSSynthesis, GnaniTransportError


class OfflineSpeech:
    """Typed boundary double: no worker, provider or learner execution is represented."""
    def __init__(self, actual) -> None:
        self.cache = actual.cache
        self.gatekeeper = actual.gatekeeper
        self.actual = actual
        self.calls = []
        self.mode = 'ok'
        self.after_capture = None

    def result(self, transport: str = 'REST_V3') -> STTResult:
        return STTResult(request_id='offline-correlation', client_request_id='offline-client',
            transport=transport, language_mode='en-IN', observed_format='transcribe',
            raw_transcript='It returns minus one', normalized_transcript='It returns -1',
            provider_confidence=None, audio_duration_sec=0.1, latency_ms=1)

    async def transcribe(self, sid, audio, language, revision, attempt, transport):
        self.calls.append(('stt', sid, audio, revision, attempt, transport))
        if self.mode == 'error':
            raise RuntimeError('Private provider diagnostics must not reach the client')
        if self.after_capture:
            self.after_capture()
        return self.result(transport)

    async def transcribe_frames(self, sid, frames, language, revision, attempt):
        # Preserve the production service's revision gate at the mocked provider boundary.
        self.actual._assert_current(sid, revision)
        received = [frame async for frame in frames]
        self.calls.append(('ws', sid, received, revision, attempt))
        if self.after_capture:
            self.after_capture()
        return self.result('WS_V3')

    async def synthesize(self, sid, text, revision, **kwargs):
        self.calls.append(('tts', sid, text, revision, kwargs))
        if self.mode == 'error':
            raise RuntimeError('Private provider diagnostics must not reach the client')
        return AssembledTTSSynthesis(request_id='offline-tts', cache_key='offline',
            cache_hit=False, wav_bytes=generate_sine_wav_bytes(duration_sec=0.1), events=[],
            speakable_chunks=[text], total_chars_billed=len(text), latency_ms=1)

    async def stream_synthesize(self, sid, text, revision, **kwargs):
        self.calls.append(('stream', sid, text, revision, kwargs))
        # Synthesis selectors are request fields, not outbound AudioEvent metadata.
        kwargs = {key: value for key, value in kwargs.items() if key == 'playback_id'}
        yield AudioEvent(event_type='start', request_id='offline-stream', **kwargs)
        if self.mode == 'error':
            raise RuntimeError('Private provider diagnostics must not reach the client')
        yield AudioEvent(event_type='chunk', request_id='offline-stream',
                         audio_b64=base64.b64encode(b'\x01\x00' * 8).decode(), **kwargs)
        yield AudioEvent(event_type='complete', request_id='offline-stream', **kwargs)

    def cancel(self, sid, generation) -> None:
        self.calls.append(('cancel', sid, generation))
        self.actual.cancel(sid, generation)

    def interrupt(self, sid, generation) -> None:
        self.calls.append(('interrupt', sid, generation))
        self.actual.interrupt(sid, generation)

    async def cancel_session(self, sid, generation) -> int:
        self.calls.append(('delete', sid, generation))
        return await self.actual.cancel_session(sid, generation)

    async def aclose(self) -> None:
        await self.actual.aclose()


@pytest.fixture
def http_speech(tmp_path: Path):
    settings = Settings(_env_file=None, gnani_api_key=None, groq_api_key=None,
        internal_worker_secret=None, allow_public_custom_code=False,
        database_path=tmp_path / 'sessions.db', tts_cache_dir=tmp_path / 'tts')
    app = create_app(settings)
    with TestClient(app) as client:
        created_response = client.post('/api/v1/sessions', json={
            'exercise_id': 'ex2_binary_search', 'spec_version': 'v1_sorted_with_duplicates'})
        assert created_response.status_code == 200
        created = created_response.json()
        path = '/api/v1/sessions/' + created['session_id']
        headers = {'Authorization': 'Bearer ' + created['session_token']}
        challenge = client.post(path + '/challenges', json={
            'revision': created['revision'], 'purpose': 'DIAGNOSTIC'},
            headers={**headers, 'X-Idempotency-Key': str(uuid4())})
        assert challenge.status_code == 200, challenge.text
        speech = OfflineSpeech(app.state.speech)
        app.state.speech = speech
        repo = SQLiteRepository(settings.database_path)
        yield client, path, headers, challenge.json(), speech, repo


def audio_request(client, path: str, headers: dict, challenge: dict, *, key: str | None = None,
                  audio: bytes | None = None, revision: dict | None = None, cid: str | None = None):
    return client.post(path + '/turns/audio', headers={**headers, 'X-Idempotency-Key': key or str(uuid4())},
        data={'revision': json.dumps(revision or challenge['revision']),
              'challenge_id': cid or challenge['challenge_id'], 'capture_attempt_id': '999'},
        files={'audio': ('capture.wav', audio if audio is not None else generate_sine_wav_bytes(duration_sec=0.1), 'audio/wav')})


def opening(headers: dict, challenge: dict) -> dict:
    return {'token': headers['Authorization'][7:], 'revision': challenge['revision'],
            'challenge_id': challenge['challenge_id'], 'language_mode': 'en-IN'}


def unavailable_artifact(repo, challenge: dict, *, reveal: bool = True) -> EvidenceArtifact:
    """Persist honest zero-execution evidence, not an accepted worker success claim."""
    rev = RevisionRef.model_validate(challenge['revision'])
    sid = str(rev.session_id)
    raw = repo.get_challenge(sid, challenge['challenge_id'])
    artifact = EvidenceArtifact(artifact_id=uuid4(), revision=rev, challenge_id=challenge['challenge_id'],
        canonical_input=raw['input_args'], case_hash=raw['case_hash'], confirmed_prediction=None,
        actual_observation=ExecutionObservation(kind='UNAVAILABLE', duration_ms=0),
        reference_output=-1, prediction_status='NOT_EVALUATED',
        verification_report=VerificationReport(status='EXECUTION_UNAVAILABLE', curated_cases_run=0,
            curated_cases_total=0, generated_cases_run=0, generated_cases_target=0,
            terminal_reason='Offline speech test: no execution occurred', runtime_version='not-executed'))
    repo.save_artifact(artifact_id=str(artifact.artifact_id), session_id=sid,
        challenge_id=str(artifact.challenge_id), code_version_id=rev.code_version_id,
        turn_generation=rev.turn_generation, case_hash=artifact.case_hash, confirmed_prediction=None,
        prediction_status='NOT_EVALUATED', verification_status='EXECUTION_UNAVAILABLE',
        minimization_status='NOT_ATTEMPTED', artifact_json=artifact.model_dump_json())
    if reveal:
        repo.reveal_challenge(sid, str(artifact.challenge_id), expected_revision=rev)
    return artifact


def test_audio_auth_idempotency_and_server_allocated_capture(http_speech) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    assert audio_request(client, path, {}, challenge).status_code == 401
    missing_key = client.post(path + '/turns/audio', headers=headers)
    assert missing_key.status_code == 400 and missing_key.json()['code'] == 'IDEMPOTENCY_KEY_REQUIRED'
    key = str(uuid4())
    # Replay requires byte-identical multipart framing, not just equivalent fields.
    request = client.build_request('POST', path + '/turns/audio', headers={**headers, 'X-Idempotency-Key': key},
        data={'revision': json.dumps(challenge['revision']), 'challenge_id': challenge['challenge_id'], 'capture_attempt_id': '999'},
        files={'audio': ('capture.wav', generate_sine_wav_bytes(duration_sec=0.1), 'audio/wav')})
    body = request.read()
    first = client.send(request)
    assert first.status_code == 200, first.text
    result = first.json()
    replay = client.post(path + '/turns/audio', content=body, headers=dict(request.headers))
    assert replay.json() == result
    assert len(speech.calls) == 1
    assert result['capture_attempt_id'] == 1
    assert result['requires_confirmation'] is True
    assert result['proposed_claim']['confirmed_at'] is None
    assert result['proposed_claim']['provider_confidence'] is None
    assert result['transcript'] == 'It returns -1'
    assert repo.get_turn(challenge['revision']['session_id'], result['turn_id']).state == 'AWAITING_CLAIM_CONFIRMATION'
    conflict = client.post(path + '/turns/audio', content=body + b'changed', headers=dict(request.headers))
    assert conflict.status_code == 409 and conflict.json()['code'] == 'IDEMPOTENCY_CONFLICT'
    second = audio_request(client, path, headers, challenge)
    assert second.status_code == 200
    assert second.json()['turn_id'] == result['turn_id']
    assert second.json()['capture_attempt_id'] == 2


@pytest.mark.parametrize('failure', ['revision', 'challenge', 'revealed', 'oversize', 'provider', 'superseded'])
def test_audio_safety_denials_and_sanitized_fallback(http_speech, failure: str) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    options = {}
    expected = 409
    if failure == 'revision':
        options['revision'] = {**challenge['revision'], 'code_hash': '0' * 64}
    elif failure == 'challenge':
        options['cid'] = str(uuid4())
    elif failure == 'revealed':
        repo.reveal_challenge(challenge['revision']['session_id'], challenge['challenge_id'])
    elif failure == 'oversize':
        options['audio'] = b'\x00' * 2_000_001
        expected = 400
    elif failure == 'provider':
        speech.mode = 'error'
        expected = 503
    else:
        def cancel_capture() -> None:
            turn = repo.get_active_turn(challenge['revision']['session_id'])
            repo.update_turn(challenge['revision']['session_id'], turn.id, state='CANCELLED')
        speech.after_capture = cancel_capture
    response = audio_request(client, path, headers, challenge, **options)
    assert response.status_code == expected, response.text
    assert 'Private provider' not in response.text
    if failure == 'provider':
        assert response.json()['code'] == 'SPEECH_UNAVAILABLE'
    if failure in ('revision', 'challenge', 'revealed', 'oversize'):
        assert speech.calls == []


@pytest.mark.parametrize('error,status,code,retryable', [
    (SpeechBusyError('Private queue diagnostics'), 503, 'SPEECH_BUSY', True),
    (SpeechQuotaExhaustedError('Private quota diagnostics'), 429, 'SPEECH_QUOTA_EXHAUSTED', False),
    (GnaniTransportError('Private provider diagnostics', retryable=True), 503, 'SPEECH_UNAVAILABLE', True),
    (GnaniTransportError('Private provider diagnostics', status_code=401), 503, 'SPEECH_UNAVAILABLE', False),
    (RuntimeError('Private provider diagnostics'), 503, 'SPEECH_UNAVAILABLE', False),
])
def test_audio_failure_has_safe_allocated_identity_and_restored_revision_allows_retained_retry(
    http_speech, monkeypatch, error: Exception, status: int, code: str, retryable: bool,
) -> None:
    client, _, _, _, speech, repo = http_speech
    created = client.post('/api/v1/sessions', json={
        'exercise_id': 'ex2_binary_search', 'spec_version': 'v1_sorted_with_duplicates',
    }).json()
    sid = created['session_id']
    path = '/api/v1/sessions/' + sid
    headers = {'Authorization': 'Bearer ' + created['session_token']}
    wav = generate_sine_wav_bytes(duration_sec=0.1)
    calls = []

    async def fail(session_id, audio, language, revision, attempt, transport):
        calls.append((audio, revision, attempt))
        raise error

    monkeypatch.setattr(speech, 'transcribe', fail)

    def send(revision, key=None):
        return client.post(path + '/turns/audio',
            headers={**headers, 'X-Idempotency-Key': key or str(uuid4())},
            data={'revision': json.dumps(revision), 'capture_attempt_id': '999'},
            files={'audio': ('retained.wav', wav, 'audio/wav')})

    response = send(created['revision'])
    assert response.status_code == status, response.text
    body = response.json()
    allocated = repo.get_active_turn(sid)
    assert body['code'] == code
    assert body['retryable'] is retryable
    assert body['turn_id'] == allocated.id
    assert body['request_id'] and response.headers['x-request-id'] == body['request_id']
    assert set(body) == {'code', 'message', 'retryable', 'request_id', 'turn_id', 'job_id'}
    assert 'Private' not in response.text
    assert allocated.latest_capture_attempt_id == 1
    assert allocated.turn_generation == created['revision']['turn_generation'] + 1
    assert allocated.confirmed_at is None
    # A retained recording may only retry after authoritative restoration; no relaxed CAS.
    stale = send(created['revision'])
    assert stale.status_code == 409 and stale.json()['code'] == 'REVISION_CONFLICT'
    assert len(calls) == 1
    restored = client.get(path, headers=headers)
    assert restored.status_code == 200, restored.text
    snapshot = restored.json()
    current = snapshot['revision']
    assert current['turn_generation'] == allocated.turn_generation
    assert snapshot['active_turn']['turn_id'] == body['turn_id']
    assert snapshot['active_turn']['capture_attempt_id'] == allocated.latest_capture_attempt_id
    assert snapshot['active_turn']['turn_generation'] == allocated.turn_generation
    assert snapshot['active_turn']['proposed_claim'] is None

    async def recover(session_id, audio, language, revision, attempt, transport):
        calls.append((audio, revision, attempt))
        return speech.result()

    monkeypatch.setattr(speech, 'transcribe', recover)
    retried = send(current)
    assert retried.status_code == 200, retried.text
    assert retried.json()['requires_confirmation'] is True
    assert retried.json()['proposed_claim']['confirmed_at'] is None
    assert calls[0][0] == calls[1][0] == wav
    assert calls[0][1].turn_generation == allocated.turn_generation
    assert calls[1][1].turn_generation == allocated.turn_generation + 1


@pytest.mark.parametrize('same_generation', [False, True])
def test_audio_barge_in_cancels_actual_conversation_tts_and_returns_safe_409(
    http_speech, monkeypatch, same_generation: bool,
) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    if same_generation:
        created = {'session_id': challenge['revision']['session_id'], 'revision': challenge['revision']}
    else:
        created = client.post('/api/v1/sessions', json={
            'exercise_id': 'ex2_binary_search', 'spec_version': 'v1_sorted_with_duplicates',
        }).json()
        path = '/api/v1/sessions/' + created['session_id']
        headers = {'Authorization': 'Bearer ' + created['session_token']}
    typed = client.post(path + '/turns/text',
        headers={**headers, 'X-Idempotency-Key': str(uuid4())},
        json={'revision': created['revision'], 'text': 'I use binary search to narrow the interval.',
              'challenge_id': challenge['challenge_id'] if same_generation else None})
    assert typed.status_code == 200, typed.text
    previous = typed.json()
    actual = speech.actual
    client.app.state.speech = actual
    started, cancelled, release = threading.Event(), threading.Event(), threading.Event()

    async def tts(req, **kwargs):
        started.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
            return AssembledTTSSynthesis(request_id='offline', cache_key='offline', cache_hit=False,
                wav_bytes=generate_sine_wav_bytes(duration_sec=0.1), events=[],
                speakable_chunks=[req.text], total_chars_billed=len(req.text), latency_ms=1)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def stt(req, audio):
        assert cancelled.is_set()
        assert actual.gatekeeper.get_capacity_status().active_requests == 1
        return speech.result()

    monkeypatch.setattr(actual.adapter, 'synthesize_tts', tts)
    monkeypatch.setattr(actual.adapter, 'transcribe_rest', stt)
    with ThreadPoolExecutor(max_workers=1) as pool:
        voice = pool.submit(client.post, path + '/speech/conversation',
            json={'revision': previous['revision'], 'turn_id': previous['turn_id']},
            headers={**headers, 'X-Idempotency-Key': str(uuid4())})
        try:
            assert started.wait(timeout=1)
            response = client.post(path + '/turns/audio',
                headers={**headers, 'X-Idempotency-Key': str(uuid4())},
                data={'revision': json.dumps(previous['revision']),
                      **({'challenge_id': challenge['challenge_id']} if same_generation else {})},
                files={'audio': ('capture.wav', generate_sine_wav_bytes(duration_sec=0.1), 'audio/wav')})
            assert response.status_code == 200, response.text
            assert cancelled.is_set()
            superseded = voice.result(timeout=1)
            assert superseded.status_code == 409, superseded.text
            assert superseded.json()['code'] == 'SPEECH_BUSY'
            capacity = actual.gatekeeper.get_capacity_status()
            assert capacity.active_requests == capacity.queued_requests == 0
            assert capacity.uncertain_requests_count == 1
            assert capacity.tts_chars_uncertain > 0
            assert capacity.tts_chars_reserved == capacity.stt_seconds_reserved == 0
            assert capacity.stt_requests_count == capacity.max_concurrency == 1
            assert response.json()['revision']['turn_generation'] == previous['revision']['turn_generation'] + (0 if same_generation else 1)
            if same_generation:
                assert response.json()['turn_id'] == previous['turn_id']
                assert response.json()['capture_attempt_id'] == previous['capture_attempt_id'] + 1
                assert repo.get_turn(created['session_id'], previous['turn_id']).state == 'AWAITING_CLAIM_CONFIRMATION'
                assert repo.get_challenge(created['session_id'], challenge['challenge_id'])['reveal_state'] == 'HIDDEN'
            else:
                assert repo.get_turn(created['session_id'], previous['turn_id']).state == 'SUPERSEDED'
        finally:
            release.set()


def test_websocket_valid_pcm_requires_confirmation_and_preserves_nullable_confidence(http_speech) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    with client.websocket_connect(path + '/speech/ws') as ws:
        ws.send_json(opening(headers, challenge))
        ws.send_bytes(b'\x01\x00' * 512)
        ws.send_bytes(b'\x02\x00' * 128)
        ws.send_json({'type': 'commit'})
        result = ws.receive_json()
        assert result['requires_confirmation'] is True
        assert result['revision'] == challenge['revision']
        assert result['capture_attempt_id'] == 1
        assert result['speech']['transport'] == 'WS_V3'
        assert result['speech']['provider_confidence'] is None
        assert result['proposed_claim']['confirmed_at'] is None
        assert repo.get_turn(challenge['revision']['session_id'], result['turn_id']).normalized_transcript == 'It returns -1'
    assert speech.calls[0][2] == [b'\x01\x00' * 512, b'\x02\x00' * 128]


def test_websocket_explanation_before_challenge_needs_confirmation_without_execution(http_speech, monkeypatch) -> None:
    client, _, _, _, speech, _ = http_speech
    created = client.post('/api/v1/sessions', json={
        'exercise_id': 'ex1_shortest_subarray', 'spec_version': 'v1_positive_only'}).json()
    original = speech.result
    def explanation(transport='REST_V3'):
        text = 'The window shrinks whenever its sum reaches the target.'
        return original(transport).model_copy(update={'raw_transcript': text, 'normalized_transcript': text})
    monkeypatch.setattr(speech, 'result', explanation)
    path = '/api/v1/sessions/' + created['session_id']
    with client.websocket_connect(path + '/speech/ws') as ws:
        ws.send_json({'token': created['session_token'], 'revision': created['revision'], 'language_mode': 'en-IN'})
        ws.send_bytes(b'\x01\x00' * 128)
        ws.send_json({'type': 'commit'})
        result = ws.receive_json()
    assert result['requires_confirmation'] is True
    assert result['revision']['turn_generation'] > created['revision']['turn_generation']
    assert speech.calls[-1][3].model_dump(mode='json') == result['revision']
    claim = result['proposed_claim']
    assert claim['claim_type'] == 'INVARIANT_OR_MECHANISM_CLAIM'
    assert claim['challenge_id'] is None and claim['confirmed_at'] is None
    claim = {**claim, 'confirmed_at': datetime.now(timezone.utc).isoformat()}
    response = client.post(path + '/turns/' + result['turn_id'] + '/confirm-claim', json={
        'revision': result['revision'], 'capture_attempt_id': result['capture_attempt_id'], 'claim': claim},
        headers={'Authorization': 'Bearer ' + created['session_token'], 'X-Idempotency-Key': str(uuid4())})
    assert response.status_code == 200, response.text
    assert response.json()['executed'] is False
    assert response.json()['requires_prediction'] is True


@pytest.mark.parametrize('failure,code', [('origin', 4403), ('token', 4401), ('expired', 4410), ('deleted', 4410)])
def test_websocket_capability_denial_never_transcribes(http_speech, failure: str, code: int) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    first = opening(headers, challenge)
    ws_headers = {}
    if failure == 'origin':
        ws_headers['origin'] = 'https://not-allowed.invalid'
    elif failure == 'token':
        first['token'] = 'invalid-capability'
    else:
        with repo._connect() as conn:
            if failure == 'expired':
                conn.execute('UPDATE sessions SET expires_at=? WHERE id=?',
                    ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), challenge['revision']['session_id']))
            else:
                conn.execute("UPDATE sessions SET deleted_at='now' WHERE id=?", (challenge['revision']['session_id'],))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path + '/speech/ws', headers=ws_headers) as ws:
            ws.send_json(first)
            ws.receive_json()
    assert exc.value.code == code
    assert speech.calls == []


@pytest.mark.parametrize('failure', ['opening', 'revision', 'challenge', 'odd', 'oversize', 'control', 'superseded'])
def test_websocket_invalid_or_stale_capture_returns_only_safe_error(http_speech, failure: str) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    first = opening(headers, challenge)
    if failure == 'revision':
        first['revision'] = {**first['revision'], 'code_hash': '0' * 64}
    elif failure == 'challenge':
        first['challenge_id'] = str(uuid4())
    elif failure == 'superseded':
        def supersede() -> None:
            repo.save_code_version(challenge['revision']['session_id'], expected_code_version_id=1,
                source_code='def first_at_least(nums, target):\n    return 0\n', code_hash='0' * 64)
        speech.after_capture = supersede
    with client.websocket_connect(path + '/speech/ws') as ws:
        if failure == 'opening':
            ws.send_text('x' * 8193)
        else:
            ws.send_json(first)
            if failure == 'odd':
                ws.send_bytes(b'x')
            elif failure == 'oversize':
                ws.send_bytes(b'\x00' * 1026)
            elif failure == 'control':
                ws.send_json({'type': 'not-commit'})
            elif failure == 'superseded':
                ws.send_bytes(b'\x00\x01')
                ws.send_json({'type': 'commit'})
        assert ws.receive_json() == {'type': 'error', 'message': 'Voice capture is unavailable; use typed input.'}
    if failure != 'superseded':
        assert speech.calls == []


@pytest.mark.parametrize('stream', [False, True])
def test_grounded_unavailable_evidence_audio_and_replay_are_honest(http_speech, stream: bool) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    artifact = unavailable_artifact(repo, challenge)
    body = {'revision': challenge['revision'], 'artifact_id': str(artifact.artifact_id)}
    key = str(uuid4())
    url = path + ('/speech/tts-stream' if stream else '/speech/tts')
    auth = {**headers, 'X-Idempotency-Key': key}
    response = client.post(url, json=body, headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert [event['event_type'] for event in events] == ['start', 'chunk', 'complete']
        assert base64.b64decode(events[1]['audio_b64']) == b'\x01\x00' * 8
        assert len({event['playback_id'] for event in events}) == 1
        replay = client.post(url, json=body, headers=auth)
        assert replay.status_code == 409 and replay.json()['code'] == 'STREAM_ALREADY_DELIVERED'
    else:
        assert response.headers['content-type'] == 'audio/wav'
        assert 'x-provider-request-id' not in response.headers  # The double reports no observed provider ID.
        assert response.content == generate_sine_wav_bytes(duration_sec=0.1)
        replay = client.post(url, json=body, headers=auth)
        assert replay.content == response.content
        assert replay.headers['x-playback-id'] == response.headers['x-playback-id']
    assert len(speech.calls) == 1
    assert 'unavailable' in speech.calls[0][2].lower()
    assert artifact.verification_report.curated_cases_run == 0


@pytest.mark.parametrize('stream', [False, True])
def test_hidden_evidence_and_locked_hint_cannot_trigger_speech(http_speech, stream: bool) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    artifact = unavailable_artifact(repo, challenge, reveal=False)
    url = path + ('/speech/tts-stream' if stream else '/speech/tts')
    body = {'revision': challenge['revision'], 'artifact_id': str(artifact.artifact_id)}
    response = client.post(url, json=body, headers={**headers, 'X-Idempotency-Key': str(uuid4())})
    assert response.status_code == 409
    assert response.json()['code'] == 'CHALLENGE_HIDDEN'
    repo.reveal_challenge(challenge['revision']['session_id'], challenge['challenge_id'])
    response = client.post(url, json={**body, 'hint_level': 2}, headers={**headers, 'X-Idempotency-Key': str(uuid4())})
    assert response.status_code == 409 and response.json()['code'] == 'REVISION_CONFLICT'
    assert speech.calls == []


@pytest.mark.parametrize('stream', [False, True])
def test_speech_error_exposes_text_fallback_not_provider_diagnostics(http_speech, stream: bool) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    artifact = unavailable_artifact(repo, challenge)
    speech.mode = 'error'
    response = client.post(path + ('/speech/tts-stream' if stream else '/speech/tts'),
        json={'revision': challenge['revision'], 'artifact_id': str(artifact.artifact_id)},
        headers={**headers, 'X-Idempotency-Key': str(uuid4())})
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert [event['event_type'] for event in events] == ['start', 'error']
        assert events[-1]['error_code'] == 'SPEECH_UNAVAILABLE'
    else:
        assert response.status_code == 503 and response.json()['code'] == 'SPEECH_UNAVAILABLE'
    assert 'Private provider' not in response.text


def test_interrupt_cancel_delete_and_capacity_keep_offline_semantics(http_speech) -> None:
    client, path, headers, challenge, speech, repo = http_speech
    sid = challenge['revision']['session_id']
    for scope, expected in [('INTERRUPT', 'interrupt'), ('TURN', 'cancel')]:
        response = client.post(path + '/cancel', json={'scope': scope, 'reason': 'User stopped audio'},
            headers={**headers, 'X-Idempotency-Key': str(uuid4())})
        assert response.status_code == 200
        assert response.json()['unconfirmed_job_ids'] == []
        assert speech.calls[-1][0] == expected
    capacity = client.get('/api/v1/capacity')
    assert capacity.status_code == 200
    assert capacity.json()['mode'] == 'DEMO'
    assert capacity.json()['custom_code_execution_enabled'] is False
    deletion = client.delete(path, headers={**headers, 'X-Idempotency-Key': str(uuid4())})
    assert deletion.status_code == 200
    assert 'retention policy' in deletion.json()['limitations']
    assert speech.calls[-1][0] == 'delete'
    assert repo.get_session(sid, include_deleted=True).deleted_at is not None
    assert client.get(path, headers=headers).status_code == 410
