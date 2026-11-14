"""Interview boundaries with a real migrated SQLite database, no provider/sandbox."""
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.db.migrations import apply_migrations, open_connection


@pytest.fixture
def harness(tmp_path):
    from backend.app.interviews.routes import router
    path = tmp_path / 'interviews.db'
    apply_migrations(path)
    app = FastAPI()
    app.state.settings = SimpleNamespace(database_path=path)
    app.include_router(router, prefix='/api/v1')
    wid, other = str(uuid.uuid4()), str(uuid.uuid4())
    from backend.app.studio.security import digest_token
    with open_connection(path) as conn:
        for owner, token in ((wid, 'w'*48), (other, 'z'*48)):
            conn.execute('INSERT INTO studio_workspaces VALUES(?,?,?,?,NULL)',
                         (owner, digest_token(token), '2026-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00'))
    with TestClient(app) as client:
        yield client, path, {'X-Workspace-Id': wid, 'X-Workspace-Token': 'w'*48}, {'X-Workspace-Id': other, 'X-Workspace-Token': 'z'*48}


def create(client, headers, **changes):
    body = {'type': 'dsa', 'difficulty': 'beginner', 'topics': [], 'duration_minutes': 15, 'language_mode': 'en-IN'}
    return client.post('/api/v1/interviews/sessions', headers=headers, json={**body, **changes})


def test_catalog_auth_configuration_and_no_ownership_input(harness):
    c, _, h, _ = harness
    assert c.get('/api/v1/interviews/config').status_code == 401
    config = c.get('/api/v1/interviews/config', headers=h).json()
    assert set(config['types']) == {'dsa', 'cs', 'system_design', 'codebase_defense'}
    assert config['camera_default'] is False
    catalog = c.get('/api/v1/interviews/catalog', headers=h).json()
    assert catalog['dsa_exercises'] and all(x['exercise_id'] for x in catalog['dsa_exercises'])
    assert 'starter_code' not in json.dumps(catalog)
    for changes in ({'user_id': 'arbitrary'}, {'duration_minutes': 0}, {'topics': ['unknown']}, {'language_mode': 'unknown'}, {'difficulty': 'unknown'}):
        assert create(c, h, **changes).status_code == 422
    response = create(c, h)
    assert response.status_code == 200, response.text
    assert 'workspace_id' not in response.json()
    assert response.json()['question']['source_refs'][0]['exercise_id']


