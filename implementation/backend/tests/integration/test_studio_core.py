import uuid
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.main import create_app


def test_studio_capabilities_cas_and_replay(tmp_path):
    app = create_app(Settings(database_path=tmp_path/'test.db', tts_cache_dir=tmp_path/'audio', env='test'))
    with TestClient(app) as c:
        wid,sid = str(uuid.uuid4()),str(uuid.uuid4())
        wk,sk='w'*48,'s'*48
        w={'workspace_id':wid,'workspace_token':wk}
        r=c.post('/api/v1/studio/workspaces',json=w,headers={'X-Idempotency-Key':'workspace1'})
        assert r.status_code==200, r.text
        assert wk not in r.text
        assert c.post('/api/v1/studio/workspaces',json=w,headers={'X-Idempotency-Key':'workspace1'}).json()==r.json()
        body={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'}
        h={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey1'}
        r=c.post('/api/v1/studio/sessions',json=body,headers=h)
        assert r.status_code==200, r.text
        assert sk not in r.text
        assert c.post('/api/v1/studio/sessions',json=body,headers=h).json()==r.json()
        sh={'Authorization':'Bearer '+sk,'X-Idempotency-Key':'diagramkey1'}
        graph={'base_revision':0,'nodes':[{'node_id':'a','kind':'service','label':'A'}],'edges':[],'assumptions':{}}
        r=c.put(f'/api/v1/studio/sessions/{sid}/diagram',json=graph,headers=sh)
        assert r.status_code==200, r.text
        assert r.json()['validation']['mechanism_status']=='unknown'
        assert c.put(f'/api/v1/studio/sessions/{sid}/diagram',json=graph,headers=sh).json()==r.json()
        sh['X-Idempotency-Key']='diagramkey2'
        assert c.put(f'/api/v1/studio/sessions/{sid}/diagram',json=graph,headers=sh).status_code==409
        assert c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'old'},headers={**sh,'X-Idempotency-Key':'staleepoch1'}).status_code==409
        assert c.get(f'/api/v1/studio/sessions/{sid}',headers={'Authorization':'Bearer wrong'}).status_code==401
        snap=c.get(f'/api/v1/studio/sessions/{sid}',headers={'Authorization':'Bearer '+sk}).json()
        assert snap['diagram_revision']==1 and snap['epoch']==2


