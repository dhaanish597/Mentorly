"""Repository corrections use synthetic source, capabilities and network doubles only."""
import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.repo_learning import ingest, routes, service
from backend.app.studio.security import digest_token


@pytest.fixture
def context(tmp_path):
    db = str(tmp_path / 'repo.db')
    apply_migrations(db)
    with open_connection(db) as conn:
        for owner in ('a', 'b'):
            conn.execute('INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES (?,?,?,?)',
                         (owner, digest_token(owner * 40), '2026-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00'))
    app = FastAPI()
    app.state.settings = SimpleNamespace(database_path=db)
    app.include_router(routes.router, prefix='/api/v1')
    return db, TestClient(app)


def headers(owner='a', key=None):
    result = {'X-Workspace-Id': owner, 'X-Workspace-Token': owner * 40}
    return {**result, 'X-Idempotency-Key': key} if key is not None else result


def zip_bytes(source):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('app.py', source)
    return output.getvalue()


def imported(client, owner='a', key=None):
    return client.post('/api/v1/repos/ingest', headers=headers(owner, key),
                       files={'file': ('repo.zip', zip_bytes('def first():\n return 1\n\ndef second():\n return 2\n'), 'application/zip')})


def citations(client, sid, owner='a'):
    results = client.get(f'/api/v1/repos/{sid}/search', headers=headers(owner), params={'q': 'def'}).json()['results']
    return [{key: row[key] for key in ('path', 'symbol', 'start_line', 'end_line', 'chunk_hash')} for row in results]


@pytest.mark.parametrize('name,text,secrets', [
    ('config.json', '{"nested":{"password":"synthetic_json_password","safe":1}}\n', ['synthetic_json_password']),
    ('config.json', '{"pass\\u0077ord":"synthetic_escaped_password"}\n', ['synthetic_escaped_password']),
    ('config.json', '{\n  "pass\\u0077ord": "synthetic_pretty_escaped",\n  "safe": 1\n}\n', ['synthetic_pretty_escaped']),
    ('config.yaml', 'password: |-\n  synthetic_block_one\n  synthetic_block_two\nnext: safe\n', ['synthetic_block_one', 'synthetic_block_two']),
    ('config.yaml', '- password: |\n    synthetic_list_block\n- name: safe\n', ['synthetic_list_block']),
    ('config.yaml', 'password:\n- synthetic_sequence_secret\nnext: safe\n', ['synthetic_sequence_secret']),
    ('config.yaml', '"password": first_line_secret\n  second_line_secret\nnext: safe\n', ['first_line_secret', 'second_line_secret']),
    ('config.json', '{"password": unsupported_secret_value}\n', ['unsupported_secret_value']),
    ('config.py', "config = {'password': 'synthetic_python_value'}\n", ['synthetic_python_value']),
])
def test_structured_secret_values_are_redacted_before_files_and_fts(context, name, text, secrets):
    _, client = context
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(name, text)
    result = client.post('/api/v1/repos/ingest', headers=headers(), files={'file': ('repo.zip', output.getvalue(), 'application/zip')})
    assert result.status_code == 202
    sid = result.json()['snapshot_id']
    indexed = client.get(f'/api/v1/repos/{sid}/files', headers=headers(), params={'path': name}).json()['content']
    assert indexed.count('\n') == text.count('\n')
    for value in secrets:
        assert value not in indexed
        assert not client.get(f'/api/v1/repos/{sid}/search', headers=headers(), params={'q': value}).json()['results']


def test_forged_deflate_size_and_crc_cannot_hide_decoded_overshoot():
    import struct
    import zlib
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('forged.py', b'a' * (1024 * 1024))
    raw = bytearray(output.getvalue())
    central = raw.index(b'PK\x01\x02')
    struct.pack_into('<I', raw, 14, zlib.crc32(b'a'))
    struct.pack_into('<I', raw, 22, 1)
    struct.pack_into('<I', raw, central + 16, zlib.crc32(b'a'))
    struct.pack_into('<I', raw, central + 24, 1)
    with pytest.raises(ingest.ImportFailure):
        ingest.unpack(bytes(raw))


