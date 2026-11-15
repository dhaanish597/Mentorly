"""Fail-closed public readiness from operator evidence and authenticated worker health."""
from __future__ import annotations

import json
from typing import Literal

import httpx
import asyncio

from backend.app.core.config import Settings

ExecutionReadiness = Literal["DISABLED", "BLOCKED_EXTERNAL", "READY"]


def has_operator_acceptance(settings: Settings) -> bool:
    """This checks claims only; the worker must bind them to its fresh runtime."""
    marker = settings.isolation_acceptance_file
    if marker is None:
        return False
    try:
        if not marker.is_file() or marker.stat().st_size > 65536:
            return False
        evidence = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(evidence, dict):
        return False
    return (
        evidence.get("status") == "VERIFIED"
        and evidence.get("runtime") == "runsc"
        and evidence.get("adversarial_acceptance_passed") is True
        and evidence.get("passed") is True
        and all(isinstance(evidence.get(key), str) and evidence[key] for key in (
            "runner_image_id", "runsc_sha256", "runtime_bundle_sha256",
            "runtime_version", "docker_daemon_id",
        ))
        and isinstance(evidence.get("runtime_config"), dict)
    )


async def probe_execution_readiness(settings: Settings) -> ExecutionReadiness:
    """Never equate a configuration flag or operator marker with live acceptance."""
    if not settings.allow_public_custom_code:
        return "DISABLED"
    if settings.execution_runtime == 'vercel_sandbox':
        try:
            from backend.app.core.worker_factory import get_worker_client
            worker = get_worker_client(settings)
            preflight = await asyncio.to_thread(worker.check_preflight)
            return 'READY' if preflight.ready and preflight.acceptance_verified else 'BLOCKED_EXTERNAL'
        except Exception:
            return 'BLOCKED_EXTERNAL'
    if not settings.internal_worker_secret or not has_operator_acceptance(settings):
        return "BLOCKED_EXTERNAL"
    try:
        async with httpx.AsyncClient(timeout=2.0, follow_redirects=False) as client:
            response = await client.get(
                f"{settings.exec_worker_url.rstrip('/')}/internal/health",
                headers={"X-Internal-Worker-Secret": settings.internal_worker_secret.get_secret_value()},
            )
        if response.status_code != 200:
            return "BLOCKED_EXTERNAL"
        health = response.json()
    except (httpx.HTTPError, ValueError):
        return "BLOCKED_EXTERNAL"
    if isinstance(health, dict) and health.get("sandbox_ready") is True and health.get("acceptance_verified") is True:
        return "READY"
    return "BLOCKED_EXTERNAL"
