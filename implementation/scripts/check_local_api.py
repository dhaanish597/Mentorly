"""Check local product route coverage, not only health. No credentials or writes."""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

PROBES = (
    ("/api/v1/meta/health", (200,)),
    ("/api/v1/meta/exercises", (200,)),
    ("/api/v1/learning/catalog", (200,)),
    ("/api/v1/speech/capabilities", (200,)),
    # Without credentials, denial proves the route exists; it does not prove auth works.
    ("/api/v1/interviews/config", (401, 422)),
    ("/api/v1/interviews/catalog", (401, 422)),
)


def validated_origin(value: str) -> str:
    """Do not send diagnostic requests to external services or credentialed URLs."""
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Use a credential-free HTTP loopback origin without a path, query or fragment."
        )
    try:
        port = url.port
    except ValueError as exc:
        raise ValueError("Use a valid loopback origin port.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Use a valid loopback origin port.")
    return value.rstrip("/")


def _probe(
    client: httpx.Client, path: str, statuses: tuple[int, ...]
) -> dict[str, Any]:
    try:
        response = client.get(path)
    except httpx.HTTPError:
        return {
            "path": path,
            "status": None,
            "ok": False,
            "reason": "Backend connection failed or timed out.",
        }
    try:
        response.json()
        is_json = True
    except ValueError:
        is_json = False
    ok = response.status_code in statuses and is_json
    if ok:
        reason = (
            "JSON endpoint reachable."
            if statuses == (200,)
            else "Protected route exists; authenticated behavior not tested."
        )
    elif response.status_code == 404:
        reason = "API route missing. Restart the backend to load current source; check the frontend proxy target."
    elif not is_json:
        reason = "Non-JSON response. Check proxy routing; an HTML app fallback is not an API response."
    else:
        reason = "Unexpected HTTP status. This check does not retry requests."
    return {"path": path, "status": response.status_code, "ok": ok, "reason": reason}


def audit_api(
    base_url: str, *, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    origin = validated_origin(base_url)
    with httpx.Client(
        base_url=origin,
        transport=transport,
        timeout=5.0,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        probes = [_probe(client, path, statuses) for path, statuses in PROBES]
    return {
        "base_url": origin,
        "ok": all(probe["ok"] for probe in probes),
        "probes": probes,
        "scope": "Read-only route diagnostics; not browser, provider, authentication or code-execution acceptance.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    try:
        result = audit_api(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