def test_unproved_zip_compression_methods_fail_closed():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr('payload.txt', b'synthetic payload')
    with pytest.raises(ingest.ImportFailure):
        ingest.unpack(output.getvalue())


@pytest.mark.parametrize('idle,total,delay', [(0.005, 0.2, 0.05), (0.2, 0.005, 0.002)])
def test_ingress_idle_and_total_deadlines_release_handler(monkeypatch, idle, total, delay):
    from fastapi import HTTPException
    monkeypatch.setattr(routes, 'BODY_IDLE_TIMEOUT', idle, raising=False)
    monkeypatch.setattr(routes, 'BODY_TOTAL_TIMEOUT', total, raising=False)
    class Request:
        headers = {}
        async def stream(self):
            for _ in range(10):
                await asyncio.sleep(delay)
                yield b'x'
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.bounded_body(Request()))
    assert error.value.status_code == 408


def test_ingress_timeout_releases_actual_admission_slot(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from backend.app.operations.admission import AdmissionMiddleware
    monkeypatch.setattr(routes, 'BODY_IDLE_TIMEOUT', 0.001)
    counts = {'acquired': 0, 'released': 0}
    class Controller:
        def try_acquire(self):
            counts['acquired'] += 1
            return True
        def admit(self, scope, **kwargs):
            return SimpleNamespace(allowed=True)
        def release(self):
            counts['released'] += 1
    async def handler(scope, receive, send):
        try:
            await routes.bounded_body(Request(scope, receive))
        except HTTPException as error:
            await JSONResponse({'detail': error.detail}, status_code=error.status_code)(scope, receive, send)
    async def scenario():
        output = []
        async def stalled_receive():
            await asyncio.sleep(0.05)
            return {'type': 'http.request', 'body': b'', 'more_body': True}
        async def send(message):
            output.append(message)
        await AdmissionMiddleware(handler, Controller())({'type': 'http', 'path': '/api/v1/repos/ingest', 'headers': [], 'method': 'POST'}, stalled_receive, send)
        assert output[0]['status'] == 408
    asyncio.run(scenario())
    assert counts == {'acquired': 1, 'released': 1}


def test_deleted_queued_snapshot_never_dispatches_public_fetch(context, monkeypatch):
    db, _ = context
    sid = service.queue(db, 'a', 'public_git_url')
    fetched = []
    async def fake_fetch(locator):
        fetched.append(locator)
        return zip_bytes('x=1\n')
    monkeypatch.setattr(routes, 'fetch_public_archive', fake_fetch)
    service.delete(db, 'a', sid)
    asyncio.run(routes.run_import(db, 'a', sid, 'public_git_url', 'https://github.com/a/b', None))
    assert fetched == []


def test_snapshot_delete_cancels_inflight_archive_task(context, monkeypatch):
    db, _ = context
    sid = service.queue(db, 'a', 'public_git_url')
    async def scenario():
        started = asyncio.Event()
        canceled = asyncio.Event()
        async def fake_fetch(locator):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()
        monkeypatch.setattr(routes, 'fetch_public_archive', fake_fetch)
        task = asyncio.create_task(routes.run_import(db, 'a', sid, 'public_git_url', 'https://github.com/a/b', None))
        await asyncio.wait_for(started.wait(), 1)
        service.delete(db, 'a', sid)
        try:
            done, _ = await asyncio.wait([task], timeout=0.05)
            assert task in done, 'Deletion must cancel the existing network task, not only fence publication'
            assert canceled.is_set()
            from backend.app.repo_learning import lifecycle
            assert not lifecycle.active_imports(db)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_synthetic_secret_fixtures_do_not_embed_scanner_patterns():
    from pathlib import Path
    from scripts.check_secrets import _SECRET_PATTERNS
    source = Path(__file__).with_name('test_repo_learning.py').read_text(encoding='utf-8')
    assert not any(pattern.search(source) for pattern in _SECRET_PATTERNS), 'Synthetic fixtures must construct recognizers, not embed secret-shaped literals'


def test_chunks_follow_real_nested_symbol_ranges_without_amplification(context):
    db, _ = context
    source = '# preface\n\nclass Worker:\n @staticmethod\n def run():\n  def inner():\n   return 9\n  return inner()\n\ndef other():\n return 3\n'
    sid = service.create(db, 'a', 'zip_upload', {'app.py': source}, {'total': 1})['snapshot_id']
    with open_connection(db) as conn:
        chunks = [dict(row) for row in conn.execute('SELECT * FROM repo_chunks WHERE snapshot_id=? ORDER BY start_line', (sid,))]
    assert {row['symbol'] for row in chunks} >= {'Worker', 'Worker.run', 'Worker.run.inner', 'other'}
    assert ''.join(row['text'] for row in chunks) == source
    symbols = {item['name']: item for item in ingest.structure('app.py', source)['symbols']}
    for row in chunks:
        assert row['text'] == ''.join(source.splitlines(keepends=True)[row['start_line'] - 1:row['end_line']])
        assert row['chunk_hash'] == ingest.digest(row['text'].encode())
        if row['symbol']:
            symbol = symbols[row['symbol']]
            assert symbol['start_line'] <= row['start_line'] <= row['end_line'] <= symbol['end_line']
        assert row['end_line'] - row['start_line'] < 80


def test_long_symbol_continuations_keep_name_and_quota_charge(context, monkeypatch):
    db, _ = context
    source = '# header\n' + 'def long_function():\n' + ''.join(f' value_{i} = {i}\n' for i in range(190))
    sid = service.create(db, 'a', 'zip_upload', {'long.py': source}, {'total': 1})['snapshot_id']
    with open_connection(db) as conn:
        rows = conn.execute('SELECT symbol,start_line,end_line FROM repo_chunks WHERE snapshot_id=? ORDER BY start_line', (sid,)).fetchall()
        charge = service._usage(conn, 'a')[2]
    assert all(row['symbol'] == 'long_function' for row in rows[1:])
    assert rows[0]['end_line'] == 1
    assert charge == service._snapshot_charge({'long.py': source})


@pytest.mark.parametrize('path,source', [('calc.ts', 'export const compute = (value: number) => value + 1;\n'), ('calc.js', 'const compute = (value) => value + 1;\n')])
def test_static_arrow_symbols_are_named_with_exact_source_grounding(context, path, source):
    db, _ = context
    info = ingest.structure(path, source)
    assert info['status'] == 'parsed'
    assert any(item['name'] == 'compute' for item in info['symbols'])
    sid = service.create(db, 'a', 'zip_upload', {path: source}, {'total': 1})['snapshot_id']
    results = service.search(db, 'a', sid, 'compute')['results']
    assert results[0]['symbol'] == 'compute'
    assert service.validate_citation(db, 'a', sid, results[0]) == source


@pytest.mark.parametrize('key', [None, 'import-retry-01'])
def test_ingest_replay_is_stable_before_quota_and_does_not_schedule_twice(context, monkeypatch, key):
    db, client = context
    calls = []
    original = routes.run_import
    async def tracked(*args):
        calls.append(args[2])
        await original(*args)
    monkeypatch.setattr(routes, 'run_import', tracked)
    monkeypatch.setattr(service, 'WORKSPACE_SNAPSHOT_LIMIT', 1)
    first = imported(client, key=key)
    retry = imported(client, key=key)
    assert first.status_code == retry.status_code == 202
    assert retry.json() == first.json()
    assert calls == [first.json()['snapshot_id']]
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_snapshots').fetchone()[0] == 1


def test_ingest_explicit_key_conflict_and_owner_isolation(context):
    _, client = context
    first = imported(client, key='same-client-key')
    conflicting = client.post('/api/v1/repos/ingest', headers=headers(key='same-client-key'),
                              json={'source_kind': 'golden_curated', 'source_locator': 'REPO-EXP-02'})
    assert conflicting.status_code == 409
    foreign = imported(client, owner='b', key='same-client-key')
    assert foreign.status_code == 202
    assert foreign.json()['snapshot_id'] != first.json()['snapshot_id']


@pytest.mark.parametrize('key', [None, 'evidence-retry-01'])
def test_evidence_and_decision_replays_conflicts_and_quota(context, monkeypatch, key):
    db, client = context
    sid = imported(client).json()['snapshot_id']
    citation = citations(client, sid)[0]
    endpoint = f'/api/v1/repos/{sid}/evidence'
    payload = {'topic': 'responsibility', 'observed_code': [citation]}
    first = client.post(endpoint, headers=headers(key=key), json=payload)
    retry = client.post(endpoint, headers=headers(key=key), json=payload)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    if key:
        assert client.post(endpoint, headers=headers(key=key), json={**payload, 'topic': 'different'}).status_code == 409
    decision = {'topic': 'design', 'evidence_card_ids': [first.json()['evidence_card_id']], 'inferred_rationale': 'A hypothesis', 'learner_alternative': 'Another design'}
    endpoint = f'/api/v1/repos/{sid}/decisions'
    first = client.post(endpoint, headers=headers(key=key), json=decision)
    retry = client.post(endpoint, headers=headers(key=key), json=decision)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    if key:
        assert client.post(endpoint, headers=headers(key=key), json={**decision, 'inferred_rationale': 'Different'}).status_code == 409
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_evidence_cards').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM repo_decisions').fetchone()[0] == 1


