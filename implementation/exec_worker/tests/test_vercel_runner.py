"""Offline transport/gate tests. These never execute learner code locally."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.models.domain import ExecutionBudgetConfig
from exec_worker.vercel_sandbox import acceptance
from exec_worker.vercel_sandbox.adapter import (
    TransportFailure, VercelSandboxRunner, VercelSandboxTransport, _BoundedSink, _decode,
    CREATION_IMAGE,
)


@pytest.fixture(autouse=True)
def offline_native_assets(tmp_path, monkeypatch):
    """Transport doubles stage inert bytes; no native binary runs in these tests."""
    folder = tmp_path / "native"
    folder.mkdir()
    binary = b"\x7fELF_INERT_TRANSPORT_TEST_ONLY"
    (folder / "_viva_native.so").write_bytes(binary)
    for name in ("guard.c", "build.py"):
        (folder / name).write_bytes((acceptance.NATIVE_FOLDER / name).read_bytes())
    manifest = {"schema": "viva-native-build-v1", "python": "3.14.4", "soabi": "cpython-314-x86_64-linux-gnu",
        "architecture": "x86_64", "gil_enabled": True, "debug": False,
        "binary_bytes": len(binary), "binary_sha256": hashlib.sha256(binary).hexdigest(),
        "source_sha256": hashlib.sha256((folder / "guard.c").read_bytes()).hexdigest(),
        "build_script_sha256": hashlib.sha256((folder / "build.py").read_bytes()).hexdigest()}
    (folder / "build-provenance.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(acceptance, "NATIVE_FOLDER", folder)


def response(**updates):
    return {"schema": "viva-supervisor-v1", "reason": "exited", "cleanup_verified": True,
            "returncode": 0, "duration_ms": 3, "runtime": {"kernel": "test"},
            "stdout_b64": "", "stderr_b64": "", **updates}


class FakeBox:
    image = acceptance.IMAGE
    persistent = False
    network_policy = SimpleNamespace(mode="deny-all")
    def __init__(self, output=None, error=None, delete_error=None):
        self.files = {}
        self.fs = self
        self.output = output or response()
        self.error = error
        self.delete_error = delete_error
        self.deleted = 0
    def __enter__(self):
        return self
    def mkdir(self, path):
        pass
    def write_bytes(self, path, content):
        self.files[path] = content
    def run_command(self, command, args, **options):
        self.command = command, args, options
        if self.error:
            raise self.error
        options["stdout"].write(b"VIVA_SUPERVISOR_READY_V1\n" + json.dumps(self.output).encode())
        return SimpleNamespace(returncode=0)
    def destroy(self, **options):
        self.deleted += 1
        if self.delete_error:
            raise self.delete_error


class FakeClient:
    def __init__(self, box=None, create_error=None):
        self.box = box or FakeBox()
        self.create_error = create_error
        self.closed = False
    def create_sandbox(self, **options):
        self.options = options
        if self.create_error:
            raise self.create_error
        return self.box
    def get_sandbox(self, name):
        self.lookup_name = name
        return self.box
    def close(self):
        self.closed = True


class FakeStore:
    durable = True
    enforces_execution_limits = True
    requires_repository_job = True
    def __init__(self):
        self.pending = {}
        self.acknowledged = set()
        self.required = set()
        self.expired = set()
    def register(self, name, job_id):
        self.pending[name] = job_id
    def complete(self, name):
        self.pending.pop(name, None)
        self.required.discard(name)
        self.expired.discard(name)
    def acknowledge(self, name):
        self.acknowledged.add(name)
    def require_cleanup(self, name):
        self.required.add(name)
    def unresolved(self):
        return list(self.pending)
    def blocking(self):
        return list((self.required | self.expired) & self.pending.keys())
    def claim_expired(self):
        names = self.expired & self.pending.keys()
        self.expired.clear()
        self.required.update(names)
        return [(name, name in self.acknowledged) for name in names]
    def quota_available(self):
        return True
    def job_cancelled(self, job_id):
        return False


def run(transport, **extra):
    budget = ExecutionBudgetConfig()
    return transport.run(job_id=extra.pop("job_id", uuid4()), payload={"mode": "execute"}, budget=budget, **extra)


def test_fresh_deny_all_and_guest_allowlist():
    clients = []
    def factory():
        client = FakeClient()
        clients.append(client)
        return client
    transport = VercelSandboxTransport(factory)
    run(transport)
    run(transport)
    assert clients[0].options["name"] != clients[1].options["name"]
    for client in clients:
        assert client.options["image"] == CREATION_IMAGE
        assert client.options["persistent"] is False
        assert client.options["env"] == {} and client.options["ports"] == [] and client.options["mounts"] == {}
        assert client.options["network_policy"].mode == "deny-all"
        assert client.options["execution_time_limit"] == 20
        assert set(client.box.files) == {"/vercel/sandbox/viva/" + name for name in acceptance.guest_files()}
        assert client.box.deleted == 1 and client.closed
        command, args, options = client.box.command
        assert command == "python3" and args[-1].endswith("supervisor.py")
        assert options["sudo"] and options["kill_after"] == 12
        assert "env" not in options


def test_staging_and_supervision_failure_delete_vm():
    client = FakeClient(FakeBox(error=RuntimeError("secret request metadata")))
    with pytest.raises(TransportFailure) as error:
        run(VercelSandboxTransport(lambda: client))
    assert "secret" not in str(error.value)
    assert error.value.phase == "supervision"
    assert client.box.deleted == 1 and client.closed


def test_ambiguous_creation_uses_chosen_name_for_cleanup():
    client = FakeClient(create_error=RuntimeError("request metadata"))
    with pytest.raises(TransportFailure):
        run(VercelSandboxTransport(lambda: client))
    assert client.lookup_name == client.options["name"]
    assert client.box.deleted == 1


def test_failed_deletion_keeps_obligation_and_fails_result():
    client = FakeClient(FakeBox(delete_error=RuntimeError("request metadata")))
    transport = VercelSandboxTransport(lambda: client)
    with pytest.raises(TransportFailure) as error:
        run(transport)
    assert error.value.sandbox_name == client.options["name"]
    assert error.value.sandbox_name in transport.cleanup_obligations
    assert client.closed


@pytest.mark.parametrize("attribute,value", [("persistent", True), ("image", "mutable:latest"),
    ("network_policy", SimpleNamespace(mode="allow-all"))])
def test_policy_mismatch_never_stages_or_runs(attribute, value):
    box = FakeBox()
    setattr(box, attribute, value)
    client = FakeClient(box)
    with pytest.raises(TransportFailure):
        run(VercelSandboxTransport(lambda: client))
    assert not box.files and box.deleted == 1


def test_cancel_before_launch_creates_nothing():
    job = uuid4()
    transport = VercelSandboxTransport(lambda: pytest.fail("created cancelled VM"))
    assert not transport.cancel_invocation(job)
    with pytest.raises(TransportFailure, match="cancelled before"):
        run(transport, job_id=job)


def test_cancel_active_vm_destroys_whole_vm():
    box = FakeBox()
    job = uuid4()
    transport = VercelSandboxTransport()
    transport.active[job] = {"test": box}
    assert transport.cancel_invocation(job)
    assert box.deleted == 1 and transport.is_cancelled(job)


def test_outer_pipe_is_bounded():
    sink = _BoundedSink(10)
    sink.write(b"0123456789")
    with pytest.raises(TransportFailure):
        sink.write(b"x")
    assert len(sink.data) == 10


@pytest.mark.parametrize("reason", ["cpu_limit", "memory_limit", "stderr_limit"])
def test_resource_reasons_map_to_resource_exit(reason):
    outcome = _decode(response(reason=reason), ExecutionBudgetConfig())
    assert outcome.returncode == 137


@pytest.mark.parametrize("reason", ["wall_timeout", "startup_timeout"])
def test_deadline_reasons_remain_distinct(reason):
    outcome = _decode(response(reason=reason), ExecutionBudgetConfig())
    assert outcome.timed_out
    assert outcome.startup_timed_out == (reason == "startup_timeout")


def test_decode_rejects_forged_outer_format():
    with pytest.raises(TransportFailure):
        _decode(response(stdout_b64="not-base64!"), ExecutionBudgetConfig())


def test_missing_acceptance_stays_unavailable(monkeypatch):
    monkeypatch.setenv("VCC_PUBLIC_EXECUTION_ENABLED", "true")
    runner = VercelSandboxRunner(acceptance_path="/does/not/exist")
    preflight = runner.check_preflight()
    assert not preflight.ready and not preflight.acceptance_verified


def test_transport_failure_maps_to_unavailable():
    runner = VercelSandboxRunner()
    outcome = SimpleNamespace(returncode=None, stdout_text="", stderr_text="Sandbox unavailable or cancelled", duration_ms=7)
    observation = runner._map_execution_outcome(outcome, ExecutionBudgetConfig())
    assert observation.kind == "UNAVAILABLE"


def test_acceptance_requires_all_real_checks_and_exact_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "runner_digest", lambda: "a" * 64)
    evidence = {"schema": "viva-vercel-acceptance-v1", "accepted": True,
        "runner_digest": "a" * 64, "image": acceptance.IMAGE, "limits": acceptance.LIMITS,
        "sdk_versions": acceptance.SDK_VERSIONS,
        "checks": dict.fromkeys(acceptance.REQUIRED_CHECKS, True),
        "all_sandboxes_deleted": True, "runtime": {"kernel": "test"}}
    path = tmp_path / "evidence.json"
    def save():
        raw = json.dumps(evidence).encode()
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    assert acceptance.load_acceptance(path, save()) == evidence
    evidence["checks"]["memory_above"] = False
    with pytest.raises(ValueError):
        acceptance.load_acceptance(path, save())


def test_higher_than_accepted_budget_rejected_before_creation():
    transport = VercelSandboxTransport(lambda: pytest.fail("created over-budget VM"))
    with pytest.raises(ValueError):
        transport.run(job_id=uuid4(), payload={}, budget=ExecutionBudgetConfig(memory_limit_mb=512))


def test_ldd_headers_are_not_dependencies(tmp_path, monkeypatch):
    from exec_worker.vercel_sandbox import supervisor
    executable = tmp_path / "python"
    stdlib = tmp_path / "stdlib"
    dynamic = stdlib / "lib-dynload"
    dynamic.mkdir(parents=True)
    module = dynamic / "_socket.so"
    libc = tmp_path / "libc.so.6"
    loader = tmp_path / "ld-linux-x86-64.so.2"
    for path in (executable, module, libc, loader):
        path.touch()
    text = (f"{executable}:\n\tlibc.so.6 => {libc} (0x1234)\n\t{loader} (0x1234)\n"
            f"{module}:\n\tlibc.so.6 => {libc} (0x9876)\n")
    monkeypatch.setattr(supervisor.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=text.encode(), stderr=b"", returncode=0))
    assert supervisor._dependencies(executable, stdlib) == sorted([libc, loader])


def test_bind_does_not_touch_existing_readonly_destination(tmp_path, monkeypatch):
    from exec_worker.vercel_sandbox import supervisor
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.touch()
    destination.touch()
    monkeypatch.setattr(Path, "touch", lambda *args, **kwargs: pytest.fail("touched existing mount target"))
    mounts = []
    monkeypatch.setattr(supervisor, "_mount", lambda *args, **kwargs: mounts.append((args, kwargs)))
    supervisor._bind(source, destination)
    assert len(mounts) == 2


def test_invalid_utf8_frame_is_rejected_without_replacement():
    from exec_worker.vercel_sandbox.adapter import InvalidRunnerOutput
    raw = b'<<VCC_RUNNER_FRAME_V1_BEGIN>>\n{"protocol_version":"1.0","mode":"execute","kind":"RETURN","return_value":"\xff"}\n<<VCC_RUNNER_FRAME_V1_END>>'
    with pytest.raises(InvalidRunnerOutput):
        _decode(response(stdout_b64=base64.b64encode(raw).decode()), ExecutionBudgetConfig())


def test_delete_and_client_close_failure_still_retain_obligation():
    client = FakeClient(FakeBox(delete_error=RuntimeError("delete failed")))
    def close_failure():
        raise RuntimeError("client close failed")
    client.close = close_failure
    store = FakeStore()
    transport = VercelSandboxTransport(lambda: client, cleanup_store=store)
    with pytest.raises(TransportFailure, match="client cleanup failed"):
        run(transport)
    name = client.options["name"]
    assert name in transport.cleanup_obligations and name in store.pending
    assert not transport.inflight_names


def test_durable_registration_precedes_sdk_and_restart_can_recover():
    store = FakeStore()
    client = FakeClient(FakeBox(delete_error=RuntimeError("delete failed")))
    def factory():
        assert len(store.pending) == 1
        return client
    with pytest.raises(TransportFailure):
        run(VercelSandboxTransport(factory, cleanup_store=store))
    store.expired.update(store.pending)
    recovery = FakeClient()
    restarted = VercelSandboxTransport(lambda: recovery, cleanup_store=store)
    restarted.recover_cleanup()
    assert not store.pending and recovery.box.deleted == 1 and recovery.closed


def test_client_setup_failure_clears_uncreated_registration():
    store = FakeStore()
    def factory():
        raise RuntimeError("client unavailable")
    transport = VercelSandboxTransport(factory, cleanup_store=store)
    with pytest.raises(TransportFailure):
        run(transport)
    assert not store.pending and not transport.inflight_names and not transport.cleanup_obligations


def test_public_preflight_requires_durable_cleanup_store(monkeypatch):
    monkeypatch.setenv("VCC_PUBLIC_EXECUTION_ENABLED", "true")
    monkeypatch.setattr("exec_worker.vercel_sandbox.adapter.load_acceptance", lambda *args: {"runtime": {"kernel": "test"}})
    assert not VercelSandboxRunner().check_preflight().ready
    transport = VercelSandboxTransport(cleanup_store=FakeStore())
    assert VercelSandboxRunner(transport=transport).check_preflight().ready
    name = "viva-inv-" + "a" * 24
    transport.cleanup_store.register(name, uuid4())
    assert VercelSandboxRunner(transport=transport).check_preflight().ready
    transport.cleanup_store.require_cleanup(name)
    assert not VercelSandboxRunner(transport=transport).check_preflight().ready


def test_inherited_runner_change_invalidates_acceptance_digest(monkeypatch):
    root = Path(acceptance.__file__).resolve().parents[2]
    if not (root / 'backend/app/core/worker_factory.py').exists():
        with pytest.raises(FileNotFoundError):
            acceptance.runner_digest()
        return
    before = acceptance.runner_digest()
    read_bytes = Path.read_bytes
    def changed(path):
        data = read_bytes(path)
        return data + b"\n# changed trusted mapping" if path.name == "sandbox_runner.py" else data
    monkeypatch.setattr(Path, "read_bytes", changed)
    assert acceptance.runner_digest() != before


@pytest.mark.parametrize("mutation", ["missing", "changed_binary", "changed_source"])
def test_missing_or_stale_native_assets_prevent_any_vm_creation(mutation):
    binary = acceptance.NATIVE_FOLDER / "_viva_native.so"
    if mutation == "missing":
        binary.unlink()
    elif mutation == "changed_binary":
        binary.write_bytes(b"\x7fELF_CHANGED_INERT_TEST_BYTES")
    else:
        source = acceptance.NATIVE_FOLDER / "guard.c"
        source.write_bytes(source.read_bytes() + b"\n/* changed */\n")
    store = FakeStore()
    transport = VercelSandboxTransport(lambda: pytest.fail("Stale build created a VM"), cleanup_store=store)
    with pytest.raises(TransportFailure) as error:
        run(transport)
    assert error.value.phase == "native_preflight"
    assert not store.pending and not transport.inflight_names and not transport.cleanup_obligations


def test_recovery_does_not_claim_another_workers_live_registration():
    store = FakeStore()
    name = "viva-inv-" + "a" * 24
    store.register(name, uuid4())
    client = FakeClient()
    VercelSandboxTransport(lambda: client, cleanup_store=store).recover_cleanup()
    assert name in store.pending and not hasattr(client, "lookup_name")


def test_expired_unacknowledged_creation_keeps_obligation():
    store = FakeStore()
    name = "viva-inv-" + "a" * 24
    store.register(name, uuid4())
    store.expired.add(name)
    client = FakeClient()
    with pytest.raises(TransportFailure, match="inventory confirmation"):
        VercelSandboxTransport(lambda: client, cleanup_store=store).recover_cleanup()
    assert name in store.pending and name in store.required


def test_ambiguous_creation_never_clears_durable_name_on_immediate_absence():
    store = FakeStore()
    class Missing(RuntimeError):
        status_code = 404
    client = FakeClient(create_error=RuntimeError("request timed out"))
    def missing(name):
        raise Missing()
    client.get_sandbox = missing
    with pytest.raises(TransportFailure):
        run(VercelSandboxTransport(lambda: client, cleanup_store=store))
    assert len(store.pending) == 1 and store.required


@pytest.mark.parametrize("reason", ["setup_failure", "startup_timeout", "wall_timeout", "memory_limit", "cpu_limit", "stdout_limit", "stderr_limit"])
def test_forgery_acceptance_never_passes_unexecuted_or_resource_failed_controls(reason):
    from exec_worker.vercel_sandbox.live_acceptance import _passed
    assert not _passed("frame_forgery", response(reason=reason, supervisor_ready_verified=True))


def test_forgery_acceptance_requires_trusted_learner_startup():
    from exec_worker.vercel_sandbox.live_acceptance import _passed
    assert not _passed("frame_forgery", response(supervisor_ready_verified=False))


@pytest.mark.parametrize("guest_cleanup", [True, False])
def test_setup_diagnostics_reject_even_after_provider_deletion(guest_cleanup):
    diagnostic = {"phase": "cgroup_enable", "error_type": "OSError", "errno": 30}
    box = FakeBox(response(reason="setup_failure", cleanup_verified=guest_cleanup,
                           failure=diagnostic, cleanup_failures=[]))
    store = FakeStore()
    transport = VercelSandboxTransport(lambda: FakeClient(box), cleanup_store=store)
    with pytest.raises(TransportFailure) as caught:
        run(transport)
    failure = caught.value
    assert failure.phase == "cgroup_enable"
    assert failure.sandbox_name.startswith("viva-inv-")
    assert failure.supervisor_diagnostic == {"failure": diagnostic, "cleanup_failures": []}
    assert failure.provider_deletion_verified is True
    assert box.deleted == 1
    assert not transport.cleanup_obligations
    assert not store.pending


def test_supervisor_diagnostic_survives_failed_provider_deletion():
    diagnostic = {"phase": "cgroup_enable", "error_type": "OSError", "errno": 30}
    box = FakeBox(response(reason="setup_failure", cleanup_verified=False, failure=diagnostic),
                  delete_error=RuntimeError("private provider error"))
    transport = VercelSandboxTransport(lambda: FakeClient(box), cleanup_store=FakeStore())
    with pytest.raises(TransportFailure, match="sandbox deletion not verified") as caught:
        run(transport)
    assert caught.value.provider_deletion_verified is False
    assert caught.value.supervisor_diagnostic["failure"] == diagnostic
    assert transport.cleanup_obligations == {caught.value.sandbox_name}
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("diagnostic", [
    {"phase": "private-token", "error_type": "OSError", "errno": 30},
    {"phase": "cgroup_enable", "error_type": "private-token", "errno": 30},
    {"phase": "cgroup_enable", "error_type": "OSError", "errno": True},
    {"phase": "cgroup_enable", "error_type": "OSError", "errno": 4096},
    {"phase": "cgroup_enable", "error_type": "OSError", "errno": 30, "message": "private-token"},
])
def test_unbounded_or_unknown_supervisor_diagnostics_never_escape(diagnostic):
    box = FakeBox(response(reason="setup_failure", cleanup_verified=False, failure=diagnostic))
    transport = VercelSandboxTransport(lambda: FakeClient(box), cleanup_store=FakeStore())
    with pytest.raises(TransportFailure, match="invalid supervisor diagnostics") as caught:
        run(transport)
    assert caught.value.supervisor_diagnostic is None
    assert caught.value.provider_deletion_verified is True
    assert "private-token" not in str(caught.value)
