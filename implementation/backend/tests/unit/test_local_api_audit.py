"""Read-only route diagnostics must distinguish API health from route coverage."""

import httpx
import pytest
from scripts.check_local_api import audit_api, main, validated_origin


@pytest.mark.parametrize("ok, code", [(True, 0), (False, 1)])
def test_cli_exit_matches_diagnostic_result(monkeypatch, capsys, ok, code):
    monkeypatch.setattr("scripts.check_local_api.audit_api", lambda origin: {"ok": ok})
    assert main(["--base-url", "http://localhost:8000"]) == code
    assert '"ok"' in capsys.readouterr().out


def test_cli_rejects_external_origin_before_requests():
    with pytest.raises(SystemExit) as failure:
        main(["--base-url", "https://example.org"])
    assert failure.value.code == 2


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org",
        "http://127.0.0.1:8000/path",
        "http://user:password@127.0.0.1:8000",
        "http://localhost:8000?token=x",
        "http://localhost:8000#fragment",
        "ftp://localhost:8000",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:invalid",
    ],
)
def test_audit_rejects_external_or_credentialed_origins(url):
    with pytest.raises(ValueError, match="loopback"):
        validated_origin(url)


def test_route_audit_checks_real_endpoints_without_credentials_or_mutations():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            401 if "/interviews/" in request.url.path else 200, json={}
        )

    result = audit_api("http://127.0.0.1:5187", transport=httpx.MockTransport(handler))
    assert result["ok"] is True
    assert len(requests) == 6
    assert all(request.method == "GET" for request in requests)
    assert all(
        "authorization" not in request.headers
        and "x-workspace-token" not in request.headers
        for request in requests
    )
    assert all(
        "/stt" not in request.url.path and "/tts" not in request.url.path
        for request in requests
    )


@pytest.mark.parametrize(
    "failure", ["missing", "html", "unauthorized", "redirect", "timeout"]
)
def test_health_success_cannot_mask_missing_or_broken_product_routes(failure):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v1/learning/catalog":
            if failure == "timeout":
                raise httpx.ReadTimeout("Timed out", request=request)
            if failure == "html":
                return httpx.Response(200, text="<html>Frontend fallback</html>")
            if failure == "redirect":
                return httpx.Response(
                    302, headers={"Location": "https://example.org/private"}
                )
            return httpx.Response(
                404 if failure == "missing" else 401, json={"detail": "Not Found"}
            )
        return httpx.Response(
            401 if "/interviews/" in request.url.path else 200, json={}
        )

    result = audit_api("http://localhost:8000", transport=httpx.MockTransport(handler))
    assert result["ok"] is False
    assert any(
        probe["path"] == "/api/v1/learning/catalog" and not probe["ok"]
        for probe in result["probes"]
    )
    assert len(requests) == 6
    assert all(request.url.host == "localhost" for request in requests)
