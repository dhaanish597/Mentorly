"""Startup regressions: configured speech service without provider calls."""
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.speech.service import SpeechService


def test_application_lifespan_starts_with_configured_speech_limits(tmp_path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "coordinator.db",
        tts_cache_dir=tmp_path / "tts",
        gnani_api_key=None,
        max_stt_seconds_per_session=12,
        max_tts_chars_per_session=150,
        global_daily_call_limit=7,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/meta/health").status_code == 200
        gate = client.app.state.speech.gatekeeper
        assert gate.per_session_stt_seconds == 12
        assert gate.per_session_tts_chars == 150
        assert gate.global_daily_call_limit == 7
        assert gate.get_capacity_status().stt_requests_count == 0
        assert gate.get_capacity_status().tts_requests_count == 0


def test_lifespan_wires_configured_admission_and_retention(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / "ops.db", tts_cache_dir=tmp_path / "tts",
        per_ip_request_limit=2, global_request_limit=10, retention_interval_seconds=1)
    with TestClient(create_app(settings)) as client:
        assert client.app.state.retention._task is not None
        assert client.app.state.admission.per_ip_limit == 2
        assert client.get("/api/v1/meta/health").status_code == 200
        assert client.get("/api/v1/meta/health").status_code == 200
        denied = client.get("/api/v1/meta/health")
        assert denied.status_code == 429
        assert denied.json()["code"] == "RATE_LIMITED"
        assert int(denied.headers["Retry-After"]) > 0


def test_liveness_does_not_claim_unaccepted_execution_is_enabled(tmp_path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "coordinator.db",
        tts_cache_dir=tmp_path / "tts",
        allow_public_custom_code=True,
        isolation_acceptance_file=tmp_path / "missing.json",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/meta/health").json()
        assert health["custom_code_execution_enabled"] is False
        assert health["execution_status"] == "BLOCKED_EXTERNAL"


def test_nonprediction_confirmation_has_no_required_execution_challenge():
    from uuid import uuid4
    from backend.app.models.api_schemas import ConfirmClaimRequest, VerifyRequest
    from backend.app.models.domain import RevisionRef
    revision = RevisionRef(
        session_id=uuid4(), exercise_id="ex2_binary_search", spec_version="v1_sorted_with_duplicates",
        code_version_id=1, code_hash="a" * 64, turn_generation=1,
    )
    claim = {"claim_type": "CLARIFICATION_OR_HINT_REQUEST", "question_text": "Please explain the loop", "extraction_method": "USER_EDITED"}
    request = ConfirmClaimRequest(revision=revision, claim=claim, capture_attempt_id=2)
    assert request.challenge_id is None
    assert request.capture_attempt_id == 2
    verification = VerifyRequest(revision=revision, run_curated_suite=True, generated_cases_target=20)
    assert verification.generated_cases_target == 20


def test_post_dispatch_protocol_failure_retains_uncertain_speech_usage(tmp_path):
    import asyncio
    import pytest
    from backend.app.models.api_schemas import STTRequest
    from backend.app.speech.audio_utils import generate_sine_wav_bytes
    from backend.app.speech.gatekeeper import SpeechGatekeeper
    from backend.app.speech.gnani_adapter import GnaniSpeechAdapter

    async def invalid_browser_frame(_request, _audio):
        raise ValueError("Malformed frame after provider contact")

    async def scenario():
        gate = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"), db_path=tmp_path / "quota.db")
        try:
            with pytest.raises(ValueError, match="Malformed frame"):
                await gate.execute_stt(
                    STTRequest(session_id="quota-regression"),
                    generate_sine_wav_bytes(duration_sec=0.1),
                    transcribe_fn=invalid_browser_frame,
                )
            capacity = gate.get_capacity_status()
            assert capacity.uncertain_requests_count == 1
            assert capacity.stt_seconds_uncertain > 0
            assert capacity.active_requests == 0
        finally:
            gate._conn.close()
    asyncio.run(scenario())


def test_live_ws_schema_error_after_pcm_is_uncertain_not_http_rejection(tmp_path):
    import asyncio
    import json
    import pytest
    from contextlib import asynccontextmanager
    from backend.app.models.api_schemas import STTRequest
    from backend.app.speech.gatekeeper import SpeechGatekeeper
    from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError
    from backend.app.speech.ws_streamer import GnaniWebSocketSTTRelay

    async def scenario():
        sent = asyncio.Event()
        class Connection:
            count = 0
            async def recv(self):
                self.count += 1
                if self.count == 1:
                    return json.dumps({"type": "connected", "request_id": "provider-test"})
                await sent.wait()
                return json.dumps({"type": "transcript", "text": 42, "is_final": True})
            async def send(self, value):
                if isinstance(value, bytes):
                    sent.set()
        @asynccontextmanager
        async def connect(*_args, **_kwargs):
            yield Connection()
        async def frames():
            yield b"\1\0" * 512
        gate = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"), db_path=tmp_path / "ws.db")
        try:
            relay = GnaniWebSocketSTTRelay(gate, connect_fn=connect, pace_frames=False)
            with pytest.raises(GnaniTransportError) as caught:
                await relay.transcribe_live(STTRequest(session_id="schema-failure"), frames())
            assert sent.is_set()
            assert caught.value.status_code is None
            assert caught.value.retryable is False
            assert gate.get_capacity_status().uncertain_requests_count == 1
            assert gate.get_capacity_status().stt_seconds_uncertain == 30
        finally:
            gate._conn.close()
    asyncio.run(scenario())


def test_tts_post_dispatch_schema_failure_retains_uncertain_usage(tmp_path):
    import asyncio
    import pytest
    from backend.app.models.api_schemas import TTSRequest
    from backend.app.speech.gatekeeper import SpeechGatekeeper
    from backend.app.speech.gnani_adapter import GnaniSpeechAdapter

    async def scenario():
        adapter = GnaniSpeechAdapter(api_key="test-only")
        async def invalid_tts_schema(*_args, **_kwargs):
            raise ValueError("Malformed complete event after provider audio")
        adapter.synthesize_tts = invalid_tts_schema
        gate = SpeechGatekeeper(adapter, db_path=tmp_path / "tts-quota.db")
        try:
            with pytest.raises(ValueError, match="Malformed complete event"):
                await gate.execute_tts(TTSRequest(session_id="tts-schema-failure", text="Hello."))
            capacity = gate.get_capacity_status()
            assert capacity.uncertain_requests_count == 1
            assert capacity.tts_chars_uncertain > 0
            assert capacity.active_requests == 0
        finally:
            gate._conn.close()
    asyncio.run(scenario())


def test_deterministic_mechanism_accepts_normalized_sliding_window():
    from backend.app.coaching.claim_extractor import extract_claim_deterministic
    claim = extract_claim_deterministic("I use a sliding window and track its sum.", known_identifiers=["sliding_window"])
    assert claim.claim_type.value == "INVARIANT_OR_MECHANISM_CLAIM"


def test_learner_exception_hints_do_not_claim_infrastructure_unavailability():
    from uuid import uuid4
    from backend.app.models.domain import EvidenceArtifact, RevisionRef, ExecutionObservation, VerificationReport
    from backend.app.models.enums import HintLevel
    from backend.app.coaching.templates import render_deterministic_hint
    revision = RevisionRef(session_id=uuid4(), exercise_id="ex2_binary_search", spec_version="v1_sorted_with_duplicates", code_version_id=1, code_hash="a"*64, turn_generation=1)
    artifact = EvidenceArtifact(
        artifact_id=uuid4(), revision=revision, challenge_id=uuid4(), canonical_input={"nums":[], "target":5}, case_hash="b"*64,
        actual_observation=ExecutionObservation(kind="EXCEPTION",error_type="IndexError",duration_ms=1), reference_output=-1,
        prediction_status="NOT_EVALUATED", verification_report=VerificationReport(status="EXECUTION_ERROR",curated_cases_run=0,curated_cases_total=1,generated_cases_run=0,generated_cases_target=0,terminal_reason="Learner exception",runtime_version="protocol-fixture"),
    )
    for level in HintLevel:
        hint = render_deterministic_hint(artifact, hint_level=level)
        assert "IndexError" in hint.display_text
        assert "Keep your current code" not in hint.display_text


def test_package_manifest_declares_voice_runtime_and_migration_data():
    from pathlib import Path
    import tomllib
    backend = Path(__file__).resolve().parents[2]
    project = tomllib.loads((backend / "pyproject.toml").read_text())
    runtime = project["project"]["dependencies"]
    assert any(item.startswith("httpx") for item in runtime)
    assert any(item.startswith("websockets") for item in runtime)
    assert any(item.startswith("python-multipart") for item in runtime)
    data = project["tool"]["setuptools"]["package-data"]
    assert "case_manifest.json" in data["backend.app.exercises"]
    assert "migrations/*.sql" in data["backend.app.db"]


def test_speech_service_defaults_remain_compatible(tmp_path):
    service = SpeechService(db_path=tmp_path / "speech.db", cache_dir=tmp_path / "tts")
    try:
        assert service.gatekeeper.per_session_stt_seconds == 180
        assert service.gatekeeper.per_session_tts_chars == 4000
    finally:
        service.close()
