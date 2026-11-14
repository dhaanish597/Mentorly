"""Actual HTTP persistence/auth journey; never substitutes an execution oracle."""
from uuid import uuid4
import json
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.main import create_app


def test_authenticated_hidden_prediction_and_unavailable_execution(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path/'app.db', tts_cache_dir=tmp_path/'tts', gnani_api_key=None)
    with TestClient(create_app(settings)) as client:
        created = client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v2_negatives_allowed'}).json()
        sid = created['session_id']; path = '/api/v1/sessions/'+sid
        def mutate(suffix,body,key=None):
            return client.post(path+suffix,json=body,headers={'Authorization':'Bearer '+created['session_token'],'X-Idempotency-Key':key or str(uuid4())})
        auth={'Authorization':'Bearer '+created['session_token']}
        assert client.get(path).status_code == 401
        assert client.get(path,headers=auth).status_code == 200
        rev=created['revision']
        assert mutate('/challenges',{'purpose':'DIAGNOSTIC','revision':rev}).status_code==409
        ack=mutate('/spec-ack',{'spec_version':rev['spec_version'],'revision':rev})
        assert ack.status_code==200,ack.text
        key=str(uuid4());body={'purpose':'DIAGNOSTIC','revision':rev}
        response=mutate('/challenges',body,key)
        assert response.status_code==200,response.text
        challenge=response.json();rev=challenge['revision']
        assert rev['turn_generation']==1
        assert mutate('/challenges',body,key).json()==challenge
        assert mutate('/challenges',{**body,'purpose':'TRANSFER'},key).status_code==409
        assert all(token not in response.text for token in ('reference_output','actual_observation','return_value'))
        turn=mutate('/turns/text',{'text':'It returns 2','revision':rev,'challenge_id':challenge['challenge_id']})
        assert turn.status_code==200,turn.text
        turn=turn.json()
        claim=turn['proposed_claim'];claim['confirmed_at']='2026-11-13T17:00:00Z'
        confirmed=mutate('/turns/'+turn['turn_id']+'/confirm-claim',{'revision':rev,'challenge_id':challenge['challenge_id'],'claim':claim})
        assert confirmed.status_code==200,confirmed.text
        result=confirmed.json()
        assert result['artifact']['verification_report']['status']=='EXECUTION_UNAVAILABLE'
        assert result['artifact']['prediction_status']=='NOT_EVALUATED'
        assert result['learning_state']!='PRACTICE_CHECKPOINT_COMPLETED'
        export=client.get(path+'/export',headers=auth)
        assert export.status_code==200,export.text
        assert mutate('/playback-ack',{'playback_id':str(uuid4()),'revision':rev,'playback_status':'COMPLETED','played_duration_ms':1}).status_code==409
        deleted=client.delete(path,headers={**auth,'X-Idempotency-Key':str(uuid4())})
        assert deleted.status_code==200,deleted.text
        assert client.get(path,headers=auth).status_code==410
        import sqlite3
        with sqlite3.connect(settings.database_path) as conn:
            assert conn.execute('SELECT count(*) FROM code_versions WHERE session_id=?',(sid,)).fetchone()[0]==0


def test_wrong_exercise_spec_pair_is_rejected(tmp_path):
    settings=Settings(_env_file=None,database_path=tmp_path/'pair.db',tts_cache_dir=tmp_path/'tts')
    with TestClient(create_app(settings)) as client:
        response=client.post('/api/v1/sessions',json={'exercise_id':'ex2_binary_search','spec_version':'v1_positive_only'})
        assert response.status_code==422