def test_answer_cas_neutral_followup_and_cross_workspace_isolation(harness):
    c, path, h, other = harness
    initial = create(c, h).json()
    sid = initial['id']
    url = f'/api/v1/interviews/sessions/{sid}'
    assert c.get(url, headers=other).status_code == 404
    assert c.post(url+'/answers', headers=other, json={'expected_epoch': 1, 'answer': 'x'}).status_code == 404
    assert c.post(url+'/answers', headers=h, json={'expected_epoch': 0, 'answer': 'x'}).status_code == 409
    res = c.post(url+'/answers', headers=h, json={'expected_epoch': 1, 'answer': 'I would scan the values.', 'code': 'raise RuntimeError("must not execute")'})
    assert res.status_code == 200, res.text
    view = res.json()
    assert view['epoch'] == 2 and view['acknowledgement']['text'] == 'Answer recorded.'
    assert view['question']['kind'] == 'followup'
    assert view['question']['parent_id'] == initial['question']['id']
    assert 'reason' in view['question']['text'].lower()
    for secret in ('rubric', 'indicators', 'score', 'model_answer', 'correctness'):
        assert secret not in view
    assert c.post(url+'/answers', headers=h, json={'expected_epoch': 1, 'answer': 'duplicate'}).status_code == 409
    with open_connection(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM interview_answers WHERE session_id=?', (sid,)).fetchone()[0] == 1
    with TestClient(c.app) as restarted:
        assert restarted.get(url, headers=h).json() == c.get(url, headers=h).json()


def test_followups_depend_on_actual_answer_and_each_policy_differs(harness):
    c, _, h, _ = harness
    texts = []
    for kind in ('dsa', 'cs', 'system_design', 'codebase_defense'):
        s = create(c, h, type=kind).json()
        r = c.post(f"/api/v1/interviews/sessions/{s['id']}/answers", headers=h,
                   json={'expected_epoch': 1, 'answer': 'because the premise is measured; for example I checked 10 cases; O(n) time; failure recovery; src/main.py:12; tradeoff latency'}).json()
        texts.append(r['question']['text'])
    assert len(set(texts)) == 4
    a, b = create(c, h).json(), create(c, h).json()
    def answer(s, text):
        return c.post(f"/api/v1/interviews/sessions/{s['id']}/answers", headers=h, json={'expected_epoch': 1, 'answer': text}).json()['question']['text']
    assert answer(a, 'scan') != answer(b, 'because state is retained; example [1,2]; O(n) time')


def test_finish_is_immutable_evidence_anchored_and_only_emits_once(harness):
    c, path, h, _ = harness
    s = create(c, h).json()
    url = f"/api/v1/interviews/sessions/{s['id']}"
    answer = 'because I retain an invariant; example [1,2]; O(n) time; empty input returns zero'
    c.post(url+'/answers', headers=h, json={'expected_epoch': 1, 'answer': answer, 'code': 'return 0'})
    assert c.post(url+'/finish', headers=h, json={'expected_epoch': 1}).status_code == 409
    report = c.post(url+'/finish', headers=h, json={'expected_epoch': 2}).json()
    assert report['completion_reason'] == 'finished'
    assert report['technical_correctness']['status'] == 'unassessed_no_execution_evidence'
    assert report['semantic_validity']['status'] == 'unassessed'
    assert report['psychology']['status'] == 'not_assessed'
    for row in report['answers']:
        for indicator in row['indicators']:
            assert 0 <= indicator['value'] <= indicator['maximum'] == 1
            for excerpt in indicator['excerpts']:
                assert row['answer'][excerpt['start']:excerpt['end']] == excerpt['text']
    assert report['recommendations'] and all(r['exercise_id'] for r in report['recommendations'])
    assert c.post(url+'/finish', headers=h, json={'expected_epoch': 2}).json() == report
    assert c.get(url, headers=h).json()['report'] == report
    assert c.post(url+'/answers', headers=h, json={'expected_epoch': 3, 'answer': 'late'}).status_code == 409
    with open_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM interview_events WHERE session_id=? AND event_type='interview.completed'", (s['id'],)).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('UPDATE interview_reports SET report_json=? WHERE session_id=?', ('{}', s['id']))


def test_timeout_persists_report_rejects_late_answer_and_is_replayable(harness):
    c, path, h, _ = harness
    s = create(c, h).json()
    url = f"/api/v1/interviews/sessions/{s['id']}"
    with open_connection(path) as conn:
        conn.execute("UPDATE interview_sessions SET deadline_at='2000-01-01T00:00:00+00:00' WHERE id=?", (s['id'],))
    view = c.post(url+'/answers', headers=h, json={'expected_epoch': 1, 'answer': 'too late'}).json()
    assert view['state'] == 'completed'
    assert view['report']['completion_reason'] == 'timeout'
    assert view['report']['answers'] == []
    assert c.get(url, headers=h).json()['report'] == view['report']
    assert c.post(url+'/finish', headers=h, json={'expected_epoch': 1}).json() == view['report']


def test_concurrent_answers_only_one_wins_and_client_cannot_forge_evidence(harness):
    c, _, h, _ = harness
    s = create(c, h).json()
    url = f"/api/v1/interviews/sessions/{s['id']}/answers"
    assert c.post(url, headers=h, json={'expected_epoch': 1, 'answer': 'x', 'execution_evidence': {'passed': True}}).status_code == 422
    assert c.post(url, headers=h, json={'expected_epoch': 1, 'answer': '   '}).status_code == 422
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: c.post(url, headers=h, json={'expected_epoch': 1, 'answer': f'answer {i}'}).status_code, range(2)))
    assert sorted(results) == [200, 409]
