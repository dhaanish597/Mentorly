"""HTTP timeout protocol tests; no network and no source execution."""
from uuid import uuid4

import httpx
import pytest

from backend.app.models.domain import ExecutionBudgetConfig, ExecutionRequest, RevisionRef, VerifyJobRequest
from backend.app.orchestration.worker_client import WorkerClient, BrokerCommunicationError


@pytest.mark.parametrize("acknowledgement", [True, False, "false", "true", 1, None])
def test_cancel_requires_an_explicit_json_boolean_acknowledgement(acknowledgement):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"cancelled":acknowledgement}))
    with httpx.Client(transport=transport) as http:
        worker = WorkerClient(base_url="http://protocol-only.invalid", internal_worker_secret="test-only", http_client=http)
        assert worker.cancel(uuid4()) is (acknowledgement is True)


def revision():
    return RevisionRef(session_id=uuid4(),exercise_id='ex1_shortest_subarray',spec_version='v1_positive_only',
        code_version_id=1,code_hash='a'*64,turn_generation=1)


@pytest.mark.parametrize('kind,expected', [('execute',9.0),('verify',185.0)])
def test_http_deadline_matches_worker_job_budget_and_cancels_timeout(kind,expected):
    calls = []
    class DeadlineTransport:
        def post(self,url,**kwargs):
            calls.append((url,kwargs))
            if '/cancel/' in url:
                return httpx.Response(200,json={'cancelled':True})
            raise httpx.ReadTimeout('fixed transport timeout')
    client = WorkerClient(base_url='http://protocol-only.invalid',internal_worker_secret='protocol-fixture',
        http_client=DeadlineTransport())
    budget = ExecutionBudgetConfig(startup_deadline_ms=5000,invocation_wall_ms=2000,job_wall_ms=180000)
    if kind == 'execute':
        req = ExecutionRequest(job_id=uuid4(),revision=revision(),source_code='protocol fixture',
            input_args={'nums':[1],'target':1},case_hash='b'*64,budget=budget)
        method = client.submit_execution
    else:
        req = VerifyJobRequest(job_id=uuid4(),revision=revision(),source_code='protocol fixture',budget=budget)
        method = client.submit_verify
    with pytest.raises(BrokerCommunicationError):
        method(req)
    assert calls[0][1]['timeout'] == expected
    assert calls[1][0].endswith('/internal/cancel/'+str(req.job_id))


def test_malformed_worker_response_is_communication_failure():
    class MalformedTransport:
        def post(self,url,**kwargs):
            return httpx.Response(200,content=b'not-json')
    client = WorkerClient(base_url='http://protocol-only.invalid',internal_worker_secret='protocol-fixture',
        http_client=MalformedTransport())
    req = ExecutionRequest(job_id=uuid4(),revision=revision(),source_code='protocol fixture',
        input_args={'nums':[1],'target':1},case_hash='b'*64)
    with pytest.raises(BrokerCommunicationError):
        client.submit_execution(req)


@pytest.mark.parametrize('kind', ['execute','verify','trace'])
def test_invalid_worker_model_is_generic_communication_failure(kind):
    from backend.app.models.domain import TraceRequest
    class InvalidModelTransport:
        def post(self,url,**kwargs):
            return httpx.Response(200,json={'private_payload':'DO_NOT_ECHO_WORKER_PAYLOAD','status':'invented'})
    client = WorkerClient(base_url='http://protocol-only.invalid',internal_worker_secret='protocol-fixture',
        http_client=InvalidModelTransport())
    if kind == 'verify':
        request = VerifyJobRequest(job_id=uuid4(),revision=revision(),source_code='protocol fixture')
        method = client.submit_verify
    elif kind == 'trace':
        request = TraceRequest(job_id=uuid4(),trace_id=uuid4(),revision=revision(),source_code='protocol fixture',
            input_args={'nums':[1],'target':1},case_hash='b'*64)
        method = client.submit_trace
    else:
        request = ExecutionRequest(job_id=uuid4(),revision=revision(),source_code='protocol fixture',
            input_args={'nums':[1],'target':1},case_hash='b'*64)
        method = client.submit_execution
    with pytest.raises(BrokerCommunicationError) as failure:
        method(request)
    assert 'DO_NOT_ECHO_WORKER_PAYLOAD' not in str(failure.value)
    assert 'invented' not in str(failure.value)