def test_review_retention_and_body_limit(tmp_path):
    from backend.app.db.migrations import open_connection
    from backend.app.studio.retention import sweep
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        assert c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace2'}).status_code==200
        body={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'}
        assert c.post('/api/v1/studio/sessions',json=body,headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey2'}).status_code==200
        auth={'Authorization':'Bearer '+sk}
        turn=c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'reasoning'},headers={**auth,'X-Idempotency-Key':'turnkey12'}).json()
        card=c.post(f'/api/v1/studio/sessions/{sid}/review-cards',json={'turn_id':turn['turn_id'],'prompt':'Revisit the tradeoff'},headers={**auth,'X-Idempotency-Key':'reviewkey1'})
        assert card.status_code==200,card.text
        rated=c.post(f"/api/v1/studio/workspaces/{wid}/reviews/{card.json()['card_id']}/rating",json={'rating':3},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'ratingkey1'})
        assert rated.status_code==200 and rated.json()['scheduler']=='fsrs-6.3.3'
        assert c.post(f'/api/v1/studio/sessions/{sid}/turns',content=b'x'*262145,headers={**auth,'X-Idempotency-Key':'too-big-1'}).status_code==413
        with open_connection(tmp_path/'test.db') as conn:
            conn.execute("UPDATE studio_workspaces SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(wid,))
        assert c.get(f'/api/v1/studio/sessions/{sid}',headers=auth).status_code==410
        sweep(tmp_path/'test.db')
        with open_connection(tmp_path/'test.db') as conn:
            assert conn.execute('SELECT count(*) FROM studio_turns WHERE session_id=?',(sid,)).fetchone()[0]==0
            assert conn.execute('SELECT count(*) FROM studio_review_cards WHERE session_id=?',(sid,)).fetchone()[0]==0


def test_concurrent_cas_only_one_wins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace3'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey3'})
        def edit(i):
            return c.put(f'/api/v1/studio/sessions/{sid}/diagram',json={'base_revision':0,'nodes':[{'node_id':str(i),'kind':'service','label':'service'}],'edges':[],'assumptions':{}},headers={'Authorization':'Bearer '+sk,'X-Idempotency-Key':f'concurrent{i}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(edit,[1,2]))
        assert sorted(results)==[200,409]


def test_replay_survives_restart_and_workspace_cannot_cross_own(tmp_path):
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test')
    wid,sid,other=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
    with TestClient(create_app(settings)) as c:
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace4'})
        c.post('/api/v1/studio/workspaces',json={'workspace_id':other,'workspace_token':'z'*48},headers={'X-Idempotency-Key':'workspace5'})
        body={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'}
        headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey4'}
        created=c.post('/api/v1/studio/sessions',json=body,headers=headers).json()
    with TestClient(create_app(settings)) as c:
        assert c.post('/api/v1/studio/sessions',json=body,headers=headers).json()==created
        assert c.get(f'/api/v1/studio/sessions/{sid}',headers={'Authorization':'Bearer '+'z'*48}).status_code==401


def test_pinned_scenario_controls_and_feedback_abstention(tmp_path):
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace6'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey6'})
        h={'Authorization':'Bearer '+sk}
        scenario=c.get(f'/api/v1/studio/sessions/{sid}/scenario',headers=h).json()
        assert scenario['version']=='1.0.0' and len(scenario['content_sha256'])==64
        assert 'hint_ladder' not in scenario and 'checks' not in scenario['constraint']
        assert c.get(f'/api/v1/studio/sessions/{sid}/evaluation',headers=h).status_code==200
        turn=c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'I need to measure this'},headers={**h,'X-Idempotency-Key':'turnkey67'}).json()
        feedback=c.post(f'/api/v1/studio/sessions/{sid}/feedback',json={'epoch':1,'turn_id':turn['turn_id']},headers={**h,'X-Idempotency-Key':'feedback6'}).json()
        assert feedback['status']=='abstained_insufficient_signal' and feedback['source']=='deterministic_fallback'
        hint=c.post(f'/api/v1/studio/sessions/{sid}/coach',json={'action':'hint'},headers={**h,'X-Idempotency-Key':'hintkey67'}).json()
        assert hint['hint_level']==1 and hint['text']


def test_assessment_assist_and_progression_gate(tmp_path):
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace7'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'guided_system_design','posture':'assessment','scenario_id':'SD-CORE-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey7'})
        h={'Authorization':'Bearer '+sk}
        def act(action,key): return c.post(f'/api/v1/studio/sessions/{sid}/coach',json={'action':action},headers={**h,'X-Idempotency-Key':key})
        assert act('advance','advance07').status_code==409
        assert act('hint','hintkey71').json()['assistance'] is True
        assert act('hint','hintkey72').status_code==409
        switched=c.post(f'/api/v1/studio/sessions/{sid}/posture',json={'posture':'teaching'},headers={**h,'X-Idempotency-Key':'switchkey7'})
        assert switched.status_code==200 and switched.json()['assessment_interrupted'] is True
        assert act('skip','skipkey77').json()['assistance'] is True
        assert c.get(f'/api/v1/studio/sessions/{sid}/summary',headers=h).json()['assistance_events']==3


def test_delete_purges_repo_defense_and_retains_anonymous_budget(tmp_path):
    from backend.app.db.migrations import open_connection
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid,rid=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace8'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey8'})
        with open_connection(tmp_path/'test.db') as db:
            db.execute("INSERT INTO repo_snapshots(id,workspace_id,source_kind,status,created_at) VALUES(?,?,'golden_curated','READY','2026-11-14T00:00:00+00:00')",(rid,wid))
            db.execute("INSERT INTO repo_defense_sessions VALUES('defense',?,?,?,'map','2026-11-14T00:00:00+00:00')",(sid,rid,wid))
            db.execute("INSERT INTO repo_defense_answers VALUES('answer','defense',1,'map','private','[]','2026-11-14T00:00:00+00:00')")
            db.execute("INSERT INTO studio_speech_usage VALUES('usage',?,1,'STT','speechkey','digest',1,0,1,'COMMITTED',datetime('now'),datetime('now'))",(sid,))
        r=c.delete(f'/api/v1/studio/sessions/{sid}',headers={'Authorization':'Bearer '+sk,'X-Idempotency-Key':'deletekey8'})
        assert r.status_code==200,r.text
        with open_connection(tmp_path/'test.db') as db:
            assert db.execute('SELECT count(*) FROM repo_defense_answers').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM studio_speech_usage').fetchone()[0]==0
            assert db.execute('SELECT request_count FROM studio_speech_deleted_daily').fetchone()[0]==1


