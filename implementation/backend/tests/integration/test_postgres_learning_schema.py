"""Opt-in schema-only tests; uses an isolated schema in a dedicated database."""
import os
import uuid

import pytest

from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.learning_schema import LEARNING_MIGRATION

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')


def test_learning_owned_evidence_and_privacy():
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_learning_test_' + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.execute('CREATE TABLE studio_workspaces (id text primary key, deleted_at text)')
                c.commit()
                assert apply_migrations(c, [LEARNING_MIGRATION]) == [5]
                assert apply_migrations(c, [LEARNING_MIGRATION]) == []
                c.execute("INSERT INTO studio_workspaces VALUES ('a',NULL),('b',NULL)")
                c.execute("""INSERT INTO learning_sessions
                 (id,workspace_id,lesson_id,catalog_version,content_hash,lesson_json,language_mode,coach_messages_json,created_at,updated_at)
                 VALUES ('s','a','l','v','h','{}','en','[]','t','t')""")
                c.execute("INSERT INTO learning_answers VALUES ('ans','s','a',1,1,'q','yes',1,'{}','t')")
                c.commit()
                with pytest.raises(psycopg.Error):
                    c.execute("INSERT INTO learning_events VALUES ('bad','b','s',1,'lesson.completed','learning_engine','ans',0,'t')")
                c.rollback()
                with pytest.raises(psycopg.Error):
                    c.execute("INSERT INTO learning_events VALUES ('bad','a','s',1,'lesson.completed','learning_engine',NULL,0,'t')")
                c.rollback()
                c.execute("INSERT INTO learning_events VALUES ('e','a','s',1,'lesson.completed','learning_engine','ans',0,'t')")
                c.execute("INSERT INTO learning_achievements VALUES ('a','badge','Badge','t','e')")
                c.commit()
                with pytest.raises(psycopg.Error):
                    c.execute("UPDATE learning_answers SET answer='altered' WHERE id='ans'")
                c.rollback()
                c.execute("""INSERT INTO interview_sessions VALUES
                 ('i','a','cs','beginner','[]',10,'en',1,'completed','t','t','t','finished','{}')""")
                c.execute("INSERT INTO interview_questions VALUES ('q','i',1,1,'{}','t')")
                c.execute("INSERT INTO interview_answers VALUES ('ia','i','q',1,'answer',NULL,'t')")
                c.execute("INSERT INTO interview_reports VALUES ('i','{}','t')")
                c.execute("INSERT INTO interview_events VALUES ('i',1,'interview.completed','{}','t')")
                c.execute("INSERT INTO learning_external_events VALUES ('ext','a','interview','i','interview.completed','t')")
                c.execute("INSERT INTO learning_evidence_achievements VALUES ('a','first_interview','Interview','t','ext','interview')")
                c.execute("UPDATE studio_workspaces SET deleted_at='now' WHERE id='a'")
                assert c.execute('SELECT count(*) FROM learning_sessions').fetchone()[0] == 0
                assert c.execute('SELECT count(*) FROM learning_achievements').fetchone()[0] == 0
                for table in ('interview_sessions', 'interview_questions', 'interview_answers',
                              'interview_reports', 'interview_events', 'learning_external_events',
                              'learning_evidence_achievements'):
                    assert c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] == 0
                c.commit()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_learning_dates_are_safe_and_timezone_independent():
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_learning_dates_' + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.execute('CREATE TABLE studio_workspaces (id text primary key, deleted_at text)')
                c.commit()
                apply_migrations(c, [LEARNING_MIGRATION])
                c.execute("SET TIME ZONE 'Pacific/Honolulu'")
                c.execute("INSERT INTO studio_workspaces VALUES ('a',NULL)")
                c.execute("""INSERT INTO learning_sessions
                 (id,workspace_id,lesson_id,catalog_version,content_hash,lesson_json,language_mode,coach_messages_json,created_at,updated_at)
                 VALUES ('s','a','l','v','h','{}','en','[]','t','t')""")
                for number, timestamp in enumerate(('bad', '2026-01-01T23:00:00',
                     '2026-01-03T01:00:00+02:00', '2026-01-03T00:00:00')):
                    c.execute("INSERT INTO learning_events VALUES (%s,'a','s',1,'hint.requested','learning_engine',NULL,0,%s)",
                              (str(number), timestamp))
                c.execute("INSERT INTO learning_evidence_achievements VALUES ('a','three_study_days','Days','2026-01-03T00:00:00','3','learning_engine')")
                assert c.execute("SELECT learning_evidence_date('nonsense'), learning_evidence_date('2026-02-30'), learning_evidence_date('2026-01-01T00:00:00+99:99')").fetchone() == (None, None, None)
                c.commit()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_backfill_purges_preexisting_tombstoned_workspace_data():
    """Exercise backfill with populated tables before its statements run."""
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_learning_backfill_' + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                c.execute("CREATE TABLE studio_workspaces (id text primary key, deleted_at text)")
                c.execute("INSERT INTO studio_workspaces VALUES ('deleted','t'),('active',NULL)")
                prefix, suffix = LEARNING_MIGRATION.sql.rsplit(
                    'DELETE FROM interview_sessions WHERE workspace_id IN', 1)
                c.execute(prefix)
                for wid in ('deleted', 'active'):
                    c.execute("""INSERT INTO interview_sessions VALUES
                      (%s,%s,'cs','beginner','[]',10,'en',1,'active','t','t',NULL,NULL,'{}')""",
                              ('interview-' + wid, wid))
                    c.execute("""INSERT INTO learning_sessions
                      (id,workspace_id,lesson_id,catalog_version,content_hash,lesson_json,language_mode,coach_messages_json,created_at,updated_at)
                      VALUES (%s,%s,'l','v','h','{}','en','[]','t','t')""", ('learning-' + wid, wid))
                c.execute('DELETE FROM interview_sessions WHERE workspace_id IN' + suffix)
                assert c.execute('SELECT id FROM interview_sessions').fetchall() == [('interview-active',)]
                assert c.execute('SELECT id FROM learning_sessions').fetchall() == [('learning-active',)]
                c.commit()
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