def test_concurrent_retries_create_one_snapshot_and_one_evidence_record(context):
    from concurrent.futures import ThreadPoolExecutor
    db, client = context
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: imported(client, key='concurrent-import'), range(3)))
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()['snapshot_id'] for response in responses}) == 1
    sid = responses[0].json()['snapshot_id']
    payload = {'topic': 'flow', 'observed_code': [citations(client, sid)[0]]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(f'/api/v1/repos/{sid}/evidence', headers=headers(key='concurrent-card'), json=payload), range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()['evidence_card_id'] for response in responses}) == 1
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_snapshots').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM repo_evidence_cards').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM repo_idempotency').fetchone()[0] == 2


def test_retry_owner_and_global_byte_limits_roll_back_side_effects(context, monkeypatch):
    from backend.app.repo_learning import idempotency
    db, client = context
    first = imported(client, key='bounded-import')
    monkeypatch.setattr(idempotency, 'MAX_OWNER_RECORDS', 1)
    assert imported(client, key='bounded-import').json() == first.json()
    sid = first.json()['snapshot_id']
    assert client.post(f'/api/v1/repos/{sid}/evidence', headers=headers(), json={'topic': 'flow', 'observed_code': [citations(client, sid)[0]]}).status_code == 429
    monkeypatch.setattr(idempotency, 'MAX_GLOBAL_BYTES', 1, raising=False)
    assert imported(client, owner='b').status_code == 429
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_snapshots').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM repo_evidence_cards').fetchone()[0] == 0
    monkeypatch.setattr(idempotency, 'MAX_GLOBAL_BYTES', 1000000)
    monkeypatch.setattr(idempotency, 'MAX_OWNER_BYTES', 1, raising=False)
    assert imported(client, owner='b').status_code == 429
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_snapshots').fetchone()[0] == 1


