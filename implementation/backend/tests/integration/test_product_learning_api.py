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
    app.state.settings = SimpleNamespace(database_target=path,database_path=path)
    app.include_router(studio_router, prefix='/api/v1')
    app.include_router(router, prefix='/api/v1')
    from backend.app.interviews.routes import router as interviews_router
    from backend.app.learning.service import record_interview_completion
    app.include_router(interviews_router, prefix='/api/v1')
    app.state.interview_completion_hook = record_interview_completion
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


def test_real_workspace_soft_delete_purges_learning_evidence(learning):
    client, headers, path = learning
    session = start(client, headers)
    assert submit(client, headers, session, 'O(n)').status_code == 200
    response = client.delete(f"/api/v1/studio/workspaces/{headers['X-Workspace-Id']}",
                             headers={'Authorization': 'Bearer ' + headers['X-Workspace-Token'],
                                      'X-Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    with closing(open_connection(path)) as conn:
        for table in ('learning_sessions', 'learning_answers', 'learning_events',
                      'learning_achievements', 'learning_external_events', 'learning_evidence_achievements'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_recommendations_prioritize_resume_then_unverified_revision(learning):
    client, headers, _ = learning
    session = start(client, headers, 'apt-percent')
    recommendations = client.get('/api/v1/learning/progress', headers=headers).json()['recommendations']
    assert recommendations[0]['lesson_id'] == 'apt-percent'
    for _ in range(5):
        session = submit(client, headers, session, 'wrong').json()
    recommendations = client.get('/api/v1/learning/progress', headers=headers).json()['recommendations']
    assert recommendations[0]['lesson_id'] == 'apt-percent'
    assert 'unverified' in recommendations[0]['reason']


def test_consistency_badge_requires_three_consecutive_active_days_not_views(learning, monkeypatch):
    import backend.app.learning.service as service
    client, headers, path = learning
    base = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    for offset in (2, 1, 0):
        instant = (base - timedelta(days=offset)).isoformat()
        monkeypatch.setattr(service, 'utc_now', lambda value=instant: value)
        session = start(client, headers)
        assert submit(client, headers, session, 'wrong').status_code == 200
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    badge = next(b for b in progress['achievements'] if b['id'] == 'three_study_days')
    assert badge['source_event'] and progress['streak'] == 3
    assert progress['lessons_completed'] == 0 and progress['topics_mastered'] == 0
    with closing(open_connection(path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO learning_evidence_achievements(workspace_id,id,title,earned_at,source_event,source) VALUES(?,?,?,?,?,?)",
                         (headers['X-Workspace-Id'], 'forged', 'Fake', instant, 'fake', 'learning_engine'))


def test_observed_study_seconds_are_server_derived_and_capped(learning, monkeypatch):
    import backend.app.learning.service as service
    client, headers, _ = learning
    base = datetime.now(timezone.utc)
    monkeypatch.setattr(service, 'utc_now', lambda: base.isoformat())
    session = start(client, headers)
    monkeypatch.setattr(service, 'utc_now', lambda: (base + timedelta(seconds=17)).isoformat())
    session = submit(client, headers, session, 'wrong').json()
    assert client.get('/api/v1/learning/progress', headers=headers).json()['study_seconds'] == 17
    monkeypatch.setattr(service, 'utc_now', lambda: (base + timedelta(seconds=1017)).isoformat())
    assert submit(client, headers, session, 'O(n)').status_code == 200
    assert client.get('/api/v1/learning/progress', headers=headers).json()['study_seconds'] == 317


def test_engine_source_cannot_forge_completion_without_correct_owned_answer(learning):
    client, headers, path = learning
    session = start(client, headers)
    with closing(open_connection(path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO learning_events(id,workspace_id,session_id,run,kind,source,answer_id,study_seconds,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         ('fake', headers['X-Workspace-Id'], session['id'], 1, 'lesson.completed',
                          'learning_engine', None, 0, datetime.now(timezone.utc).isoformat()))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE learning_sessions SET state='completed' WHERE id=?", (session['id'],))


def test_server_enforces_owned_prerequisite_completion_before_creation(learning):
    client, headers, path = learning
    body = {'lesson_id': 'dsa-binary-search', 'mode': 'practice', 'language_mode': 'english'}
    assert client.post('/api/v1/learning/sessions', headers=headers, json=body).status_code == 409
    other = workspace(client, 'z')
    array = start(client, other, 'dsa-complexity')
    assert submit(client, other, array, 'O(n)').status_code == 200
    array = start(client, other, 'dsa-arrays')
    assert submit(client, other, array, '5').status_code == 200
    assert client.post('/api/v1/learning/sessions', headers=headers, json=body).status_code == 409
    with closing(open_connection(path)) as conn:
        assert conn.execute('SELECT count(*) FROM learning_sessions WHERE workspace_id=?',
                            (headers['X-Workspace-Id'],)).fetchone()[0] == 0
    prerequisite = start(client, headers)
    assert submit(client, headers, prerequisite, 'O(n)').status_code == 200
    array = start(client, headers, 'dsa-arrays')
    assert submit(client, headers, array, '5').status_code == 200
    assert client.post('/api/v1/learning/sessions', headers=headers, json=body).status_code == 200


def test_first_interview_award_uses_durable_source_and_deletion_cascades(learning):
    from backend.app.learning.service import record_interview_completion
    client, headers, path = learning
    created = client.post('/api/v1/interviews/sessions', headers=headers, json={
        'type': 'cs', 'difficulty': 'beginner', 'topics': ['networking'],
        'duration_minutes': 5, 'language_mode': 'en-IN'})
    assert created.status_code == 200, created.text
    session = created.json()
    with closing(open_connection(path)) as conn:
        with pytest.raises(ValueError):
            record_interview_completion(conn, headers['X-Workspace-Id'], {'session_id': session['id']})
    finished = client.post(f"/api/v1/interviews/sessions/{session['id']}/finish", headers=headers,
                           json={'expected_epoch': session['epoch']})
    assert finished.status_code == 200, finished.text
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    assert progress['interviews_completed'] == 1 and progress['topics_mastered'] == 0
    badge = next(b for b in progress['achievements'] if b['id'] == 'first_interview')
    assert badge['source_event'].startswith('interview:')
    assert any(r['lesson_id'] == 'cs-dns' and 'unassessed' in r['reason']
               for r in progress['recommendations'])
    with closing(open_connection(path)) as conn:
        with pytest.raises(ValueError):
            record_interview_completion(conn, 'another-workspace', {'session_id': session['id']})
        assert record_interview_completion(conn, headers['X-Workspace-Id'], {'session_id': session['id']}) == badge['source_event']
        assert conn.execute('SELECT count(*) FROM learning_evidence_achievements').fetchone()[0] == 1
        conn.execute('DELETE FROM interview_sessions WHERE id=?', (session['id'],))
        assert conn.execute('SELECT count(*) FROM learning_external_events').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM learning_evidence_achievements').fetchone()[0] == 0


def test_interview_completion_activity_keeps_report_session_id_and_deletion_removes_it(learning):
    client, headers, path = learning
    other = workspace(client, 'z')
    body = {'type': 'cs', 'difficulty': 'beginner', 'topics': ['networking'],
            'duration_minutes': 5, 'language_mode': 'en-IN'}
    created = client.post('/api/v1/interviews/sessions', headers=headers, json=body)
    assert created.status_code == 200, created.text
    first = created.json()
    url = f"/api/v1/interviews/sessions/{first['id']}"
    finished = client.post(url + '/finish', headers=headers,
                           json={'expected_epoch': first['epoch']})
    assert finished.status_code == 200, finished.text
    second = client.post('/api/v1/interviews/sessions', headers=headers, json=body)
    assert second.status_code == 200, second.text
    assert second.json()['id'] != first['id'] and second.json()['report'] is None
    report_url = f"/api/v1/interviews/reports/{first['id']}"
    assert client.get(report_url, headers=headers).json() == finished.json()
    assert client.get(report_url, headers=other).status_code == 404

    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    completions = [item for item in progress['recent_activity']
                   if item['type'] == 'interview.completed']
    assert progress['interviews_completed'] == 1
    assert len(completions) == 1
    assert completions[0]['session_id'] == first['id']
    foreign = client.get('/api/v1/learning/progress', headers=other).json()
    assert foreign['interviews_completed'] == 0 and foreign['recent_activity'] == []

    with closing(open_connection(path)) as conn:
        conn.execute('DELETE FROM interview_sessions WHERE id=?', (first['id'],))
    assert client.get(report_url, headers=headers).status_code == 404
    assert client.get(url, headers=headers).status_code == 404
    after = client.get('/api/v1/learning/progress', headers=headers).json()
    assert after['interviews_completed'] == 0
    assert not any(item['session_id'] == first['id'] for item in after['recent_activity'])
    assert not any(badge['id'] == 'first_interview' for badge in after['achievements'])
    assert client.get(f"/api/v1/interviews/sessions/{second.json()['id']}",
                      headers=headers).json()['state'] == 'active'


def test_completed_lesson_report_and_activity_survive_new_session_until_deletion(learning):
    client, headers, path = learning
    other = workspace(client, 'z')
    first = start(client, headers)
    completed = submit(client, headers, first, 'O(n)')
    assert completed.status_code == 200, completed.text
    assert completed.json()['state'] == 'completed'
    assert completed.json()['report']['lesson_completed'] is True
    second = start(client, headers)
    assert second['id'] != first['id'] and second['report'] is None
    url = f"/api/v1/learning/sessions/{first['id']}"
    recovered = client.get(url, headers=headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json() == completed.json()
    assert client.get(url, headers=other).status_code == 404
    progress = client.get('/api/v1/learning/progress', headers=headers).json()
    completions = [item for item in progress['recent_activity']
                   if item['type'] == 'lesson.completed']
    assert progress['lessons_completed'] == 1 and len(completions) == 1
    assert completions[0]['session_id'] == first['id']
    assert client.get('/api/v1/learning/progress', headers=other).json()['recent_activity'] == []

    with closing(open_connection(path)) as conn:
        conn.execute('DELETE FROM learning_sessions WHERE id=?', (first['id'],))
    assert client.get(url, headers=headers).status_code == 404
    after = client.get('/api/v1/learning/progress', headers=headers).json()
    assert after['lessons_completed'] == 0 and after['completed_lesson_ids'] == []
    assert not any(item['session_id'] == first['id'] for item in after['recent_activity'])
    assert client.get(f"/api/v1/learning/sessions/{second['id']}",
                      headers=headers).json()['state'] == 'active'


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