def test_repo_body_limit_without_content_type(tmp_path):
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        r=c.post('/api/v1/repos/anything/evidence',content=b'x'*262145)
        assert r.status_code==413


def test_mock_deadline_auto_debrief(tmp_path):
    from backend.app.db.migrations import open_connection
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace9'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'architecture_mock_interview','posture':'assessment','scenario_id':'SD-CORE-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey9'})
        with open_connection(tmp_path/'test.db') as db:
            db.execute("UPDATE studio_sessions SET deadline_at='2000-01-01T00:00:00+00:00' WHERE id=?",(sid,))
        snap=c.get(f'/api/v1/studio/sessions/{sid}',headers={'Authorization':'Bearer '+sk}).json()
        assert snap['state']=='completed' and snap['phase']=='completed' and snap['epoch']==2
        assert c.get(f'/api/v1/studio/sessions/{sid}/evaluation',headers={'Authorization':'Bearer '+sk}).json()['status']!='withheld_until_debrief'


def test_repo_body_limit_chunked_and_duplicate_headers():
    import asyncio
    from backend.app.studio.body_limit import StudioBodyLimit
    messages=[{'type':'http.request','body':b'a'*150000,'more_body':True},{'type':'http.request','body':b'b'*150000,'more_body':False}]
    sent=[]; reached=[]
    async def app(scope,receive,send): reached.append(True)
    async def receive(): return messages.pop(0)
    async def send(message): sent.append(message)
    scope={'type':'http','method':'POST','path':'/api/v1/repos/id/evidence','headers':[(b'content-type',b'application/json'),(b'content-type',b'text/plain')]}
    asyncio.run(StudioBodyLimit(app)(scope,receive,send))
    assert not reached and sent[0]['status']==413


def test_switch_to_teaching_stops_mock_timer(tmp_path):
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspacex'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'architecture_mock_interview','posture':'assessment','scenario_id':'SD-CORE-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkeyx'})
        h={'Authorization':'Bearer '+sk}
        c.post(f'/api/v1/studio/sessions/{sid}/posture',json={'posture':'teaching'},headers={**h,'X-Idempotency-Key':'switchkeyx'})
        snap=c.get(f'/api/v1/studio/sessions/{sid}',headers=h).json()
        assert snap['posture']=='teaching' and snap['deadline_at'] is None
        assert c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':snap['epoch'],'text':'continued reasoning'},headers={**h,'X-Idempotency-Key':'turnkeyxx'}).status_code==200


def test_finish_creates_fsrs_card_and_reopen_is_explicit(tmp_path):
    from backend.app.db.migrations import open_connection
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspacef'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkeyf'})
        with open_connection(tmp_path/'test.db') as db: db.execute('UPDATE studio_sessions SET constraint_index=3 WHERE id=?',(sid,))
        h={'Authorization':'Bearer '+sk}
        def coach(action,key): return c.post(f'/api/v1/studio/sessions/{sid}/coach',json={'action':action},headers={**h,'X-Idempotency-Key':key})
        coach('teachback','teachbackf')
        c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'My restatement'},headers={**h,'X-Idempotency-Key':'turnkeyf1'})
        coach('transfer','transferf')
        turn=c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'My transfer attempt'},headers={**h,'X-Idempotency-Key':'turnkeyf2'}).json()
        finished=coach('finish','finishkeyf'); assert finished.status_code==200,finished.text
        with open_connection(tmp_path/'test.db') as db:
            row=db.execute('SELECT evidence_json,fsrs_json FROM studio_review_cards WHERE session_id=?',(sid,)).fetchone()
            assert turn['turn_id'] in row['evidence_json'] and row['fsrs_json']
        assert c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':2,'text':'edit'},headers={**h,'X-Idempotency-Key':'turnkeyf3'}).status_code==409
        reopened=coach('reopen','reopenkeyf'); assert reopened.status_code==200
        assert c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':3,'text':'edit'},headers={**h,'X-Idempotency-Key':'turnkeyf4'}).status_code==200


