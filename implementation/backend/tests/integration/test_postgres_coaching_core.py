"""Opt-in partial coaching schema checks; requires a dedicated test DB."""
import os
import uuid

import pytest

from backend.app.db.postgres import Migration, apply_migrations
from backend.app.db.postgres.core import CORE_MIGRATION

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_TEST_DSN to a dedicated test database")


def test_core_schema_constraints_and_rollback():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    schema = "viva_core_test_" + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as conn:
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                conn.commit()
                with pytest.raises(psycopg.Error):
                    apply_migrations(conn, [CORE_MIGRATION, Migration(2, "failure", "SELECT * FROM no_such_table")])
                assert conn.execute("SELECT to_regclass('sessions'), to_regclass('viva_schema_migrations')").fetchone() == (None, None)
                conn.rollback()
                assert apply_migrations(conn, [CORE_MIGRATION]) == [1]
                assert apply_migrations(conn, [CORE_MIGRATION]) == []
                for sid in ("a", "b"):
                    conn.execute("INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES (%s,%s,'e','v','en','text','t','t','t')", (sid, sid))
                    conn.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES (%s,%s,1,'code','hash','t')", (sid, sid))
                conn.execute("INSERT INTO challenges (id,session_id,exercise_id,spec_version,code_version_id,code_hash,turn_generation,input_args_json,case_hash,purpose,created_at,expires_at) VALUES ('ca','a','e','v',1,'hash',1,'[]','case','DIAGNOSTIC','t','t')")
                conn.commit()
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    conn.execute("INSERT INTO turns (id,session_id,turn_generation,code_version_id,challenge_id,transport_mode,language_mode,state,created_at,updated_at) VALUES ('bad','b',1,1,'ca','text','en','CREATED','t','t')")
                conn.rollback()
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    conn.execute("INSERT INTO jobs (id,session_id,job_type,status,turn_generation,code_version_id,created_at,updated_at) VALUES ('bad','a','run','RUNNING',1,999,'t','t')")
                conn.rollback()
                with pytest.raises(psycopg.errors.UniqueViolation):
                    conn.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES ('duplicate','a',1,'x','x','t')")
                conn.rollback()
                conn.execute("INSERT INTO challenges (id,session_id,exercise_id,spec_version,code_version_id,code_hash,turn_generation,input_args_json,case_hash,purpose,created_at,expires_at) VALUES ('ca2','a','e','v',1,'hash',2,'[]','case2','DIAGNOSTIC','t','t')")
                conn.execute("INSERT INTO challenges (id,session_id,exercise_id,spec_version,code_version_id,code_hash,turn_generation,input_args_json,case_hash,purpose,created_at,expires_at) VALUES ('cb','b','e','v',1,'hash',1,'[]','case','DIAGNOSTIC','t','t')")
                conn.execute("INSERT INTO turns (id,session_id,turn_generation,code_version_id,challenge_id,transport_mode,language_mode,state,created_at,updated_at) VALUES ('ta','a',1,1,'ca','text','en','CREATED','t','t')")
                conn.execute("INSERT INTO traces (id,session_id,code_version_id,turn_generation,case_hash,status,total_observed,trace_truncated,termination_reason,runtime_version,steps_json,created_at,challenge_id) VALUES ('tr','a',1,1,'case','OK',0,0,'done','v','[]','t','ca')")
                conn.execute("INSERT INTO evidence_artifacts (id,session_id,challenge_id,code_version_id,turn_generation,case_hash,prediction_status,verification_status,minimization_status,trace_id,artifact_json,created_at) VALUES ('ea','a','ca',1,1,'case','P','V','M','tr','{}','t')")
                conn.execute("INSERT INTO jobs (id,session_id,job_type,status,turn_generation,code_version_id,created_at,updated_at,challenge_id) VALUES ('j','a','run','RUNNING',1,1,'t','t','ca'),('jn','a','run','RUNNING',1,1,'t','t',NULL)")
                conn.commit()
                for statement in (
                    "INSERT INTO jobs (id,session_id,job_type,status,turn_generation,code_version_id,created_at,updated_at,challenge_id) VALUES ('jb','b','run','RUNNING',1,1,'t','t','ca')",
                    "INSERT INTO traces (id,session_id,code_version_id,turn_generation,case_hash,status,total_observed,trace_truncated,termination_reason,runtime_version,steps_json,created_at,challenge_id) VALUES ('tb','b',1,1,'case','OK',0,0,'done','v','[]','t','ca')",
                    "INSERT INTO evidence_artifacts (id,session_id,challenge_id,code_version_id,turn_generation,case_hash,prediction_status,verification_status,minimization_status,trace_id,artifact_json,created_at) VALUES ('eb','b','cb',1,1,'case','P','V','M','tr','{}','t')",
                    "INSERT INTO artifacts (id,session_id,challenge_id,turn_id,schema_version,code_version_id,code_hash,turn_generation,verification_status,prediction_status,artifact_json,created_at) VALUES ('ar','a','ca2','ta','v',1,'hash',1,'V','P','{}','t')",
                    "DELETE FROM traces WHERE id='tr'",
                    "DELETE FROM challenges WHERE id='ca'",
                ):
                    with pytest.raises(psycopg.errors.ForeignKeyViolation):
                        conn.execute(statement)
                    conn.rollback()
                conn.execute("DELETE FROM sessions WHERE id='a'")
                assert conn.execute("SELECT count(*) FROM challenges WHERE id='ca'").fetchone()[0] == 0
                conn.commit()
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
