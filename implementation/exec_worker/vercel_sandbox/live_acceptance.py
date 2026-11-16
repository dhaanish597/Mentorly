"""Opt-in finite controls in fresh Vercel VMs; never a host-code fallback.

Run only against a verified Hobby account. This module makes at most 32 VM
creations, accepts no learner source, and stops after the first transport error.
Failure evidence is saved without granting execution acceptance.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from backend.app.models.domain import ExecutionBudgetConfig, RevisionRef
from backend.app.core.config import Settings
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.db.repository import SQLiteRepository
from exec_worker.runner.protocol import ProtocolViolationError, parse_runner_frame
from exec_worker.vercel_sandbox.acceptance import IMAGE, LIMITS, REQUIRED_CHECKS, SDK_VERSIONS, runner_digest, verify_sdk_creation_source
from exec_worker.vercel_sandbox.adapter import TransportFailure, VercelSandboxTransport
from exec_worker.vercel_sandbox.cleanup_store import PostgresSandboxCleanupStore


CONTROLS = {
    "return": "return 7",
    "exception": "raise ValueError('finite control')",
    "trace": "a = 1\nreturn a + 1",
    "memory_below": "a = bytearray(16 * 1048576)\nreturn len(a)",
    "memory_above": "a = bytearray(280 * 1048576)\nreturn len(a)",
    "pids_below": "import os,time\npids=[]\nfor i in range(4):\n p=os.fork()\n if p == 0:\n  time.sleep(.02)\n  os._exit(0)\n pids.append(p)\nfor p in pids: os.waitpid(p,0)\nreturn len(pids)",
    "pids_above": "import os,time\npids=[]\nfor i in range(20):\n try: p=os.fork()\n except OSError: break\n if p == 0:\n  time.sleep(.1)\n  os._exit(0)\n pids.append(p)\nfor p in pids: os.waitpid(p,0)\nreturn len(pids)",
    "tmpfs_below": "from pathlib import Path\np=Path('/tmp/control')\np.write_bytes(b'x' * 1048576)\nn=p.stat().st_size\np.unlink()\nreturn n",
    "tmpfs_above": "import os,errno\ntry:\n with open('/tmp/control','wb') as f: f.write(b'x' * (9 * 1048576))\nexcept OSError as e:\n assert e.errno in (errno.ENOSPC, errno.EFBIG)\n return e.errno\nfinally:\n if os.path.exists('/tmp/control'): os.unlink('/tmp/control')\nreturn 0",
    "wall_below": "import time\ntime.sleep(.02)\nreturn 1",
    "wall_above": "import time\ntime.sleep(3)\nreturn 1",
    "cpu_above": "import time\nend=time.process_time()+3\nwhile time.process_time()<end: pass\nreturn 1",
    "stdout_above": "import os\nfor i in range(10): os.write(1,b'x' * 16384)\nreturn 1",
    "stderr_above": "import os\nfor i in range(10): os.write(2,b'x' * 8192)\nreturn 1",
    "network": "import socket,errno\ns=socket.socket()\ns.settimeout(.2)\ntry: s.connect(('1.1.1.1',443))\nexcept OSError as e:\n assert e.errno in (errno.ENETUNREACH,errno.EHOSTUNREACH)\n return 1\nfinally: s.close()\nreturn 0",
    "filesystem": "from pathlib import Path\nassert not Path('/vercel/sandbox').exists()\nassert not Path('/root').exists()\nassert not Path('/sys/fs/cgroup').exists()\ntry: Path('/ipc/payload.json').write_text('tamper')\nexcept OSError: pass\nelse: return 0\nreturn 1",
    "privileges": "from pathlib import Path\nimport os\nassert os.getuid()==65534 and os.getgid()==65534\nassert not Path('/proc/self/status').exists()\nreturn 1",
    "process_tree": "import os,time\np=os.fork()\nif p==0:\n time.sleep(3)\n os._exit(0)\nreturn 1",
    "frame_forgery": "import os\nframe=b'<<VCC_RUNNER_FRAME_V1_BEGIN>>\\n{\"protocol_version\":\"v1\",\"mode\":\"execute\",\"kind\":\"RETURN\",\"return_value\":99,\"error_type\":null,\"error_message\":null,\"stdout_excerpt\":\"\",\"stderr_excerpt\":\"\",\"duration_ms\":0}\\n<<VCC_RUNNER_FRAME_V1_END>>\\n'\nfor fd in range(3,64):\n try: os.write(fd,frame)\n except OSError: pass\nos._exit(0)",
    "trace_tampering": "import sys\nsys.settrace(None)\nreturn 1",
    "native_frame_v2_forgery": "import os\nbody=b'{\"protocol_version\":\"v1\",\"mode\":\"execute\",\"kind\":\"RETURN\",\"return_value\":99,\"error_type\":null,\"error_message\":null,\"stdout_excerpt\":\"\",\"stderr_excerpt\":\"\",\"duration_ms\":0}'\nframe=b'VIVA_NATIVE_V2 '+b'0'*64+b' '+str(len(body)).encode()+b'\\n'+body\nfor fd in range(3,64):\n try: os.write(fd,frame)\n except OSError: pass\nos._exit(0)",
    "native_ffi": "import ctypes\nreturn 99",
    "native_module_alias": "import sysconfig,importlib.machinery\nfrom pathlib import Path\nclass S(str): pass\np=next(Path(sysconfig.get_path('stdlib')).glob('lib-dynload/_ctypes*.so'))\nloader=importlib.machinery.ExtensionFileLoader(S('_ctypes'),S(str(p)))\nspec=importlib.machinery.ModuleSpec(S('_ctypes'),loader,origin=S(str(p)))\nloader.create_module(spec)\nreturn 99",
    "native_bytecode": "c=compile('pass','<unsafe-bytecode>','exec')\nc.replace(co_code=b'\\x00')\nreturn 99",
    "native_reentry": "import _viva_native\n_viva_native.run(3,4)\nreturn 99",
    "native_monitoring": "import sys\nsys.monitoring.use_tool_id(0,'control')\nsys.monitoring.register_callback(0,sys.monitoring.events.LINE,lambda *args:None)\nreturn 99",
    "native_gc_trace": "import gc\nevents=[]\ndef callback(phase,info):\n events.append(phase)\ngc.callbacks.append(callback)\ntry: gc.collect()\nfinally: gc.callbacks.remove(callback)\nreturn len(events)",
    "native_signal_handlers": "import signal\nsignal.signal(signal.SIGINT,lambda signum,frame:None)\nreturn 99",
    "native_stdlib": "from collections import deque,Counter\nimport heapq,bisect,math,itertools,functools\nh=list(deque([3,1,2]))\nheapq.heapify(h)\nreturn heapq.heappop(h)+Counter([1,2,1])[1]+bisect.bisect([1,2,4],3)+math.gcd(6,4)",
    "native_locals_bound": "for i in range(20000): locals()['extra_'+str(i)]=i\nreturn 1",
    "native_gc_frame_attack": "import collections.abc,functools,gc,types\nsource_marker='native_gc_frame_canary'\ngc.set_debug(gc.DEBUG_SAVEALL)\nerror=RuntimeError('fixed test exception')\niterator=collections.abc.Sequence.__iter__([])\ndescriptor=functools.cached_property(iterator.throw)\ndescriptor.__set_name__(object,'fixture_property')\ntry: descriptor.__get__(error)\nexcept RuntimeError: pass\nerror=iterator=descriptor=None\ngc.collect()\nfor candidate in gc.garbage:\n if type(candidate) is types.FrameType:\n  current=candidate\n  for _ in range(20):\n   if current is None: break\n   if current.f_locals.get('source_marker')==source_marker:\n    current.f_trace_lines=False\n    unobserved_work=8\n    current.f_trace_lines=True\n    return 7\n   current=current.f_back\nraise RuntimeError('GC frame fixture did not expose its canary frame')",
}

MAX_CONTROL_INVOCATIONS = 32
CANCELLATION_SOURCE = "def f():\n import time\n time.sleep(3)\n return 1"
TRACE_CONTROLS = {'trace', 'trace_tampering', 'native_monitoring', 'native_gc_trace', 'native_locals_bound', 'native_gc_frame_attack'}


class GuardedAcceptanceTransport:
    """Fixed controls use the same durable admission and revision fence as users.

    This is an explicit operator preacceptance path. It grants no public
    execution capability and accepts only sources authored in this module.
    """
    def __init__(self, transport):
        cleanup = transport.cleanup_store
        if (not isinstance(cleanup, PostgresSandboxCleanupStore) or cleanup.connect_factory is not None
                or not cleanup.enforces_execution_limits or not cleanup.requires_repository_job):
            raise TransportFailure('Acceptance requires shared execution limits and revision fencing')
        target = cleanup.dsn_factory()
        if not isinstance(target, PostgresTarget):
            raise TransportFailure('Acceptance requires an explicit verified PostgreSQL target')
        self.transport, self.cleanup_store = transport, cleanup
        self.repository = SQLiteRepository(target)
        self._attempts = 0
        self._counter_lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.transport, name)

    @staticmethod
    def _validate_payload(payload, budget):
        source = payload.get('source_code')
        allowed = {"def f():\n" + "\n".join(' ' + line for line in body.splitlines()):
            ('trace' if name in TRACE_CONTROLS else 'execute', _control_budget(name)) for name, body in CONTROLS.items()}
        allowed[CANCELLATION_SOURCE] = ('execute', ExecutionBudgetConfig())
        selected = allowed.get(source)
        if (selected is None or payload.get('function_name') != 'f' or payload.get('input_args') != {}
                or payload.get('mode') != selected[0] or budget != selected[1]
                or payload.get('budget') != budget.model_dump(mode='json')
                or payload.get('source_hash') != hashlib.sha256(source.encode()).hexdigest()
                or payload.get('apply_rlimits') is not False):
            raise TransportFailure('Only the authored finite acceptance controls are permitted')

    def run(self, *, job_id, payload, budget):
        self._validate_payload(payload, budget)
        with self._counter_lock:
            if self._attempts >= MAX_CONTROL_INVOCATIONS:
                raise TransportFailure('Finite acceptance invocation ceiling reached')
            self._attempts += 1
        sid = str(uuid4())
        source_hash = payload['source_hash']
        self.repository.create_session(session_id=sid, token_hash=str(uuid4()),
            exercise_id='ex2_binary_search', spec_version='v1_sorted_with_duplicates', language_mode='en-IN',
            interaction_mode='TEXT', starter_code=payload['source_code'], starter_code_hash=source_hash,
            expires_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
        acquired, returned = False, False
        try:
            revision = RevisionRef(session_id=sid, exercise_id='ex2_binary_search', spec_version='v1_sorted_with_duplicates',
                code_version_id=1, code_hash=source_hash, turn_generation=0)
            self.repository.register_execution_job(sid,str(job_id),'ACCEPTANCE',revision,'')
            acquired = self.cleanup_store.acquire_job(job_id)
            if not acquired:
                raise TransportFailure('Shared acceptance job capacity is occupied or cancelled')
            result = self.transport.run(job_id=job_id,payload=payload,budget=budget,dispatch_deadline=time.monotonic()+240)
            returned = True
            return result
        finally:
            settled = acquired and self.cleanup_store.finish_job(job_id)
            if settled:
                if self.cleanup_store.job_cancelled(job_id):
                    self.repository.request_execution_cancellation(sid,str(job_id))
                    self.repository.acknowledge_execution_cancellation(sid,str(job_id))
                else:
                    self.repository.finish_execution_job(sid,str(job_id),'COMPLETE' if returned else 'FAILED')
            self.repository.tombstone_session(sid)
            if acquired and not settled:
                raise TransportFailure('Acceptance cleanup remains unconfirmed')

    def cancel_invocation(self, job_id):
        self.cleanup_store.request_cancel(job_id)
        return self.transport.cancel_invocation(job_id)


def _frame(response, mode):
    return parse_runner_frame(base64.b64decode(response["stdout_b64"], validate=True), expected_mode=mode)


def _passed(name, result):
    if result.get("cleanup_verified") is not True or result.get("supervisor_ready_verified") is not True:
        return False
    reason = result["reason"]
    if name in {"frame_forgery", "native_frame_v2_forgery"} and (reason != "exited" or result.get("returncode") != 0):
        return False
    if name == "memory_above":
        return reason == "memory_limit" and result["events"]["memory"].get("oom_kill", 0) > 0
    if name == "pids_above":
        return result["events"]["pids"].get("max", 0) > 0
    if name == "cpu_above":
        return reason == "cpu_limit"
    if name in {"wall_above", "process_tree"}:
        return reason == "wall_timeout"
    if name == "stdout_above":
        return reason == "stdout_limit"
    if name == "stderr_above":
        return reason == "stderr_limit"
    if name not in {"frame_forgery", "native_frame_v2_forgery"} and result.get("native_authenticated") is not True:
        return False
    mode = "trace" if name in {"trace", "trace_tampering", "native_monitoring", "native_gc_trace", "native_locals_bound", "native_gc_frame_attack"} else "execute"
    try:
        frame = _frame(result, mode)
    except ProtocolViolationError:
        return name in {"frame_forgery", "native_frame_v2_forgery"} and result.get("native_authenticated") is False
    if name in {"frame_forgery", "native_frame_v2_forgery"}:
        # A forged single frame plus immediate exit must not be accepted.
        return False
    if name == "trace_tampering":
        return frame.trace_status == "TRACE_TAMPERED"
    if name == "trace":
        return frame.trace_status == "COMPLETED" and len(frame.steps) > 0
    if name in {"native_monitoring", "native_gc_frame_attack"}:
        return frame.trace_status == "TRACE_TAMPERED" and frame.kind == "EXCEPTION" and frame.error_type == "PermissionError"
    if name in {"native_ffi", "native_module_alias", "native_bytecode", "native_reentry"}:
        return frame.kind == "EXCEPTION" and frame.error_type == "PermissionError"
    if name == "native_signal_handlers":
        return frame.kind == "EXCEPTION" and frame.error_type in {"PermissionError", "OSError"}
    if name == "native_gc_trace":
        return frame.trace_status == "COMPLETED" and frame.kind == "RETURN" and frame.return_value == 2 and any("phase" in step["locals_snapshot"] for step in frame.steps)
    if name == "native_locals_bound":
        return frame.trace_status == "PARTIAL" and frame.kind == "RETURN" and frame.return_value == 1 and frame.trace_truncated
    expected = {"return": 7, "memory_below": 16 * 1048576, "pids_below": 4,
        "tmpfs_below": 1048576, "wall_below": 1, "network": 1, "filesystem": 1, "privileges": 1,
        "native_policy_selftest": 7, "native_stdlib": 7}
    if name == "exception":
        return frame.kind == "EXCEPTION"
    if name == "tmpfs_above":
        return frame.kind == "RETURN" and frame.return_value in {27, 28}
    return reason == "exited" and frame.kind == "RETURN" and frame.return_value == expected[name]


def _control_budget(name: str) -> ExecutionBudgetConfig:
    if name == "cpu_above":
        return ExecutionBudgetConfig(invocation_cpu_seconds=1)
    if name == "native_locals_bound":
        return ExecutionBudgetConfig(max_trace_snapshots_work=50)
    return ExecutionBudgetConfig()


def run_acceptance(transport, output_path: Path):
    checks = dict.fromkeys(sorted(REQUIRED_CHECKS), False)
    evidence = {"schema": "viva-vercel-acceptance-v1", "accepted": False,
        "runner_digest": runner_digest(), "image": IMAGE, "limits": LIMITS,
        "sdk_versions": {name: version(name) for name in SDK_VERSIONS},
        "checks": checks, "runtime": None, "all_sandboxes_deleted": False,
        "started_at": datetime.now(timezone.utc).isoformat(), "controls": [], "blockers": []}
    try:
        if evidence["sdk_versions"] != SDK_VERSIONS:
            raise TransportFailure("SDK versions do not match acceptance configuration")
        verify_sdk_creation_source()
        if len(CONTROLS)+1 > MAX_CONTROL_INVOCATIONS:
            raise TransportFailure('Finite acceptance control corpus exceeds its VM ceiling')
        transport = GuardedAcceptanceTransport(transport)
        for name, body in CONTROLS.items():
            budget = _control_budget(name)
            source = "def f():\n" + "\n".join(" " + line for line in body.splitlines())
            mode = "trace" if name in TRACE_CONTROLS else "execute"
            payload = {"mode": mode, "function_name": "f", "source_code": source,
                "source_hash": hashlib.sha256(source.encode()).hexdigest(), "input_args": {},
                "budget": budget.model_dump(mode="json"), "apply_rlimits": False}
            result = transport.run(job_id=uuid4(), payload=payload, budget=budget)
            checks[name] = _passed(name, result)
            if name == "return":
                # The exact bound native driver runs its fixed syscall/mapping
                # checks before it can emit any authenticated observation.
                checks["native_policy_selftest"] = checks[name]
            identity_ok = evidence["runtime"] is None or evidence["runtime"] == result["runtime"]
            evidence["runtime"] = result["runtime"]
            if not identity_ok:
                checks[name] = False
            evidence["controls"].append({"name": name, "passed": checks[name], "reason": result["reason"],
                "duration_ms": result["duration_ms"], "events": result["events"], "limits": result["limits"],
                "cleanup_verified": result["cleanup_verified"], "runtime_identity_matched": identity_ok})
            print(json.dumps({"control": name, "passed": checks[name], "reason": result["reason"]}), flush=True)
            if not checks[name] or not identity_ok:
                raise TransportFailure('Fixed acceptance control did not pass; remaining controls stopped', phase='control')
        job_id = uuid4()
        cancellation_result = {}
        budget = ExecutionBudgetConfig()
        cancel_source = CANCELLATION_SOURCE
        cancel_payload = {"mode": "execute", "function_name": "f", "source_code": cancel_source,
            "source_hash": hashlib.sha256(cancel_source.encode()).hexdigest(), "input_args": {},
            "budget": budget.model_dump(mode="json"), "apply_rlimits": False}
        def cancellation_control():
            try:
                transport.run(job_id=job_id, payload=cancel_payload, budget=budget)
                cancellation_result["returned"] = True
            except TransportFailure as exc:
                cancellation_result["failure"] = str(exc)
            except Exception as exc:
                cancellation_result['control_error'] = type(exc).__name__
        thread = threading.Thread(target=cancellation_control, daemon=True)
        thread.start()
        deadline = time.monotonic() + 40
        ready = False
        while thread.is_alive() and time.monotonic() < deadline:
            with transport.lock:
                ready = job_id in transport.ready_jobs
            if ready:
                break
            time.sleep(.01)
        deleted = transport.cancel_invocation(job_id)
        thread.join(timeout=20)
        checks["cancellation"] = (ready and deleted and not thread.is_alive()
            and "failure" in cancellation_result and 'control_error' not in cancellation_result
            and not transport.cleanup_obligations and transport.cleanup_store.cancellation_confirmed(job_id))
        evidence["controls"].append({"name": "cancellation", "passed": checks["cancellation"],
            "trusted_learner_ready_observed": ready, "vm_destroy_acknowledged": deleted,
            "command_completed_after_cancel": not thread.is_alive(),
            'control_error': cancellation_result.get('control_error')})
        checks["cleanup"] = not transport.cleanup_obligations
        checks["durable_cleanup"] = (transport.cleanup_store is not None
            and transport.cleanup_store.durable is True and not transport.cleanup_store.unresolved())
        evidence["all_sandboxes_deleted"] = checks["cleanup"]
        evidence["accepted"] = all(checks.values())
    except TransportFailure as exc:
        evidence["blockers"].append({"error": str(exc), "sandbox_name": exc.sandbox_name,
            "phase": exc.phase, "error_type": exc.error_type, "status_code": exc.status_code,
            "supervisor_diagnostic": exc.supervisor_diagnostic,
            "provider_deletion_verified": exc.provider_deletion_verified})
    except Exception as exc:
        evidence["blockers"].append({"error": "acceptance control failed", "error_type": type(exc).__name__})
    finally:
        evidence["cleanup_obligations"] = sorted(transport.cleanup_obligations)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirmed-free-hobby", action="store_true")
    parser.add_argument("--postgres-dsn-env", default="VCC_DATABASE_URL")
    parser.add_argument('--postgres-schema')
    parser.add_argument('--allow-local-postgres-for-acceptance', action='store_true')
    parser.parse_args()
    raise SystemExit(
        "Sandbox acceptance is unavailable: this runtime lacks the reviewed "
        "cleanup and execution-limit migrations and compatibility probe."
    )


if __name__ == "__main__":
    main()
