"""Atomic repository publication on SQLite and disposable PostgreSQL."""
from contextlib import closing
import os
import sqlite3
from uuid import uuid4

import pytest
from psycopg import sql

from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.db.postgres.runtime import PostgresTarget, initialize
from backend.app.repo_learning import service


@pytest.fixture(params=['sqlite', 'postgres'])
def publication_db(request, tmp_path):
    if request.param == 'sqlite':
        target = str(tmp_path / 'publication.sqlite3')
        apply_migrations(target)
    else:
        dsn = os.environ.get('VIVA_POSTGRES_TEST_DSN')
        if not dsn:
            pytest.skip('Dedicated disposable PostgreSQL required')
        target = PostgresTarget(dsn, 'batch_publish_' + uuid4().hex)
        initialize(target)
    with closing(open_connection(target)) as db:
        db.execute("INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES ('owner','synthetic-hash','2026-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00')")
        db.commit()
    try:
        yield target
    finally:
        if isinstance(target, PostgresTarget):
            with target.connect() as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(target.schema)))


FILES = {'z.py': 'def later():\n    return 2\n', 'a.py': 'def first():\n    return 1\n'}
COVERAGE = {'total': 2, 'skipped': 0}


def traced_connections(monkeypatch, *, fail_fts=False, cancel_before_ready=False):
    batches = []
    phase = {'locked': False}
    original_open = service.open_connection

    class Traced:
        def __init__(self, target):
            self.db = original_open(target)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, query, params=()):
            if query == 'BEGIN IMMEDIATE':
                phase['locked'] = True
            if query.startswith(('INSERT INTO repo_files ', 'INSERT INTO repo_chunks ', 'INSERT INTO repo_chunks_fts')):
                pytest.fail('Repository rows must use batched publication')
            if cancel_before_ready and query.startswith("UPDATE repo_snapshots SET status='READY'"):
                self.db.execute("UPDATE repo_snapshots SET status='FAILED' WHERE id=?", (params[4],))
            return self.db.execute(query, params)

        def executemany(self, query, rows):
            assert phase['locked']
            rows = list(rows)
            batches.append((query.split()[2], len(rows)))
            result = self.db.executemany(query, rows)
            if fail_fts and query.startswith('INSERT INTO repo_chunks_fts'):
                raise sqlite3.OperationalError('synthetic publication failure after FTS insertion')
            return result

        def commit(self):
            self.db.commit()
            phase['locked'] = False

        def close(self):
            self.db.close()
            phase['locked'] = False

    monkeypatch.setattr(service, 'open_connection', Traced)
    return batches, phase


def test_rows_are_staged_before_lock_and_published_in_three_batches(publication_db, monkeypatch):
    sid = service.queue(publication_db, 'owner', 'zip_upload')
    batches, phase = traced_connections(monkeypatch)
    original_spans = service.chunk_spans
    calls = []

    def staged_spans(*args):
        assert not phase['locked']
        calls.append(True)
        return original_spans(*args)

    monkeypatch.setattr(service, 'chunk_spans', staged_spans)
    result = service.create(publication_db, 'owner', 'zip_upload', FILES, COVERAGE, sid)
    assert result['status'] == 'READY'
    assert calls and [table for table, _ in batches] == ['repo_files', 'repo_chunks', 'repo_chunks_fts(chunk_id,snapshot_id,text)']
    assert batches[0][1] == len(FILES) and batches[1][1] == batches[2][1] > 0
    with closing(open_connection(publication_db)) as db:
        assert [row[0] for row in db.execute('SELECT path FROM repo_files WHERE snapshot_id=? ORDER BY rowid', (sid,))] == sorted(FILES)
        assert db.execute('SELECT count(*) FROM repo_chunks WHERE snapshot_id=?', (sid,)).fetchone()[0] == batches[1][1]
        assert db.execute('SELECT count(*) FROM repo_chunks_fts WHERE snapshot_id=?', (sid,)).fetchone()[0] == batches[2][1]
    assert service.search(publication_db, 'owner', sid, 'first')['results']


