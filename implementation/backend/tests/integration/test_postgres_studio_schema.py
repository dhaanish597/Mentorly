"""Opt-in PostgreSQL Studio schema/privacy integration."""
import os
import uuid
import pytest
from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.studio_schema import STUDIO_MIGRATION
from backend.app.db.postgres.learning_schema import LEARNING_MIGRATION

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')


def test_studio_ownership_tombstone_and_retained_accounting():
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_studio_test_' + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.commit()
                assert apply_migrations(c, [STUDIO_MIGRATION, LEARNING_MIGRATION]) == [4, 5]
                assert apply_migrations(c, [STUDIO_MIGRATION, LEARNING_MIGRATION]) == []
                c.execute("INSERT INTO studio_workspaces VALUES ('a','hash','t','t',NULL),('b','hash','t','t',NULL)")
                c.execute("""INSERT INTO studio_sessions
                  (id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at)
                  VALUES ('s','a','hash','mode','teaching','scenario','v','t','t')""")
                c.commit()
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    c.execute("INSERT INTO studio_review_cards VALUES ('bad','b','s','prompt','[]','{}','t')")
                c.rollback()
                c.execute("""INSERT INTO studio_sessions
                  (id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at)
                  VALUES ('s2','b','hash','mode','teaching','scenario','v','t','t')""")
                c.execute("INSERT INTO studio_turns (id,session_id,epoch,diagram_revision,kind,content,created_at) VALUES ('t1','s',1,1,'answer','a','t'),('t2','s2',1,1,'answer','b','t'),('t3','s',1,1,'answer','c','t')")
                c.commit()
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    c.execute("UPDATE studio_turns SET superseded_by='t2' WHERE id='t1'")
                c.rollback()
                c.execute("UPDATE studio_turns SET superseded_by='t3' WHERE id='t1'")
                c.execute("DELETE FROM studio_turns WHERE id='t3'")
                assert c.execute("SELECT session_id,superseded_by FROM studio_turns WHERE id='t1'").fetchone() == ('s', None)
                c.commit()
                for seconds, chars, count in ((-1, 0, 1), (0, -1, 1), (0, 0, -1)):
                    with pytest.raises(psycopg.errors.CheckViolation):
                        c.execute("INSERT INTO studio_speech_usage VALUES ('invalid','s',1,'STT','invalid','digest',%s,%s,%s,'RESERVED','2026-01-01','t','UNDISPATCHED')", (seconds, chars, count))
                    c.rollback()
                c.execute("INSERT INTO studio_speech_usage VALUES ('release','s',1,'STT','release','digest',2,0,1,'RESERVED','2026-01-01T00:00:00Z','t','UNDISPATCHED')")
                assert c.execute("SELECT studio_release_undispatched_speech('release')").fetchone() == (True,)
                assert c.execute("SELECT count(*) FROM studio_speech_deleted_daily").fetchone() == (0,)
                c.execute("INSERT INTO studio_speech_usage VALUES ('dispatched','s',1,'STT','dispatched','digest',1,0,1,'RESERVED','2026-01-01T00:00:00Z','t','UNDISPATCHED')")
                assert c.execute("SELECT studio_mark_speech_dispatched('dispatched')").fetchone() == (True,)
                assert c.execute("SELECT studio_release_undispatched_speech('dispatched')").fetchone() == (False,)
                c.commit()
                for statement in ("UPDATE studio_speech_usage SET dispatch_state='RELEASED' WHERE id='dispatched'",
                                  "UPDATE studio_speech_usage SET dispatch_state='UNDISPATCHED' WHERE id='dispatched'",
                                  "UPDATE studio_speech_usage SET request_count=0 WHERE id='dispatched'"):
                    with pytest.raises(psycopg.errors.RaiseException):
                        c.execute(statement)
                    c.rollback()
                c.execute("UPDATE studio_speech_usage SET status='COMMITTED' WHERE id='dispatched'")
                c.commit()
                with pytest.raises(psycopg.errors.RaiseException):
                    c.execute("UPDATE studio_speech_usage SET dispatch_state='RELEASED',status='RESERVED' WHERE id='dispatched'")
                c.rollback()
                c.execute("INSERT INTO studio_diagrams VALUES ('s',1,NULL,'{}','t')")
                c.execute("INSERT INTO studio_review_cards VALUES ('r','a','s','prompt','[]','{}','t')")
                c.execute("INSERT INTO studio_idempotency VALUES ('s','POST','/','key','d',200,'{}','t')")
                c.execute("INSERT INTO studio_speech_usage VALUES ('v','s',1,'STT','key','digest',2,0,1,'RESERVED','2026-01-01T00:00:00Z','t','UNDISPATCHED')")
                c.execute("SELECT studio_mark_speech_dispatched('v')")
                c.execute("UPDATE studio_speech_usage SET status='COMMITTED' WHERE id='v'")
                c.execute("INSERT INTO studio_model_usage VALUES ('m','s',1,'key','UNCERTAIN','2026-01-01T00:00:00Z')")
                c.execute("UPDATE studio_workspaces SET deleted_at='2026-01-02' WHERE id='a'")
                assert c.execute("SELECT deleted_at,epoch FROM studio_sessions WHERE id='s'").fetchone() == ('2026-01-02', 2)
                for name in ('studio_diagrams','studio_review_cards','studio_idempotency','studio_speech_usage','studio_model_usage'):
                    assert c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(name))).fetchone() == (0,)
                assert c.execute("SELECT request_count FROM studio_speech_deleted_daily WHERE day='2026-01-01'").fetchone() == (2,)
                assert c.execute("SELECT stt_seconds FROM studio_speech_deleted_audio WHERE day='2026-01-01'").fetchone() == (3.0,)
                assert c.execute("SELECT request_count FROM studio_model_deleted_daily WHERE day='2026-01-01'").fetchone() == (1,)
                c.commit()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
