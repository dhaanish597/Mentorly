"""Existing source-bound voice assertions with a real PostgreSQL database.

Provider audio is synthetic. The SQL/UOW, source ownership, quota accounting and
HTTP contracts remain real; no remote provider or learner code is invoked.
"""

import inspect
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend.app.db.migrations import open_connection
from backend.app.db.repository import repository_for
from backend.app.orchestration.state_machine import CoordinatorStateMachine
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gnani_adapter import AssembledTTSSynthesis
from backend.tests.integration import test_product_module_voice_api as module_voice
from backend.tests.integration import test_voice_conversation as conversation_voice
from backend.tests.integration.test_postgres_product_parity import contracts
from backend.tests.integration.test_postgres_runtime import runtime as runtime  # noqa: PLC0414 - pytest fixture re-export


@pytest.fixture
def postgres_module_voice(runtime, tmp_path, monkeypatch):
    _, target = runtime
    # Inject the real database into the existing fixture rather than duplicating
    # its private source rows and mock adapter expectations.
    monkeypatch.setattr(module_voice, "apply_migrations", lambda path: None)
    monkeypatch.setattr(
        module_voice, "open_connection", lambda path: open_connection(target)
    )
    from backend.app.repo_learning import rederive, service

    # Existing SQLite fixtures stringify their DB path in private setup helpers.
    # Inject the PG connection at that seam; their service SQL stays unchanged.
    monkeypatch.setattr(
        service, "open_connection", lambda path: open_connection(target)
    )
    monkeypatch.setattr(
        rederive, "open_connection", lambda path: open_connection(target)
    )
    fixture = module_voice.voice.__wrapped__(tmp_path, monkeypatch)
    value = next(fixture)
    value.path = target
    value.app.state.settings.database_path = target
    try:
        yield value
    finally:
        fixture.close()


@pytest.mark.parametrize("name", contracts(module_voice, "voice"))
def test_existing_module_voice_contract_against_postgres(
    postgres_module_voice, name, monkeypatch
):
    fn = getattr(module_voice, name)
    args = {"voice": postgres_module_voice, "monkeypatch": monkeypatch}
    fn(**{key: args[key] for key in inspect.signature(fn).parameters})


@pytest.fixture
def postgres_conversation(runtime, monkeypatch):
    app_client, target = runtime
    app = app_client.app
    created_response = app_client.post(
        "/api/v1/sessions",
        json={
            "exercise_id": "ex1_shortest_subarray",
            "spec_version": "v1_positive_only",
        },
    )
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()
    repo = repository_for(target)
    machine = CoordinatorStateMachine(repo)
    sid = created["session_id"]
    turn, _ = repo.create_or_reuse_turn(
        session_id=sid,
        code_version_id=created["revision"]["code_version_id"],
        challenge_id=None,
        transport_mode="TEXT",
        state="AWAITING_CLAIM_CONFIRMATION",
        raw_transcript="I shrink the window to keep the shortest answer.",
        normalized_transcript="I shrink the window to keep the shortest answer.",
        claim_json=json.dumps(
            {
                "claim_type": "INVARIANT_OR_MECHANISM_CLAIM",
                "mechanism_summary": "Shrinking keeps the shortest answer.",
                "extraction_method": "DETERMINISTIC",
            }
        ),
    )
    calls = []
    wav = generate_sine_wav_bytes(duration_sec=0.1)

    async def synthesize(session_id, text, revision, **kwargs):
        calls.append((session_id, text, revision, kwargs))
        return AssembledTTSSynthesis(
            request_id="synthetic",
            cache_key="synthetic",
            cache_hit=False,
            wav_bytes=wav,
            events=[],
            speakable_chunks=[text],
            total_chars_billed=len(text),
            latency_ms=1,
        )

    monkeypatch.setattr(app.state.speech, "synthesize", synthesize)
    payload = {
        "revision": machine.build_revision_ref(sid).model_dump(mode="json"),
        "turn_id": turn.id,
    }
    headers = {"Authorization": "Bearer " + created["session_token"]}
    path = f"/api/v1/sessions/{sid}/speech/conversation"

    def post(body=None, key=None, authorized=True):
        return app_client.post(
            path,
            json=payload if body is None else body,
            headers={
                **(headers if authorized else {}),
                "X-Idempotency-Key": key or str(uuid4()),
            },
        )

    yield SimpleNamespace(
        app=app,
        client=app_client,
        repo=repo,
        machine=machine,
        sid=sid,
        turn=turn,
        calls=calls,
        wav=wav,
        payload=payload,
        post=post,
        path=path,
        headers=headers,
    )


@pytest.mark.parametrize("name", contracts(conversation_voice, "conversation"))
def test_existing_dsa_voice_contract_against_postgres(
    postgres_conversation, name, monkeypatch
):
    fn = getattr(conversation_voice, name)
    args = {"conversation": postgres_conversation, "monkeypatch": monkeypatch}
    fn(**{key: args[key] for key in inspect.signature(fn).parameters})