def test_retry_records_and_evidence_fts_are_privacy_deleted(context):
    db, client = context
    sid = imported(client, key='privacy-retry-key').json()['snapshot_id']
    client.post(f'/api/v1/repos/{sid}/evidence', headers=headers(key='privacy-card-key'),
                json={'topic': 'flow', 'observed_code': [citations(client, sid)[0]]})
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_idempotency WHERE snapshot_id=?', (sid,)).fetchone()[0] == 2
    assert client.delete(f'/api/v1/repos/{sid}', headers=headers()).status_code == 204
    with open_connection(db) as conn:
        for table in ('repo_idempotency', 'repo_evidence_cards', 'repo_files', 'repo_chunks', 'repo_chunks_fts'):
            assert conn.execute(f'SELECT count(*) FROM {table} WHERE snapshot_id=?', (sid,)).fetchone()[0] == 0
    new = imported(client, key='privacy-retry-key').json()['snapshot_id']
    assert new != sid


@pytest.mark.parametrize('key', ['', 'short', 'x' * 129, 'bad key spaces'])
def test_bad_idempotency_keys_rejected_without_side_effects(context, key):
    db, client = context
    assert imported(client, key=key).status_code == 400
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_snapshots').fetchone()[0] == 0


def start_defense(db, client, sid, mode='repo_exploration'):
    with open_connection(db) as conn:
        conn.execute("INSERT INTO studio_sessions(id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,repo_snapshot_id,created_at,expires_at) VALUES ('session','a',?,?,'teaching','REPO-DEF-02','1',?,'2026-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00')", (digest_token('s' * 40), mode, sid))
    head = {**headers(), 'X-Session-Token': 's' * 40}
    response = client.post(f'/api/v1/repos/{sid}/defense/start', headers=head, json={'studio_session_id': 'session'})
    assert response.status_code == 200
    return head


