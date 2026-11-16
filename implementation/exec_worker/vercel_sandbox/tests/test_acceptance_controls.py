"""Validate the fixed acceptance plan without running code or creating VMs."""
from __future__ import annotations

import ast
import json

import pytest

from backend.app.models.domain import ExecutionBudgetConfig
from exec_worker.vercel_sandbox.acceptance import LIMITS
from exec_worker.vercel_sandbox.live_acceptance import CONTROLS, _control_budget


@pytest.mark.parametrize("name,body", CONTROLS.items())
def test_fixed_control_source_and_budget_are_valid(name: str, body: str):
    source = "def f():\n" + "\n".join(" " + line for line in body.splitlines())
    ast.parse(source)
    budget = _control_budget(name).model_dump(mode="json")
    ExecutionBudgetConfig.model_validate(budget)
    for field, ceiling in LIMITS.items():
        assert 0 < budget[field] <= ceiling


def test_failed_acceptance_records_safe_diagnostic_and_provider_absence(tmp_path, monkeypatch):
    from exec_worker.vercel_sandbox import live_acceptance
    from exec_worker.vercel_sandbox.adapter import TransportFailure
    diagnostic = {"failure": {"phase": "cgroup_enable", "error_type": "OSError", "errno": 30},
                  "cleanup_failures": []}
    class FailureTransport:
        cleanup_obligations = set()
        def run(self, **kwargs):
            raise TransportFailure("supervisor setup failed", phase="cgroup_enable",
                                   supervisor_diagnostic=diagnostic, provider_deletion_verified=True)
    monkeypatch.setattr(live_acceptance, "GuardedAcceptanceTransport", lambda transport: transport)
    monkeypatch.setattr(live_acceptance, "verify_sdk_creation_source", lambda: None)
    monkeypatch.setattr(live_acceptance, "runner_digest", lambda: "f" * 64)
    monkeypatch.setattr(live_acceptance, "version", lambda name: live_acceptance.SDK_VERSIONS[name])
    path = tmp_path / "failure.json"
    evidence = live_acceptance.run_acceptance(FailureTransport(), path)
    assert evidence["accepted"] is False
    assert not any(evidence["checks"].values())
    assert evidence["controls"] == []
    assert evidence["blockers"][0]["supervisor_diagnostic"] == diagnostic
    assert evidence["blockers"][0]["provider_deletion_verified"] is True
    assert json.loads(path.read_text()) == evidence