@pytest.mark.parametrize('failure', ['fts', 'final_cas'])
def test_failed_batch_or_publication_cas_rolls_back_every_row(publication_db, monkeypatch, failure):
    sid = service.queue(publication_db, 'owner', 'zip_upload')
    batches, _ = traced_connections(monkeypatch, fail_fts=failure == 'fts', cancel_before_ready=failure == 'final_cas')
    with pytest.raises((sqlite3.OperationalError, ValueError)):
        service.create(publication_db, 'owner', 'zip_upload', FILES, COVERAGE, sid)
    assert len(batches) == 3
    with closing(open_connection(publication_db)) as db:
        assert db.execute('SELECT status FROM repo_snapshots WHERE id=?', (sid,)).fetchone()[0] == 'FAILED'
        for table in ('repo_files', 'repo_chunks', 'repo_chunks_fts', 'repo_evidence_cards'):
            assert db.execute('SELECT count(*) FROM ' + table + ' WHERE snapshot_id=?', (sid,)).fetchone()[0] == 0


def test_individually_oversized_snapshot_is_rejected_before_batch_allocation(publication_db, monkeypatch):
    sid = service.queue(publication_db, 'owner', 'zip_upload')
    batches, _ = traced_connections(monkeypatch)
    monkeypatch.setattr(service, 'WORKSPACE_BYTE_LIMIT', 1)
    monkeypatch.setattr(service, 'make_id', lambda: pytest.fail('Oversized input must not allocate batch row identities'))
    with pytest.raises(service.QuotaExceeded):
        service.create(publication_db, 'owner', 'zip_upload', FILES, COVERAGE, sid)
    assert not batches
    assert service.get(publication_db, 'owner', sid)['failure_code'] == 'QUOTA_EXCEEDED'


def test_curated_cards_use_staged_chunks_and_one_additional_batch(publication_db, monkeypatch):
    from backend.app.repo_learning.ingest import golden
    files, coverage = golden('REPO-EXP-01')
    sid = service.queue(publication_db, 'owner', 'golden_curated', 'REPO-EXP-01')
    batches, _ = traced_connections(monkeypatch)
    result = service.create(publication_db, 'owner', 'golden_curated', files, coverage, sid)
    assert result['status'] == 'READY'
    assert len(batches) == 4 and batches[-1] == ('repo_evidence_cards', 8)
    with closing(open_connection(publication_db)) as db:
        import json
        rows = db.execute('SELECT evidence_json FROM repo_evidence_cards WHERE snapshot_id=?', (sid,)).fetchall()
    assert len(rows) == 8
    for row in rows:
        card = json.loads(row[0])
        assert card['author_intent_verifiable'] is False
        assert service.validate_citation(publication_db, 'owner', sid, card['observed_code'][0])


def test_workspace_deleted_during_staging_cannot_publish_or_leave_orphans(publication_db, monkeypatch):
    sid = service.queue(publication_db, 'owner', 'zip_upload')
    original_spans = service.chunk_spans
    deleted = False

    def delete_during_staging(*args):
        nonlocal deleted
        if not deleted:
            with closing(open_connection(publication_db)) as db:
                db.execute("UPDATE studio_workspaces SET deleted_at='2026-01-01T00:00:00+00:00' WHERE id='owner'")
                db.commit()
            deleted = True
        return original_spans(*args)

    monkeypatch.setattr(service, 'chunk_spans', delete_during_staging)
    with pytest.raises((sqlite3.IntegrityError, ValueError)):
        service.create(publication_db, 'owner', 'zip_upload', FILES, COVERAGE, sid)
    assert deleted
    with closing(open_connection(publication_db)) as db:
        assert db.execute('SELECT status FROM repo_snapshots WHERE id=?', (sid,)).fetchone()[0] == 'FAILED'
        assert db.execute("SELECT deleted_at FROM studio_workspaces WHERE id='owner'").fetchone()[0] is not None
        for table in ('repo_files', 'repo_chunks', 'repo_chunks_fts', 'repo_evidence_cards'):
            assert db.execute('SELECT count(*) FROM ' + table + ' WHERE snapshot_id=?', (sid,)).fetchone()[0] == 0
