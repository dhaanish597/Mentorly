"""Opt-in PostgreSQL repository search authorization and indexing checks."""
import hashlib
import os
import threading
import time
import uuid
import pytest
from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.studio_schema import STUDIO_MIGRATION
from backend.app.db.postgres.learning_schema import LEARNING_MIGRATION
from backend.app.db.postgres.repository_schema import REPOSITORY_MIGRATION
from backend.app.db.postgres.repository_search import REPOSITORY_SEARCH_MIGRATION, search_repository, SearchAuthorizationError

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')


def test_search_scope_auth_escaping_and_index_updates():
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_search_test_' + uuid.uuid4().hex
    digest = hashlib.sha256(b'token').hexdigest()
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.commit()
                assert apply_migrations(c, [STUDIO_MIGRATION, LEARNING_MIGRATION, REPOSITORY_MIGRATION, REPOSITORY_SEARCH_MIGRATION]) == [4,5,6,7]
                for workspace in ('a','b'):
                    c.execute("INSERT INTO studio_workspaces VALUES (%s,%s,'t','2099-01-01T00:00:00+00:00',NULL)",(workspace,digest))
                    c.execute("INSERT INTO repo_snapshots (id,workspace_id,source_kind,status,created_at) VALUES (%s,%s,'upload','READY','t')",(workspace,workspace))
                    c.execute("INSERT INTO repo_files VALUES (%s,%s,'x','text','h','py','ok','[]','[]','[]',0)",(workspace,workspace))
                    c.execute("INSERT INTO repo_chunks (id,snapshot_id,file_id,path,symbol,start_line,end_line,chunk_hash,text) VALUES (%s,%s,%s,'x','f',1,2,'h',%s)",(workspace,workspace,workspace,'apple grape' if workspace=='a' else 'apple secret'))
                c.commit()
                def search(wid='a', token=digest, snap='a', query='apple', limit=20):
                    return search_repository(c, workspace_id=wid, token_hash=token, snapshot_id=snap, query=query, limit=limit)
                assert [x['text'] for x in search()] == ['apple grape']
                assert len(search(query='"apple" | !grape & (oops)')) == 1
                assert len(search(query='nothing grape')) == 1
                assert search(query='%%%') == []
                with pytest.raises(SearchAuthorizationError): search(snap='b')
                with pytest.raises(SearchAuthorizationError): search(token='0'*64)
                with pytest.raises(ValueError): search(limit=21)
                with pytest.raises(ValueError): search(query='x'*201)
                assert search(query='x'*200) == []
                c.execute("UPDATE repo_chunks SET text='pear' WHERE id='a'")
                c.commit()
                assert search() == []
                assert len(search(query='pear')) == 1
                # Hold the same row lock while search starts, then tombstone before
                # releasing it; the search must see deletion after the lock wait.
                c.execute("SELECT id FROM studio_workspaces WHERE id='a' FOR UPDATE")
                started = threading.Event()
                outcome = []
                search_pid = []
                def concurrent_search():
                    with psycopg.connect(DSN) as other:
                        other.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                        other.commit()
                        search_pid.append(other.info.backend_pid)
                        started.set()
                        try:
                            search_repository(other, workspace_id='a', token_hash=digest, snapshot_id='a', query='pear')
                            outcome.append('allowed')
                        except SearchAuthorizationError:
                            outcome.append('denied')
                thread = threading.Thread(target=concurrent_search)
                thread.start()
                assert started.wait(5)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    blockers = c.execute('SELECT pg_blocking_pids(%s)', (search_pid[0],)).fetchone()[0]
                    if c.info.backend_pid in blockers:
                        break
                    time.sleep(0.01)
                else:
                    raise AssertionError('Search never blocked on the held workspace lock')
                c.execute("UPDATE studio_workspaces SET deleted_at='t' WHERE id='a'")
                c.commit()
                thread.join(timeout=5)
                assert not thread.is_alive() and outcome == ['denied']
                with pytest.raises(SearchAuthorizationError): search()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