def answer_body(phase, citation, excerpt):
    kinds = {'map': 'observed_responsibility', 'derive': 'constraint_hypothesis', 'defend': 'tradeoff', 'reflect': 'changed_requirement'}
    body = {'studio_session_id': 'session', 'expected_phase': phase, 'answer': f'{phase} learner statement', 'citations': [citation],
            'evidence_links': [{'kind': kinds[phase], 'claim': f'{phase} claim', 'citation': citation, 'excerpt': excerpt}]}
    if phase == 'reflect':
        body = {**body, 'changed_requirement': 'Support a second output', 'learner_alternative': 'Replace the fixed output', 'unknowns': ['Author motivation is unknown']}
    return body


def test_persistent_defense_prompts_publish_validated_native_voice_events(context):
    from backend.app.studio.speech import event_text
    from fastapi import HTTPException
    import json
    db, client = context
    sid = imported(client).json()['snapshot_id']
    head = start_defense(db, client, sid)
    with open_connection(db) as conn:
        rows = conn.execute("SELECT sequence,payload_json FROM studio_events WHERE session_id='session' AND event_type='coach.action' ORDER BY sequence").fetchall()
        assert len(rows) == 1
        initial = json.loads(rows[0]['payload_json'])
        assert initial['validated'] is True and initial['epoch'] == 1
        assert initial['phase'] == 'map' and initial['snapshot_id'] == sid
        assert initial['source'] == 'authored_repo_defense'
    client.post(f'/api/v1/repos/{sid}/defense/start', headers=head, json={'studio_session_id': 'session'})
    c = citations(client, sid)[0]
    body = {'studio_session_id': 'session', 'expected_phase': 'map', 'answer': 'synthetic learner prose', 'citations': [c]}
    result = client.post(f'/api/v1/repos/{sid}/defense/answer', headers=head, json=body)
    assert result.status_code == 200
    retry = client.post(f'/api/v1/repos/{sid}/defense/answer', headers=head, json=body)
    assert retry.json() == result.json()
    with open_connection(db) as conn:
        session = conn.execute("SELECT * FROM studio_sessions WHERE id='session'").fetchone()
        rows = conn.execute("SELECT sequence,payload_json FROM studio_events WHERE session_id='session' AND event_type='coach.action' ORDER BY sequence").fetchall()
        assert len(rows) == 2 and session['epoch'] == 2
        payload = json.loads(rows[-1]['payload_json'])
        assert payload['validated'] is True and payload['epoch'] == session['epoch']
        assert payload['citations'] == [c]
        assert 'synthetic learner prose' not in payload['text']
        assert payload['phase'] == 'derive' and 'invariant' in payload['text']
        assert event_text(conn, session, 2, rows[-1]['sequence']) == payload['text']
        with pytest.raises(HTTPException):
            event_text(conn, session, 1, rows[0]['sequence'])


