"""Opt-in PostgreSQL lifecycle and concurrent deletion checks."""
import os
import threading
import uuid
import pytest
from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.jobs import JOBS_MIGRATION
from backend.app.db.postgres.coaching import AuthorizationError, Revision, save_code_version
from backend.app.db.postgres.session_lifecycle import (SESSION_LIFECYCLE_MIGRATION, create_session, restore_session,
 delete_session, expire_session, finalize_deletion)

DSN=os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')


def test_lifecycle_and_worker_cleanup():
    psycopg=pytest.importorskip('psycopg')
    from psycopg import sql
    import hashlib
    schema='viva_lifecycle_'+uuid.uuid4().hex
    with psycopg.connect(DSN,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with psycopg.connect(DSN) as c:
                c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema))); c.commit()
                apply_migrations(c,[CORE_MIGRATION,JOBS_MIGRATION,SESSION_LIFECYCLE_MIGRATION])
                s=create_session(c,exercise_id='e',spec_version='v',language_mode='en',interaction_mode='text',source_code='original')
                sid,token=s['session_id'],s['token']
                assert restore_session(c,session_id=sid,token=token)['source_code']=='original'
                with pytest.raises(AuthorizationError): restore_session(c,session_id=sid,token='wrong')
                job,owner=uuid.uuid4(),uuid.uuid4()
                fence=c.execute("""INSERT INTO viva_coaching_jobs(id,session_id,idempotency_key,request_digest,exercise_id,spec_version,code_version_id,code_hash,turn_generation,status,owner,lease_expires_at)
                  VALUES (%s,%s,'key','digest','e','v',1,%s,0,'RUNNING',%s,clock_timestamp()+interval '5 minutes') RETURNING fence""",(job,sid,s['code_hash'],owner)).fetchone()[0]
                c.execute("INSERT INTO jobs (id,session_id,job_type,status,turn_generation,code_version_id,created_at,updated_at) VALUES ('legacy',%s,'run','RUNNING',0,1,'t','t')",(sid,))
                c.commit()
                delete_session(c,session_id=sid,token=token)
                assert not finalize_deletion(c,session_id=sid)
                # Direct SQL simulates a future, independently authenticated cleanup
                # authority; the lifecycle module provides no acknowledgement API.
                c.execute("UPDATE viva_session_cleanup SET audio_pending=false WHERE session_id=%s",(sid,))
                c.execute("UPDATE viva_coaching_jobs SET status='CANCELLED',owner=NULL,lease_expires_at=NULL WHERE id=%s",(job,))
                c.commit()
                assert not finalize_deletion(c,session_id=sid)
                assert c.execute("SELECT job_id FROM viva_session_legacy_cleanup WHERE session_id=%s",(sid,)).fetchone()==('legacy',)
                c.execute("DELETE FROM viva_session_legacy_cleanup WHERE session_id=%s",(sid,)); c.commit()
                assert finalize_deletion(c,session_id=sid)
                expired=create_session(c,exercise_id='e',spec_version='v',language_mode='en',interaction_mode='text',source_code='x')
                c.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=%s",(expired['session_id'],)); c.commit()
                assert expire_session(c,session_id=expired['session_id'])
                c.execute('UPDATE viva_session_cleanup SET audio_pending=false WHERE session_id=%s',(expired['session_id'],)); c.commit()
                assert finalize_deletion(c,session_id=expired['session_id'])
                # A held session lock forces save to wait for tombstone commit.
                race=create_session(c,exercise_id='e',spec_version='v',language_mode='en',interaction_mode='text',source_code='x')
                sid=race['session_id']; digest=hashlib.sha256(race['token'].encode()).hexdigest()
                rev=Revision(sid,'e','v',1,race['code_hash'],0); outcomes=[]
                c.execute('SELECT id FROM sessions WHERE id=%s FOR UPDATE',(sid,))
                def save():
                    with psycopg.connect(DSN) as other:
                        other.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema))); other.commit()
                        try: save_code_version(other,session_id=sid,token_hash=digest,expected=rev,source_code='new',code_hash='h')
                        except AuthorizationError: outcomes.append('denied')
                thread=threading.Thread(target=save); thread.start()
                c.execute("UPDATE sessions SET deleted_at='now' WHERE id=%s",(sid,)); c.commit(); thread.join(timeout=5)
                assert not thread.is_alive() and outcomes==['denied']
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
