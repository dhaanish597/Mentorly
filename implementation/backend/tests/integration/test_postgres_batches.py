"""Transactional INSERT batches against an owned disposable PostgreSQL schema."""
import os
import sqlite3
from contextlib import closing
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from backend.app.db.migrations import open_connection
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.db.postgres.maintenance import DDL, Fence, maintenance_fence

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='Dedicated disposable PostgreSQL required')


@pytest.fixture
def target():
    target = PostgresTarget(DSN, 'batch_' + uuid4().hex)
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(target.schema)))
    try:
        with target.connect() as db:
            db.execute('CREATE TABLE parents(id TEXT PRIMARY KEY,label TEXT,_vcc_order BIGINT GENERATED ALWAYS AS IDENTITY)')
            db.execute('CREATE TABLE children(id TEXT PRIMARY KEY,parent_id TEXT REFERENCES parents(id),note TEXT,_vcc_order BIGINT GENERATED ALWAYS AS IDENTITY)')
            db.execute(DDL)
        yield target
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(target.schema)))


def test_batches_preserve_order_foreign_keys_and_percent_literals(target):
    with closing(open_connection(target)) as db:
        assert db._conn.prepare_threshold is None
        db.execute('BEGIN IMMEDIATE')
        assert db.executemany("INSERT INTO parents(id,label) VALUES (?,'100% ready')", [('a',), ('b',)]).rowcount == 2
        rows = [('one', 'a', "it's 20% done"), ('two', 'b', 'literal ? and %s data')]
        assert db.executemany('INSERT INTO children(id,parent_id,note) VALUES (?,?,?)', rows).rowcount == 2
        db.commit()
        assert [tuple(r) for r in db.execute('SELECT id,parent_id,note FROM children ORDER BY rowid')] == rows
        assert db.execute('SELECT label FROM parents WHERE id=?', ('a',)).fetchone()[0] == '100% ready'
        assert db.execute('SELECT count(*) FROM pg_prepared_statements').fetchone()[0] == 0


def test_failed_pipeline_rolls_back_all_rows_with_caller_transaction(target):
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.IntegrityError, match='23505'):
            db.executemany('INSERT INTO parents(id,label) VALUES (?,?)', [('duplicate', 'first'), ('duplicate', 'second')])
        db.rollback()
        assert db.execute('SELECT count(*) FROM parents').fetchone()[0] == 0
        db.execute('BEGIN IMMEDIATE')
        db.executemany('INSERT INTO parents(id,label) VALUES (?,?)', [('fresh', 'valid')])
        db.commit()
        assert db.execute('SELECT count(*) FROM parents').fetchone()[0] == 1


def test_batches_cannot_implicitly_commit_or_execute_other_statements(target):
    with closing(open_connection(target)) as db:
        with pytest.raises(sqlite3.ProgrammingError, match='explicit transaction'):
            db.executemany('INSERT INTO parents(id) VALUES (?)', [('a',)])
        db.execute('BEGIN IMMEDIATE')
        for statement in ('DELETE FROM parents WHERE id=?', 'INSERT INTO parents(id) VALUES (?) RETURNING id', 'INSERT INTO parents(id) VALUES (?); DELETE FROM parents'):
            with pytest.raises(sqlite3.ProgrammingError, match='one INSERT'):
                db.executemany(statement, [('a',)])
        assert db.executemany('INSERT INTO parents(id) VALUES (?)', []).rowcount == 0
        db.rollback()
        assert db.execute('SELECT count(*) FROM parents').fetchone()[0] == 0


@pytest.mark.parametrize('owner,generation,expired', [('new', 1, False), ('owner', 2, False), ('owner', 1, True)])
def test_stale_maintenance_fence_rejects_batch_and_rolls_back(target, owner, generation, expired):
    with target.connect() as raw:
        raw.execute("INSERT INTO runtime_maintenance_owner VALUES('retention','owner',1,clock_timestamp()+interval '1 hour')")
        if expired:
            raw.execute("UPDATE runtime_maintenance_owner SET expires_at=clock_timestamp()-interval '1 second'")
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT INTO parents(id) VALUES ('pending')")
        token = maintenance_fence.set(Fence(str(target), owner, generation))
        try:
            with pytest.raises(sqlite3.OperationalError, match='superseded or expired'):
                db.executemany('INSERT INTO parents(id) VALUES (?)', [('blocked',)])
        finally:
            maintenance_fence.reset(token)
        assert not db.in_transaction
        assert db.execute('SELECT count(*) FROM parents').fetchone()[0] == 0


def test_current_maintenance_fence_allows_batch(target):
    with target.connect() as raw:
        raw.execute("INSERT INTO runtime_maintenance_owner VALUES('retention','owner',1,clock_timestamp()+interval '1 hour')")
    with closing(open_connection(target)) as db:
        token = maintenance_fence.set(Fence(str(target), 'owner', 1))
        try:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT INTO parents(id) VALUES (?)', [('allowed',)])
            db.commit()
        finally:
            maintenance_fence.reset(token)
        assert db.execute('SELECT count(*) FROM parents').fetchone()[0] == 1
