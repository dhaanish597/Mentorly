"""Opt-in integration of experimental slices in one schema.

The operator must supply an isolated, dedicated test database in
VIVA_POSTGRES_TEST_DSN. This test does not verify the target database; its UUID
schema protects existing objects but the migration advisory lock is database-wide.
Never point it at a production or shared database.
"""
import os
import uuid
import pytest
from backend.app.db.postgres import Migration, apply_migrations
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.speech_coordination import SPEECH_MIGRATION
from backend.app.db.postgres.jobs import JOBS_MIGRATION
from backend.app.db.postgres.studio_schema import STUDIO_MIGRATION
from backend.app.db.postgres.learning_schema import LEARNING_MIGRATION
from backend.app.db.postgres.repository_schema import REPOSITORY_MIGRATION
from backend.app.db.postgres.repository_search import REPOSITORY_SEARCH_MIGRATION
from backend.app.db.postgres.session_lifecycle import SESSION_LIFECYCLE_MIGRATION

DSN=os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')
MANIFEST=[CORE_MIGRATION,SPEECH_MIGRATION,JOBS_MIGRATION,STUDIO_MIGRATION,LEARNING_MIGRATION,
          REPOSITORY_MIGRATION,REPOSITORY_SEARCH_MIGRATION,SESSION_LIFECYCLE_MIGRATION]


def test_complete_manifest_atomicity_ownership_and_privacy():
    psycopg=pytest.importorskip('psycopg')
    from psycopg import sql
    schema='viva_full_'+uuid.uuid4().hex
    with psycopg.connect(DSN,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema))); c.commit()
                with pytest.raises(psycopg.Error):
                    apply_migrations(c,MANIFEST+[Migration(9,'failure','SELECT * FROM no_such_table')])
                assert c.execute("SELECT to_regclass('sessions'),to_regclass('studio_workspaces'),to_regclass('viva_schema_migrations')").fetchone()==(None,None,None)
                c.rollback()
                assert apply_migrations(c,MANIFEST)==list(range(1,9))
                assert apply_migrations(c,MANIFEST)==[]
                c.execute("INSERT INTO studio_workspaces VALUES ('a','hash','t','t',NULL),('b','hash','t','t',NULL)")
                c.execute("INSERT INTO repo_snapshots (id,workspace_id,source_kind,status,created_at) VALUES ('snap','a','upload','READY','t')")
                c.execute("INSERT INTO studio_sessions (id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,repo_snapshot_id,created_at,expires_at) VALUES ('s','a','h','m','p','scenario','v','snap','t','t')")
                c.execute("INSERT INTO repo_files VALUES ('file','snap','x','text','h','py','ok','[]','[]','[]',0)")
                c.execute("INSERT INTO repo_chunks (id,snapshot_id,file_id,path,symbol,start_line,end_line,chunk_hash,text) VALUES ('chunk','snap','file','x','f',1,2,'h','searchable text')")
                c.execute("INSERT INTO learning_sessions (id,workspace_id,lesson_id,catalog_version,content_hash,lesson_json,language_mode,coach_messages_json,created_at,updated_at) VALUES ('lesson','a','l','v','h','{}','en','[]','t','t')")
                c.execute("INSERT INTO interview_sessions VALUES ('interview','a','cs','beginner','[]',10,'en',1,'active','t','t',NULL,NULL,'{}')")
                c.execute("INSERT INTO module_speech_usage VALUES ('voice','a','lesson','lesson',1,'STT',2,0,1,'COMMITTED','2026-01-01T00:00:00Z','t')")
                c.commit()
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    c.execute("INSERT INTO repo_evidence_cards VALUES ('bad','snap','b','topic','[]','t','authored')")
                c.rollback()
                assert c.execute("SELECT count(*) FROM repo_chunks WHERE search_vector @@ plainto_tsquery('simple','searchable')").fetchone()==(1,)
                c.execute("UPDATE studio_workspaces SET deleted_at='t' WHERE id='a'")
                for table in ('repo_snapshots','repo_chunks','learning_sessions','interview_sessions','module_speech_usage'):
                    assert c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()==(0,)
                assert c.execute("SELECT request_count FROM studio_speech_deleted_daily WHERE day='2026-01-01'").fetchone()==(1,)
                c.commit()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
