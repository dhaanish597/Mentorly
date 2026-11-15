"""Opt-in repository schema ownership and privacy checks."""
import os
import uuid
import pytest
from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.studio_schema import STUDIO_MIGRATION
from backend.app.db.postgres.learning_schema import LEARNING_MIGRATION
from backend.app.db.postgres.repository_schema import REPOSITORY_MIGRATION

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')


def test_repository_ownership_privacy_and_accounting():
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_repo_test_' + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.commit()
                assert apply_migrations(c, [STUDIO_MIGRATION, LEARNING_MIGRATION, REPOSITORY_MIGRATION]) == [4,5,6]
                c.execute("INSERT INTO studio_workspaces VALUES ('a','hash','t','t',NULL),('b','hash','t','t',NULL)")
                c.execute("""INSERT INTO studio_sessions
                 (id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at)
                 VALUES ('s','a','h','m','p','scenario','v','t','t'),('s2','a','h','m','p','scenario','v','t','t')""")
                c.execute("INSERT INTO repo_snapshots (id,workspace_id,source_kind,status,created_at) VALUES ('snap','a','upload','READY','t'),('snap2','a','upload','READY','t'),('other','b','upload','READY','t')")
                c.execute("UPDATE studio_sessions SET repo_snapshot_id='snap' WHERE id IN ('s','s2')")
                c.execute("INSERT INTO repo_defense_sessions VALUES ('def','s','snap','a','map','t')")
                c.execute("INSERT INTO repo_evidence_cards VALUES ('card','snap','a','topic','[]','t','authored')")
                c.execute("INSERT INTO repo_decisions VALUES ('decision','snap','a','topic','[]','reason',NULL,'t')")
                c.execute("INSERT INTO repo_files VALUES ('f','snap','a.py','text','h','python','ok','[]','[]','[]',0)")
                c.commit()
                for query in (
                    "INSERT INTO repo_defense_sessions VALUES ('bad','s2','snap2','a','map','t')",
                    "INSERT INTO repo_idempotency VALUES ('a','x','one','h','snap2','s',NULL,NULL,NULL,'{}','t')",
                    "INSERT INTO repo_idempotency VALUES ('a','x','two','h','snap2',NULL,'def',NULL,NULL,'{}','t')",
                    "INSERT INTO repo_idempotency VALUES ('a','x','three','h','snap2',NULL,NULL,'card',NULL,'{}','t')",
                    "INSERT INTO repo_idempotency VALUES ('a','x','four','h','snap2',NULL,NULL,NULL,'decision','{}','t')",
                    "INSERT INTO repo_chunks VALUES ('bad','other','f','a.py','f',1,2,'h','text')",
                    "INSERT INTO repo_evidence_cards VALUES ('bad','snap','b','t','[]','t','authored')",
                    "INSERT INTO repo_learning_plans (id,workspace_id,snapshot_id,snapshot_hash,steps_json,created_at,updated_at) VALUES ('bad','b','snap','h','[]','t','t')",
                ):
                    with pytest.raises(psycopg.errors.ForeignKeyViolation):
                        c.execute(query)
                    c.rollback()
                c.execute("INSERT INTO repo_chunks VALUES ('c','snap','f','a.py','f',1,2,'h','text')")
                c.execute("INSERT INTO studio_events VALUES ('s',1,'coach.action','{\"source\":\"authored_repo_defense\",\"snapshot_id\":\"snap\"}','t'),('s',2,'coach.action','invalid json','t')")
                c.execute("INSERT INTO module_speech_usage VALUES ('v','a','source','redrive',1,'STT',2,0,1,'COMMITTED','2026-01-01T00:00:00Z','t')")
                c.execute("DELETE FROM repo_snapshots WHERE id='snap'")
                assert c.execute("SELECT sequence FROM studio_events").fetchall() == [(2,)]
                assert c.execute("SELECT count(*) FROM repo_chunks").fetchone() == (0,)
                c.execute("UPDATE studio_workspaces SET deleted_at='t' WHERE id='a'")
                assert c.execute("SELECT count(*) FROM module_speech_usage").fetchone() == (0,)
                assert c.execute("SELECT request_count FROM studio_speech_deleted_daily WHERE day='2026-01-01'").fetchone() == (1,)
                assert c.execute("SELECT stt_seconds FROM module_speech_deleted_totals WHERE day='2026-01-01'").fetchone() == (2.0,)
                assert c.execute("SELECT count(*) FROM repo_snapshots WHERE id='other'").fetchone() == (1,)
                c.commit()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
