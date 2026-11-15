"""Actual pinned SDK creation requests cross only an inert HTTP transport."""
from datetime import timedelta

import pytest
import httpx2 as httpx
from vercel.sandbox.sync import SyncSandboxClient, SandboxServiceOptions, SandboxCredentials, NetworkPolicy

from exec_worker.vercel_sandbox.adapter import single_attempt_creation
from exec_worker.vercel_sandbox import acceptance


@pytest.mark.parametrize('guarded,expected', [(False,3),(True,1)])
def test_ambiguous_creation_has_exactly_one_post_with_guard(guarded, expected):
    requests = []
    def failed(request):
        requests.append(request)
        raise httpx.ReadTimeout('Controlled inert ambiguity',request=request)
    client = SyncSandboxClient.create(options=SandboxServiceOptions(
        base_url='https://sandbox.example.invalid',
        credentials_factory=lambda: SandboxCredentials('inert-token','inert-team','inert-project'),
        request_timeout=timedelta(seconds=5)),
        httpx_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(failed)))
    async def no_wait(_seconds):
        pass
    try:
        client._service.api_client._sleep = no_wait
        if guarded:
            single_attempt_creation(client)
        with pytest.raises(httpx.ReadTimeout,match='inert ambiguity'):
            client.create_sandbox(name='viva-inv-'+'a'*24,persistent=False,
                execution_time_limit=20,network_policy=NetworkPolicy.deny_all(),image='fixed-test-image')
        assert len(requests)==expected
        assert all(request.method=='POST' and request.url.path=='/v3/sandboxes' for request in requests)
    finally:
        client.close()


def test_sdk_source_drift_fails_before_any_request(monkeypatch):
    requests = []
    client = SyncSandboxClient.create(httpx_client_factory=lambda: httpx.Client(
        transport=httpx.MockTransport(lambda request: requests.append(request))))
    monkeypatch.setitem(acceptance.SDK_CREATION_SOURCE_SHA256,'vercel.sandbox._internal.api_client','0'*64)
    try:
        with pytest.raises(ValueError,match='Unaccepted'):
            single_attempt_creation(client)
        assert requests==[]
    finally:
        client.close()