def test_phase_specific_links_fresh_transfer_and_unassessed_replay(context):
    db, client = context
    sid = imported(client).json()['snapshot_id']
    choices = citations(client, sid)
    first = next(c for c in choices if c['symbol'] == 'first')
    second = next(c for c in choices if c['symbol'] == 'second')
    head = start_defense(db, client, sid)
    endpoint = f'/api/v1/repos/{sid}/defense/answer'
    for phase in ('map', 'derive', 'defend'):
        body = answer_body(phase, first, 'return 1')
        wrong = {**body, 'evidence_links': [{**body['evidence_links'][0], 'kind': 'changed_requirement'}]}
        assert client.post(endpoint, headers=head, json=wrong).status_code == 409
        response = client.post(endpoint, headers={**head, 'X-Idempotency-Key': f'answer-{phase}-key'}, json=body)
        assert response.status_code == 200, response.text
        assert client.post(endpoint, headers={**head, 'X-Idempotency-Key': f'answer-{phase}-key'}, json=body).json() == response.json()
        assert client.post(endpoint, headers={**head, 'X-Idempotency-Key': f'answer-{phase}-key'}, json={**body, 'answer': 'changed'}).status_code == 409
    # The same relevant source span may legitimately support a changed design.
    fresh = answer_body('reflect', first, 'return 1')
    result = client.post(endpoint, headers=head, json=fresh)
    assert result.status_code == 200, result.text
    summary = result.json()
    assert summary['phase'] == 'complete'
    assert summary['synthesis']['assessment_status'] == 'unassessed'
    assert summary['synthesis']['author_intent'] == 'unknown'
    assert summary['history'][-1]['changed_requirement'] == fresh['changed_requirement']
    assert summary['history'][-1]['evidence_links'] == fresh['evidence_links']
    assert client.post(endpoint, headers=head, json=fresh).json() == summary


@pytest.mark.parametrize('via_api', [True, False])
def test_snapshot_deletion_purges_only_its_authored_prompt_events(context, via_api):
    import json
    db, client = context
    sid = imported(client).json()['snapshot_id']
    head = start_defense(db, client, sid)
    with open_connection(db) as conn:
        conn.execute("UPDATE studio_sessions SET expires_at='2020-01-01T00:00:00+00:00' WHERE id='session'")
        conn.execute("INSERT INTO studio_events VALUES ('session',2,'learner.note',?,'2026-01-01T00:00:00+00:00')", (json.dumps({'text': 'retain the unrelated learner transcript'}),))
        conn.execute("INSERT INTO studio_events VALUES ('session',3,'coach.action',?,'2026-01-01T00:00:00+00:00')", (json.dumps({'source': 'authored_scenario', 'snapshot_id': sid, 'text': 'retain unrelated coaching'}),))
    if via_api:
        assert client.delete(f'/api/v1/repos/{sid}', headers=headers()).status_code == 204
    else:
        with open_connection(db) as conn:
            conn.execute('DELETE FROM repo_snapshots WHERE id=?', (sid,))
    with open_connection(db) as conn:
        rows = conn.execute("SELECT payload_json FROM studio_events WHERE session_id='session' ORDER BY sequence").fetchall()
        assert len(rows) == 2
        assert [json.loads(row['payload_json']).get('source') for row in rows] == [None, 'authored_scenario']
        assert conn.execute('SELECT count(*) FROM repo_idempotency WHERE snapshot_id=?', (sid,)).fetchone()[0] == 0