def test_repo_four_phases_gate_progress_on_owned_verified_citations(tmp_path):
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspacerepo'})
        rh={'X-Workspace-Id':wid,'X-Workspace-Token':wk}
        imported=c.post('/api/v1/repos/ingest',headers=rh,json={'source_kind':'golden_curated','source_locator':'REPO-EXP-02'})
        assert imported.status_code==202,imported.text
        rid=imported.json()['snapshot_id']
        session=c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'repo_exploration','posture':'teaching','scenario_id':'REPO-EXP-02','repo_snapshot_id':rid},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionrepo'})
        assert session.status_code==200,session.text
        h={'Authorization':'Bearer '+sk}; path=f'/api/v1/studio/sessions/{sid}'
        assert c.get(path+'/evaluation',headers=h).json()['status']=='unknown'
        assert c.post(path+'/coach',json={'action':'advance'},headers={**h,'X-Idempotency-Key':'advancerepo0'}).status_code==409
        results=c.get(f'/api/v1/repos/{rid}/search',params={'q':'deliver'},headers=rh).json()['results']
        citation={k:results[0][k] for k in ('path','symbol','start_line','end_line','chunk_hash')}
        dh={**rh,'X-Session-Token':sk}
        assert c.post(f'/api/v1/repos/{rid}/defense/start',headers=dh,json={'studio_session_id':sid}).status_code==200
        for i,phase in enumerate(('map','derive','defend','reflect')):
            answer=c.post(f'/api/v1/repos/{rid}/defense/answer',headers=dh,json={'studio_session_id':sid,'expected_phase':phase,'answer':'A cited observation','citations':[citation]})
            assert answer.status_code==200,answer.text
            assert c.get(path+'/evaluation',headers=h).json()['status']=='satisfied_under_declared_assumptions'
            advanced=c.post(path+'/coach',json={'action':'advance'},headers={**h,'X-Idempotency-Key':f'advancerepo{i+1}'})
            assert advanced.status_code==200,advanced.text
            if i<3: assert c.get(path+'/evaluation',headers=h).json()['status']=='unknown'


def test_mock_pause_subsecond_keeps_resumable_second(tmp_path):
    from backend.app.db.migrations import open_connection
    from datetime import datetime,timedelta,timezone
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspacetimer'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'architecture_mock_interview','posture':'assessment','scenario_id':'SD-CORE-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessiontimer'})
        with open_connection(tmp_path/'test.db') as db: db.execute('UPDATE studio_sessions SET deadline_at=? WHERE id=?',((datetime.now(timezone.utc)+timedelta(milliseconds=800)).isoformat(),sid))
        r=c.post(f'/api/v1/studio/sessions/{sid}/timer/pause',headers={'Authorization':'Bearer '+sk,'X-Idempotency-Key':'timerpause1'})
        assert r.status_code==200 and r.json()['state']=='paused' and r.json()['remaining_seconds']==1


def test_capacity_arithmetic_handles_arbitrary_integer():
    from backend.app.studio.validation import evaluate
    graph={'nodes':[],'edges':[],'assumptions':{'read_rps':10**400,'miss_fraction':0.5}}
    assert 'origin_reads_per_second' not in evaluate(graph)['calculations']


def test_studio_read_connections_close_after_requests(tmp_path,monkeypatch):
    import sqlite3
    import backend.app.studio.routes as routes
    opened=[]; original=routes.connection
    def tracked(request):
        db=original(request); opened.append(db); return db
    monkeypatch.setattr(routes,'connection',tracked)
    app=create_app(Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test'))
    with TestClient(app) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspaceclose'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionclose'})
        assert c.get(f'/api/v1/studio/sessions/{sid}/scenario',headers={'Authorization':'Bearer '+sk}).status_code==200
    assert opened
    for db in opened:
        try: db.execute('SELECT 1')
        except sqlite3.ProgrammingError: continue
        raise AssertionError('studio connection was not closed')
