"""Honest model availability, durable accounting and idempotent fallback."""
import asyncio
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.main import create_app
from backend.app.studio.feedback import DIMENSIONS


@pytest.fixture
def feedback_client(tmp_path):
    settings = Settings(_env_file=None, database_url=None, database_path=tmp_path/'feedback.db',
                        tts_cache_dir=tmp_path/'cache', env='test', gnani_api_key=None,
                        groq_api_key='mock-model-account', llm_model='mock-model')
    with TestClient(create_app(settings)) as client:
        workspace, session = str(uuid.uuid4()), str(uuid.uuid4())
        result = client.post('/api/v1/studio/workspaces', json={'workspace_id':workspace, 'workspace_token':'w'*48},
                             headers={'X-Idempotency-Key':'workspace-availability'})
        assert result.status_code == 200
        result = client.post('/api/v1/studio/sessions', json={'workspace_id':workspace, 'session_id':session,
                             'session_token':'s'*48, 'mode':'dsa_to_system_bridge', 'posture':'teaching', 'scenario_id':'SD-BR-01'},
                             headers={'Authorization':'Bearer '+'w'*48, 'X-Idempotency-Key':'session-availability'})
        assert result.status_code == 200
        path = f'/api/v1/studio/sessions/{session}'
        headers = {'Authorization':'Bearer '+'s'*48, 'X-Idempotency-Key':'turn-availability'}
        result = client.post(path+'/turns', json={'epoch':1, 'text':'Consider one writer and compare cache misses.'}, headers=headers)
        assert result.status_code == 200
        yield client, settings, path, result.json()['turn_id']


def request(client, path, turn, key='feedback-availability', allow_external=True):
    return client.post(path+'/feedback', json={'epoch':1, 'turn_id':turn, 'allow_external':allow_external},
                       headers={'Authorization':'Bearer '+'s'*48, 'X-Idempotency-Key':key})


def candidate():
    return {'question':'Which cache miss would you measure first?', 'uncertainty':'No correctness proof is available.',
            'criteria':[{'dimension':dimension, 'status':'abstained_insufficient_signal', 'evidence_ids':[]} for dimension in DIMENSIONS]}


def model_client(monkeypatch, behavior):
    calls = []
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(kwargs)
            if isinstance(behavior, Exception): raise behavior
            if behavior == 'deadline':
                await asyncio.sleep(2)
            content = json.dumps(candidate()) if behavior == 'success' else '{invalid'
            return httpx.Response(429 if behavior == 'rate' else 200,
                                  json={'choices':[{'message':{'content':content}}]}, request=httpx.Request('POST',url))
    monkeypatch.setattr('backend.app.studio.feedback.httpx.AsyncClient', Client)
    return calls


@pytest.mark.parametrize('behavior,status', [
    ('success','MODEL_ASSISTED'), ('invalid','MODEL_INVALID_RESPONSE'), ('rate','MODEL_RATE_LIMITED'),
    (httpx.ReadTimeout('private-model-body'),'MODEL_TIMEOUT'), (httpx.ConnectError('private-secret-detail'),'MODEL_UNAVAILABLE'),
    ('deadline','MODEL_TIMEOUT'),
])
def test_model_failures_are_explicit_and_replay_does_not_dispatch(feedback_client, monkeypatch, behavior, status):
    client, settings, path, turn = feedback_client
    settings.llm_feedback_timeout_ms = 100
    calls = model_client(monkeypatch, behavior)
    result = request(client,path,turn)
    assert result.status_code == 200, result.text
    assert result.json()['model_status'] == status
    assert result.json()['status'] in ('unassessed','abstained_insufficient_signal')
    assert result.json()['source'] == ('model_assisted' if status == 'MODEL_ASSISTED' else 'deterministic_fallback')
    assert 'private-' not in result.text and 'mock-model-account' not in result.text
    replay = request(client,path,turn)
    assert replay.json() == result.json() and len(calls) == 1
    with open_connection(settings.database_path) as db:
        row = db.execute('SELECT status FROM studio_model_usage').fetchone()
        assert row['status'] == ('UNCERTAIN' if status in ('MODEL_TIMEOUT','MODEL_UNAVAILABLE') else 'COMMITTED')


@pytest.mark.parametrize('kind,status', [('disabled','MODEL_DISABLED'), ('no-model','MODEL_NOT_CONFIGURED'),
                                        ('no-key','MODEL_NOT_CONFIGURED'), ('no-consent','DETERMINISTIC_FALLBACK')])
def test_unconfigured_or_unconsented_model_never_dispatches(feedback_client, monkeypatch, kind, status):
    client, settings, path, turn = feedback_client
    if kind == 'disabled': settings.llm_provider = 'deterministic'
    if kind == 'no-model': settings.llm_model = ''
    if kind == 'no-key': settings.groq_api_key = None
    calls = model_client(monkeypatch, 'success')
    result = request(client,path,turn,allow_external=kind!='no-consent')
    assert result.status_code == 200 and result.json()['model_status'] == status
    assert calls == []
    with open_connection(settings.database_path) as db:
        assert db.execute('SELECT count(*) FROM studio_model_usage').fetchone()[0] == 0


def test_exhausted_model_budget_returns_honest_fallback(feedback_client, monkeypatch):
    client, settings, path, turn = feedback_client
    settings.model_daily_call_limit = 1
    calls = model_client(monkeypatch, 'success')
    assert request(client,path,turn).json()['model_status'] == 'MODEL_ASSISTED'
    result = request(client,path,turn,key='different-feedback-key')
    assert result.status_code == 200 and result.json()['model_status'] == 'MODEL_RATE_LIMITED'
    assert result.json()['source'] == 'deterministic_fallback' and len(calls) == 1