def test_authored_project_defense_requires_live_requirement_proposal_only(context):
    db, client = context
    sid = imported(client).json()['snapshot_id']
    c = citations(client, sid)[0]
    head = start_defense(db, client, sid, mode='project_defense')
    endpoint = f'/api/v1/repos/{sid}/defense/answer'
    for phase in ('map', 'derive', 'defend'):
        body = {'studio_session_id': 'session', 'expected_phase': phase, 'answer': f'{phase} statement', 'citations': [c]}
        assert client.post(endpoint, headers=head, json=body).status_code == 200
    body = {'studio_session_id': 'session', 'expected_phase': 'reflect', 'answer': 'A proposed change', 'citations': [c]}
    assert client.post(endpoint, headers=head, json=body).status_code == 409
    for field in ('changed_requirement', 'learner_alternative'):
        invalid = {**body, 'changed_requirement': 'Require a configurable result', 'learner_alternative': 'Parameterize the result', field: None}
        assert client.post(endpoint, headers=head, json=invalid).status_code == 409
    complete = {**body, 'changed_requirement': 'Require a configurable result', 'learner_alternative': 'Parameterize the result'}
    response = client.post(endpoint, headers=head, json=complete)
    assert response.status_code == 200
    assert response.json()['synthesis']['assessment_status'] == 'unassessed'


def test_link_requires_selected_citation_and_exact_excerpt(context):
    db, client = context
    sid = imported(client).json()['snapshot_id']
    first, second = citations(client, sid)[:2]
    head = start_defense(db, client, sid)
    endpoint = f'/api/v1/repos/{sid}/defense/answer'
    body = answer_body('map', first, service.validate_citation(db, 'a', sid, first).strip())
    fabricated = {**body, 'evidence_links': [{**body['evidence_links'][0], 'excerpt': 'fabricated source'}]}
    assert client.post(endpoint, headers=head, json=fabricated).status_code == 409
    unselected = {**body, 'evidence_links': [{**body['evidence_links'][0], 'citation': second}]}
    assert client.post(endpoint, headers=head, json=unselected).status_code == 409
    assert client.post(endpoint, headers=head, json=body).status_code == 200
    with open_connection(db) as conn:
        assert conn.execute('SELECT count(*) FROM repo_defense_answers').fetchone()[0] == 1
        conn.execute("DELETE FROM studio_sessions WHERE id='session'")
        assert conn.execute('SELECT count(*) FROM repo_idempotency WHERE studio_session_id IS NOT NULL').fetchone()[0] == 0


def test_stage_prompt_names_selected_span_and_transfer_obligations(context):
    _, client = context
    sid = imported(client).json()['snapshot_id']
    c = citations(client, sid)[0]
    result = client.post(f'/api/v1/repos/{sid}/defense', headers=headers(), json={'phase': 'reflect', 'topic': 'flow', 'citations': [c]}).json()
    assert c['path'] in result['prompt'] and c['chunk_hash'] in result['prompt']
    assert 'changed requirement' in result['prompt'].lower()
    assert 'new' in result['prompt'].lower() and 'alternative' in result['prompt'].lower()


class FakeResponse:
    def __init__(self, status=200, chunks=(b'zip',), headers=None, delay=0):
        self.status_code = status
        self.chunks = chunks
        self.headers = headers or {}
        self.delay = delay
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def aiter_raw(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk
    aiter_bytes = aiter_raw


def mock_client(monkeypatch, response):
    requested = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kwargs):
            requested.append(url)
            return response
    monkeypatch.setattr(routes.httpx, 'AsyncClient', Client)
    return requested


def test_download_total_timeout_stops_trickle_without_live_network(monkeypatch):
    monkeypatch.setattr(routes, 'ARCHIVE_TOTAL_TIMEOUT', 0.01, raising=False)
    mock_client(monkeypatch, FakeResponse(chunks=(b'1', b'2'), delay=0.05))
    with pytest.raises(ingest.ImportFailure, match='timeout'):
        asyncio.run(routes.fetch_public_archive('https://github.com/a/b'))


