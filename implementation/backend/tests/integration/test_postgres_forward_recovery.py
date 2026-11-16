"""Forward restart rehearsal against a dedicated disposable PostgreSQL database."""
import hashlib
import io
import wave
import json
import os
from contextlib import closing
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from psycopg import sql

from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.main import create_app
from backend.app.repo_learning.audio_storage import store_audio
from backend.app.repo_learning.ingest import golden
from backend.app.repo_learning.service import create, queue
from backend.tests.integration.test_postgres_runtime import _workspace

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='Dedicated disposable PostgreSQL DSN required')


def table_digests(target):
    """Hash the complete multiset of every ordinary authoritative schema table."""
    result = {}
    with target.connect() as db:
        names = db.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (target.schema,)).fetchall()
        for (name,) in names:
            query = sql.SQL("SELECT count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text, '[]') FROM {}.{} t").format(sql.Identifier(target.schema), sql.Identifier(name))
            count, rows = db.execute(query).fetchone()
            result[name] = (count, hashlib.sha256(rows.encode()).hexdigest())
    return result


def test_separate_app_forward_restart_preserves_all_tables(tmp_path):
    import psycopg
    target = PostgresTarget(DSN, 'viva_forward_' + uuid4().hex)
    settings = Settings(_env_file=None, database_url=SecretStr(DSN), database_schema=target.schema,
                        database_path=tmp_path/'unused.sqlite', tts_cache_dir=tmp_path/'cache',
                        env='test', gnani_api_key=None, groq_api_key=None, retention_interval_seconds=86400)
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 160)
    audio_bytes = audio.getvalue()
    try:
        with TestClient(create_app(settings)) as client:
            wid, token, headers = _workspace(client)
            recovery = 'r' * 48
            auth = {'Authorization': 'Bearer ' + token, 'X-Idempotency-Key': str(uuid4())}
            assert client.put(f'/api/v1/studio/workspaces/{wid}/recovery', headers=auth, json={'recovery_token': recovery}).status_code == 200
            lesson = client.post('/api/v1/learning/sessions', headers=headers, json={'lesson_id': 'dsa-complexity', 'mode': 'practice', 'language_mode': 'en-IN'})
            assert lesson.status_code == 200, lesson.text
            sid = lesson.json()['id']
            with closing(open_connection(target)) as db:
                answer = json.loads(db.execute('SELECT lesson_json FROM learning_sessions WHERE id=?', (sid,)).fetchone()[0])['question']['correct_answer']
            completed = client.post(f'/api/v1/learning/sessions/{sid}/answers', headers=headers, json={'expected_epoch': lesson.json()['epoch'], 'question_id': lesson.json()['question']['id'], 'answer': answer})
            assert completed.status_code == 200, completed.text
            coding = client.post('/api/v1/sessions', json={'exercise_id': 'ex1_shortest_subarray', 'spec_version': 'v1_positive_only'})
            assert coding.status_code == 200, coding.text
            coding = coding.json()
            updated = client.put(f"/api/v1/sessions/{coding['session_id']}/code", headers={'Authorization': 'Bearer '+coding['session_token'], 'X-Idempotency-Key': str(uuid4())}, json={'code': coding['starter_code']+'\n# synthetic recovery revision', 'expected_code_version_id': 1, 'client_edit_sequence': 1})
            assert updated.status_code == 200, updated.text
            files, coverage = golden('REPO-EXP-01')
            snap = queue(target, wid, 'golden_curated', 'REPO-EXP-01')
            create(target, wid, 'golden_curated', files, coverage, snap)
            cb = client.post('/api/v1/codebase-learning/sessions', headers=headers, json={'snapshot_id': snap, 'repo_url': 'https://example.test/repo', 'repo_name': 'synthetic'})
            assert cb.status_code == 201, cb.text
            cbid = cb.json()['session_id']
            turn = client.post(f'/api/v1/codebase-learning/sessions/{cbid}/turns', headers=headers, json={'text': 'I am learning this synthetic repository.'})
            assert turn.status_code == 200, turn.text
            with closing(open_connection(target)) as db:
                db.execute('BEGIN IMMEDIATE')
                audio_url = store_audio(db, cbid, audio_bytes)
                db.execute('UPDATE codebase_learning_messages SET audio_path=? WHERE session_id=? AND sequence=1', (audio_url, cbid))
                db.execute("INSERT INTO codebase_speech_usage VALUES(?,?,?,?,?,?,?,?)", ('synthetic-usage', cbid, 'TTS', 0, 12, 1, 'COMMITTED', '2026-01-01T00:00:00+00:00'))
                db.commit()
            assert client.get(audio_url, headers=headers).content == audio_bytes
        before = table_digests(target)
        assert len(before) > 50
        assert all(before[name][0] for name in ('code_versions', 'learning_sessions', 'workspace_recovery', 'codebase_learning_messages', 'codebase_speech_usage'))
        with TestClient(create_app(settings)) as recovered:
            assert table_digests(target) == before
            assert recovered.get(f'/api/v1/learning/sessions/{sid}', headers=headers).json()['state'] == 'completed'
            assert len(recovered.get(f'/api/v1/codebase-learning/sessions/{cbid}', headers=headers).json()['messages']) >= 3
            assert recovered.get(audio_url, headers=headers).content == audio_bytes
            restored = recovered.get(f"/api/v1/sessions/{coding['session_id']}", headers={'Authorization': 'Bearer '+coding['session_token']})
            assert restored.status_code == 200 and '# synthetic recovery revision' in restored.json()['source_code']
            replacement = 'n' * 48
            resumed = recovered.post(f'/api/v1/studio/workspaces/{wid}/recover', json={'recovery_token': recovery, 'workspace_token': replacement})
            assert resumed.status_code == 200, resumed.text
            archive = recovered.get(f'/api/v1/studio/workspaces/{wid}/archive', headers={'Authorization': 'Bearer '+replacement})
            assert archive.status_code == 200 and archive.json()['data']['learning_sessions'][0]['id'] == sid
        # Read requests legitimately update admission counters after the full-table comparison.
    finally:
        with psycopg.connect(DSN, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(target.schema)))
