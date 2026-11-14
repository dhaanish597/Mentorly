"""Learning contract: real SQLite, workspace capabilities, deterministic evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import sqlite3
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.studio.routes import router as studio_router


def application(path):
    from backend.app.learning.routes import router

    apply_migrations(path)
    app = FastAPI()
    app.state.settings = SimpleNamespace(database_path=path)
    app.include_router(studio_router, prefix='/api/v1')
    app.include_router(router, prefix='/api/v1')
    return app


def workspace(client, suffix='w'):
    wid = str(uuid.uuid4())
    token = suffix * 48
    response = client.post('/api/v1/studio/workspaces', json={
        'workspace_id': wid, 'workspace_token': token,
    }, headers={'X-Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    return {'X-Workspace-Id': wid, 'X-Workspace-Token': token}


@pytest.fixture
def learning(tmp_path):
    path = tmp_path / 'learning.db'
    with TestClient(application(path)) as client:
        yield client, workspace(client), path


def start(client, headers, lesson='dsa-complexity'):
    response = client.post('/api/v1/learning/sessions', headers=headers, json={
        'lesson_id': lesson, 'mode': 'practice', 'language_mode': 'english',
    })
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, headers, session, answer):
    return client.post(f"/api/v1/learning/sessions/{session['id']}/answers", headers=headers,
                       json={'expected_epoch': session['epoch'],
                             'question_id': session['question']['id'], 'answer': answer})


def test_catalog_public_substantive_and_no_answer_keys(learning):
    client, _, _ = learning
    response = client.get('/api/v1/learning/catalog')
    assert response.status_code == 200
    catalog = response.json()
    assert catalog['version'] == '1.0.0'
    assert {t['module'] for t in catalog['tracks']} == {'dsa', 'cs', 'aptitude', 'system_design'}
    lessons = [l for t in catalog['tracks'] for l in t['lessons']]
    assert len(lessons) >= 40
    assert len({l['id'] for l in lessons}) == len(lessons)
    for lesson in lessons:
        assert set(lesson) == {'id', 'title', 'prerequisites', 'difficulty', 'estimated_minutes',
                               'objectives', 'explanation', 'example', 'hints', 'practice_url', 'question'}
        assert len(lesson['explanation']) >= 150
        assert len(lesson['example']) >= 70
        assert len(lesson['objectives']) >= 2
        assert len(lesson['hints']) == 3
        assert set(lesson['question']) == {'id', 'prompt', 'options'}
    assert 'correct_answer' not in response.text and 'accepted_answers' not in response.text
    assert any(l['practice_url'].startswith('/practice/') for l in lessons)
    assert any(l['practice_url'].startswith('/studio?') for l in lessons)


def test_empty_progress_is_honest_and_authenticated(learning):
    client, headers, _ = learning
    assert client.get('/api/v1/learning/progress').status_code == 422
    response = client.get('/api/v1/learning/progress', headers=headers)
    assert response.status_code == 200
    progress = response.json()
    for field in ('lessons_completed', 'attempts', 'topics_mastered', 'practice_sessions',
                  'interviews_completed', 'study_seconds', 'streak'):
        assert progress[field] == 0
    assert progress['completed_lesson_ids'] == progress['achievements'] == progress['recent_activity'] == []
    assert progress['recommendations'] and all(r['reason'] for r in progress['recommendations'])
    invalid = {**headers, 'X-Workspace-Token': 'wrong'}
    assert client.get('/api/v1/learning/progress', headers=invalid).status_code == 401


def test_wrong_answer_then_correct_atomic_completion_and_dedup(learning):
    client, headers, path = learning
    session = start(client, headers)
    assert session['state'] == 'active' and session['answer_count'] == 0 and session['deadline'] is None
    wrong = submit(client, headers, session, 'O(1)')
    assert wrong.status_code == 200, wrong.text
    session = wrong.json()
    assert session['feedback']['correct'] is False and session['state'] == 'active'
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    assert progress['attempts'] == 1 and progress['lessons_completed'] == 0
    correct = submit(client, headers, session, 'O(n)')
    assert correct.status_code == 200, correct.text
    completed = correct.json()
    assert completed['state'] == 'completed' and completed['answer_count'] == 2
    assert completed['feedback']['correct'] is True
    assert completed['report']['explanation_rubric']['status'] == 'unassessed'
    assert completed['report']['mastery_awarded'] is False
    assert submit(client, headers, completed, 'O(n)').status_code == 409
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    assert progress['lessons_completed'] == 1 and progress['attempts'] == 2
    assert progress['topics_mastered'] == 0 and progress['streak'] == 1
    assert progress['completed_lesson_ids'] == ['dsa-complexity']
    assert progress['achievements'][0]['earned_at'] and progress['achievements'][0]['source_event']
    with closing(open_connection(path)) as conn:
        assert conn.execute('SELECT count(*) FROM learning_answers').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM learning_events WHERE kind=\'lesson.completed\'').fetchone()[0] == 1
    second = start(client, headers)
    assert submit(client, headers, second, 'O(n)').status_code == 200
    again = client.get('/api/v1/learning/progress', headers=headers).json()
    assert again['lessons_completed'] == 1
    assert len(again['achievements']) == len(progress['achievements'])


def test_capability_isolation_and_stale_epoch(learning):
    client, headers, _ = learning
    other = workspace(client, 'z')
    session = start(client, headers)
    url = f"/api/v1/learning/sessions/{session['id']}"
    assert client.get(url, headers=other).status_code == 404
    assert submit(client, other, session, 'O(n)').status_code == 404
    wrong = submit(client, headers, session, 'wrong').json()
    assert wrong['epoch'] == session['epoch'] + 1
    assert submit(client, headers, session, 'O(n)').status_code == 409
    assert client.post(url + '/hints', headers=headers, json={'expected_epoch': session['epoch']}).status_code == 409
    assert client.get(url, headers=headers).json() == wrong


def test_concurrent_answers_only_one_commits(learning):
    client, headers, path = learning
    session = start(client, headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: submit(client, headers, session, 'O(n)').status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    with closing(open_connection(path)) as conn:
        assert conn.execute('SELECT count(*) FROM learning_answers').fetchone()[0] == 1


def test_hints_bounds_and_restart_preserve_history(learning):
    client, headers, _ = learning
    session = start(client, headers)
    url = f"/api/v1/learning/sessions/{session['id']}"
    for level in range(1, 4):
        response = client.post(url + '/hints', headers=headers, json={'expected_epoch': session['epoch']})
        assert response.status_code == 200, response.text
        session = response.json()
        assert session['hint_count'] == level and session['coach_messages'][-1]['kind'] == 'hint'
    assert client.post(url + '/hints', headers=headers, json={'expected_epoch': session['epoch']}).status_code == 409
    for _ in range(5):
        response = submit(client, headers, session, 'not correct')
        assert response.status_code == 200
        session = response.json()
    assert session['state'] == 'exhausted'
    assert submit(client, headers, session, 'O(n)').status_code == 409
    restarted = client.post(url + '/restart', headers=headers,
                            json={'expected_epoch': session['epoch']})
    assert restarted.status_code == 200, restarted.text
    fresh = restarted.json()
    assert fresh['id'] == session['id'] and fresh['epoch'] > session['epoch']
    assert fresh['state'] == 'active' and fresh['answer_count'] == fresh['hint_count'] == 0
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    assert progress['attempts'] == 5 and progress['lessons_completed'] == 0


def test_resume_survives_application_restart(learning):
    client, headers, path = learning
    session = submit(client, headers, start(client, headers), 'wrong').json()
    with TestClient(application(path)) as restarted:
        assert restarted.get(f"/api/v1/learning/sessions/{session['id']}", headers=headers).json() == session
        assert submit(restarted, headers, session, 'O(n)').json()['state'] == 'completed'


@pytest.mark.parametrize('body', [
    {'lesson_id': 'missing', 'mode': 'practice', 'language_mode': 'english'},
    {'lesson_id': 'dsa-complexity', 'mode': 'interview', 'language_mode': 'english'},
    {'lesson_id': 'dsa-complexity', 'mode': 'practice', 'language_mode': ''},
    {'lesson_id': 'dsa-complexity', 'mode': 'practice', 'language_mode': 'x' * 81},
    {'lesson_id': 'dsa-complexity', 'mode': 'practice', 'language_mode': 'english', 'completed': True},
])
def test_creation_rejects_unknown_and_caller_generated_completion(learning, body):
    client, headers, _ = learning
    assert client.post('/api/v1/learning/sessions', headers=headers, json=body).status_code in (404, 422)


@pytest.mark.parametrize('patch', [
    {'answer': ''}, {'answer': ' '}, {'answer': 'x' * 2001}, {'answer': 3},
    {'expected_epoch': 0}, {'expected_epoch': True}, {'question_id': 'another'},
    {'correct': True}, {'source_event': 'fake'},
])
def test_answer_bounds_and_unknown_question_do_not_write(learning, patch):
    client, headers, path = learning
    session = start(client, headers)
    body = {'expected_epoch': session['epoch'], 'question_id': session['question']['id'], 'answer': 'O(n)', **patch}
    response = client.post(f"/api/v1/learning/sessions/{session['id']}/answers", headers=headers, json=body)
    assert response.status_code in (409, 422)
    with closing(open_connection(path)) as conn:
        assert conn.execute('SELECT count(*) FROM learning_answers').fetchone()[0] == 0


def test_event_source_guards_atomic_rollback_and_deletion_cascade(learning):
    client, headers, path = learning
    session = start(client, headers)
    with closing(open_connection(path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO learning_events(id,workspace_id,session_id,run,kind,source,answer_id,study_seconds,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         ('fake', headers['X-Workspace-Id'], session['id'], 1, 'lesson.completed', 'caller', None, 0,
                          datetime.now(timezone.utc).isoformat()))
        conn.execute("CREATE TRIGGER reject_learning_completion BEFORE INSERT ON learning_events WHEN NEW.kind='lesson.completed' BEGIN SELECT RAISE(ABORT,'test rollback'); END;")
    with TestClient(application(path), raise_server_exceptions=False) as safe:
        response = submit(safe, headers, session, 'O(n)')
        assert response.status_code == 500
    with closing(open_connection(path)) as conn:
        assert conn.execute('SELECT count(*) FROM learning_answers').fetchone()[0] == 0
        assert conn.execute('SELECT epoch FROM learning_sessions').fetchone()[0] == session['epoch']
        conn.execute('DROP TRIGGER reject_learning_completion')
    assert submit(client, headers, session, 'O(n)').status_code == 200
    with closing(open_connection(path)) as conn:
        conn.execute('DELETE FROM studio_workspaces WHERE id=?', (headers['X-Workspace-Id'],))
        for table in ('learning_sessions', 'learning_answers', 'learning_events', 'learning_achievements'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_prerequisite_recommendations_and_expired_capability(learning):
    client, headers, path = learning
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    assert 'dsa-binary-search' not in {r['lesson_id'] for r in progress['recommendations']}
    session = start(client, headers)
    assert any(r['lesson_id'] == session['lesson_id'] and 'Resume' in r['reason']
               for r in client.get('/api/v1/learning/progress', headers=headers).json()['recommendations'])
    with closing(open_connection(path)) as conn:
        conn.execute("UPDATE studio_workspaces SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (headers['X-Workspace-Id'],))
    assert client.get('/api/v1/learning/progress', headers=headers).status_code == 401