def test_private_redirect_never_followed_and_download_size_encoding_bounded(monkeypatch):
    requested = mock_client(monkeypatch, FakeResponse(status=302, headers={'location': 'https://127.0.0.1/private'}))
    with pytest.raises(ingest.ImportFailure):
        asyncio.run(routes.fetch_public_archive('https://github.com/a/b'))
    assert requested == ['https://codeload.github.com/a/b/zip/HEAD']
    monkeypatch.setattr(ingest, 'MAX_COMPRESSED', 4)
    for response in (FakeResponse(chunks=(b'123', b'45')), FakeResponse(headers={'content-length': '5'}), FakeResponse(headers={'content-encoding': 'gzip'})):
        mock_client(monkeypatch, response)
        with pytest.raises(ingest.ImportFailure):
            asyncio.run(routes.fetch_public_archive('https://github.com/a/b'))


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.2', '169.254.169.254', '::1', 'fc00::1', '::ffff:127.0.0.1', '2001:db8::1', '224.0.0.1'])
def test_dns_private_special_addresses_rejected_before_socket_connect(monkeypatch, address):
    from backend.app.repo_learning.network import PublicArchiveBackend
    connections = []
    async def resolve(host, port):
        return [address]
    class Backend:
        async def connect_tcp(self, *args, **kwargs):
            connections.append((args, kwargs))
    backend = PublicArchiveBackend(resolver=resolve, backend=Backend())
    with pytest.raises(ingest.ImportFailure):
        asyncio.run(backend.connect_tcp('codeload.github.com', 443))
    assert not connections


def test_dns_resolution_deadline_and_forbidden_socket_targets():
    from backend.app.repo_learning.network import PublicArchiveBackend
    async def delayed(host, port):
        await asyncio.sleep(0.05)
        return ['93.184.216.34']
    backend = PublicArchiveBackend(resolver=delayed)
    with pytest.raises(ingest.ImportFailure, match='timeout'):
        asyncio.run(backend.connect_tcp('gitlab.com', 443, timeout=0.001))
    for host, port in [('evil.example', 443), ('gitlab.com', 80)]:
        with pytest.raises(ingest.ImportFailure):
            asyncio.run(backend.connect_tcp(host, port))
    with pytest.raises(ingest.ImportFailure):
        asyncio.run(backend.connect_unix_socket('/synthetic/socket'))


def test_real_http_adapter_pins_numeric_ip_and_preserves_tls_and_host(monkeypatch):
    import httpcore
    from backend.app.repo_learning import network
    connected, tls_names, writes = [], [], []
    class Stream(httpcore.AsyncNetworkStream):
        async def read(self, max_bytes, timeout=None):
            return b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nzip'
        async def write(self, buffer, timeout=None):
            writes.append(buffer)
        async def aclose(self):
            pass
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_names.append(server_hostname)
            return self
        def get_extra_info(self, info):
            return None
    class Backend:
        async def connect_tcp(self, host, port, **kwargs):
            connected.append((host, port))
            return Stream()
    async def resolver(host, port):
        return ['93.184.216.34']
    monkeypatch.setattr(network, 'resolve_addresses', resolver)
    monkeypatch.setattr(network, 'AnyIOBackend', Backend)
    result = asyncio.run(routes.fetch_public_archive('https://github.com/owner/repo'))
    assert result == b'zip'
    assert connected == [('93.184.216.34', 443)]
    assert tls_names == ['codeload.github.com']
    assert b'host: codeload.github.com\r\n' in b''.join(writes).lower()


def test_public_dns_is_pinned_and_mixed_resolution_fails_closed():
    from backend.app.repo_learning.network import PublicArchiveBackend
    connected = []
    async def resolve(host, port):
        return ['93.184.216.34']
    class Backend:
        async def connect_tcp(self, host, port, **kwargs):
            connected.append((host, port))
            return 'fake-stream'
    assert asyncio.run(PublicArchiveBackend(resolver=resolve, backend=Backend()).connect_tcp('gitlab.com', 443)) == 'fake-stream'
    assert connected == [('93.184.216.34', 443)]
    async def mixed(host, port):
        return ['93.184.216.34', '10.0.0.1']
    with pytest.raises(ingest.ImportFailure):
        asyncio.run(PublicArchiveBackend(resolver=mixed, backend=Backend()).connect_tcp('gitlab.com', 443))
    assert len(connected) == 1
