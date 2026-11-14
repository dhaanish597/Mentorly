"""Learner fixture execution is always a fresh, no-network runsc invocation.

Protocol and serializer unit tests remain runnable offline. Execution/trace
acceptance is explicitly blocked on a Linux gVisor host; there is no host
interpreter or ordinary-Docker fallback.
"""
from __future__ import annotations

import json
import unittest
from typing import Any
from uuid import uuid4

from backend.app.models.domain import ExecutionBudgetConfig
from exec_worker.runner.protocol import FRAME_BEGIN, FRAME_END, parse_runner_frame
from exec_worker.worker_app.sandbox_runner import GVisorSandboxRunner


def execute_payload_in_gvisor(payload: dict[str, Any], **_unused: Any) -> dict[str, Any]:
    runner = GVisorSandboxRunner()
    preflight = runner.check_preflight()
    if not preflight.ready:
        raise unittest.SkipTest('BLOCKED_EXTERNAL: genuine gVisor acceptance: '+preflight.summary)
    budget = ExecutionBudgetConfig(**payload.get('budget', {}))
    outcome = runner._launch_disposable_container(
        job_id=uuid4(), payload=payload, budget=budget,
        max_stdout_pipe_bytes=budget.max_trace_bytes+budget.max_stdout_bytes,
        runner_image=preflight.runner_image,
    )
    if outcome.returncode != 0 or outcome.timed_out or outcome.startup_timed_out:
        raise AssertionError(f'Fresh gVisor invocation failed: {outcome}')
    parse_runner_frame(outcome.stdout_text, expected_mode=payload.get('mode', 'execute'))
    raw = outcome.stdout_text.split(FRAME_BEGIN, 1)[1].split(FRAME_END, 1)[0]
    return json.loads(raw)
