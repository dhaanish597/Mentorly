"""Bind acceptance to this runner, immutable provider image, runtime and limits."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

IMAGE = "vercel/sandbox/universal@sha256:9b2669397f26336812ec6835c2f67db6a546074cbabb05db93bf5e669f71ec5d"
SDK_VERSIONS = {"vercel-sandbox": "1.0.0", "vercel-internal-core": "0.3.0",
    "httpx2": "2.16.0", "httpcore2": "2.16.0", "vercel-oidc": "0.12.0", "vercel-headers": "0.8.0"}
SDK_CREATION_SOURCE_SHA256 = {
    'vercel.sandbox._internal.api_client': '34aea61c24c7db01bb9946a4f5de7bc28c32be0aaad6d6646b044ef19071aedd',
    'vercel.sandbox._internal.service': 'f2cb7b7dcd8de32f5e28da987c612020e16cba7ec28c5de9dbc65db6c10ae7ef',
    'vercel.sandbox._internal.sync_runtime': '3806cd3aed5fa45378e6ceaaf97e625a76d456c88388b7889245eabb2dd78e17',
    'vercel.sandbox._internal.retry': '1b34d8e7a0c2ad6d09a7f6004921c68346a3347381acc1dcce284aa562469c13',
    'vercel.sandbox.sync.client': '61cca11daa791805d3a96e0c8a1df873d3eddcd1da4df108a090f6bffadefb0d',
}


def verify_sdk_creation_source():
    for module_name, expected in SDK_CREATION_SOURCE_SHA256.items():
        module = importlib.import_module(module_name)
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != expected:
            raise ValueError('Unaccepted Sandbox SDK creation source')

LIMITS = {"memory_limit_mb": 256, "pids_limit": 16, "tmpfs_size_mb": 8,
          "invocation_cpu_seconds": 2, "invocation_wall_ms": 2000,
          "startup_deadline_ms": 5000, "max_stdout_bytes": 65536,
          "max_stderr_bytes": 65536, "max_result_bytes": 65536,
          "max_trace_bytes": 262144, "max_trace_steps": 250, "max_trace_snapshots_work": 2000}
REQUIRED_CHECKS = frozenset({"return", "exception", "trace", "memory_below", "memory_above",
    "pids_below", "pids_above", "tmpfs_below", "tmpfs_above", "wall_below", "wall_above",
    "cpu_above", "stdout_above", "stderr_above", "network", "filesystem", "privileges",
    "process_tree", "cancellation", "frame_forgery", "trace_tampering", "cleanup", "durable_cleanup",
    "native_policy_selftest", "native_frame_v2_forgery", "native_ffi", "native_module_alias", "native_bytecode",
    "native_reentry", "native_monitoring", "native_gc_trace", "native_signal_handlers", "native_stdlib", "native_locals_bound", "native_gc_frame_attack"})
NATIVE_FOLDER = Path(__file__).with_name("native")


def guest_files() -> dict[str, Path]:
    package = Path(__file__).resolve().parents[1]
    files = {"supervisor.py": Path(__file__).with_name("supervisor.py")}
    files["native_protocol.py"] = Path(__file__).with_name("native_protocol.py")
    files["assets/native/_viva_native.so"] = verified_native_binary()
    files["assets/exec_worker/__init__.py"] = package / "__init__.py"
    files.update({"assets/exec_worker/runner/" + path.name: path for path in sorted((package / "runner").glob("*.py"))})
    return files


def verified_native_binary() -> Path:
    folder = NATIVE_FOLDER
    binary, metadata = folder / "_viva_native.so", folder / "build-provenance.json"
    raw, manifest_raw = binary.read_bytes(), metadata.read_bytes()
    if not 0 < len(raw) <= 131072 or not raw.startswith(b"\x7fELF") or len(manifest_raw) > 65536:
        raise ValueError("Native build assets exceed bounds")
    manifest = json.loads(manifest_raw)
    if (manifest.get("schema") != "viva-native-build-v1" or manifest.get("python") != "3.14.4"
            or manifest.get("soabi") != "cpython-314-x86_64-linux-gnu"
            or manifest.get("architecture") != "x86_64" or manifest.get("gil_enabled") is not True
            or manifest.get("debug") is not False or manifest.get("binary_bytes") != len(raw)
            or manifest.get("binary_sha256") != hashlib.sha256(raw).hexdigest()
            or manifest.get("source_sha256") != hashlib.sha256((folder / "guard.c").read_bytes()).hexdigest()
            or manifest.get("build_script_sha256") != hashlib.sha256((folder / "build.py").read_bytes()).hexdigest()):
        raise ValueError("Native build identity mismatch")
    return binary


def runner_digest() -> str:
    digest = hashlib.sha256()
    for name, path in sorted(guest_files().items()):
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    # Trusted adapter/gate changes also invalidate acceptance.
    for name in ("adapter.py", "acceptance.py", "live_acceptance.py", "cleanup_store.py", "cleanup_store.sql", "integration.py", "native_protocol.py", "native/guard.c", "native/build.py", "native/build-provenance.json"):
        path = NATIVE_FOLDER / name[7:] if name.startswith("native/") else Path(__file__).parent / name
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    root = Path(__file__).resolve().parents[2]
    for name in ("exec_worker/worker_app/sandbox_runner.py", "exec_worker/worker_app/main.py",
                 "exec_worker/worker_app/verifier_harness.py", "backend/app/orchestration/worker_client.py",
                 'backend/app/core/worker_factory.py', 'backend/app/core/config.py',
                 'backend/app/core/execution_readiness.py', 'backend/app/main.py',
                 'backend/app/api/routes_sessions.py', 'backend/app/operations/readiness.py',
                 'backend/app/db/postgres/runtime.py', 'backend/app/db/repository.py'):
        digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
    for path in sorted((root / 'backend/app/db/postgres/runtime_migrations').glob('*.sql')):
        name = str(path.relative_to(root))
        digest.update(name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def load_acceptance(path: str | Path, expected_sha256: str) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > 65536 or len(expected_sha256) != 64 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("acceptance artifact binding mismatch")
    evidence = json.loads(raw)
    if (evidence.get("schema") != "viva-vercel-acceptance-v1"
            or evidence.get("accepted") is not True
            or evidence.get("runner_digest") != runner_digest()
            or evidence.get("image") != IMAGE or evidence.get("limits") != LIMITS
            or evidence.get("sdk_versions") != SDK_VERSIONS
            or not REQUIRED_CHECKS <= set(evidence.get("checks", {}))
            or any(evidence["checks"][name] is not True for name in REQUIRED_CHECKS)
            or evidence.get("all_sandboxes_deleted") is not True
            or not isinstance(evidence.get("runtime"), dict)):
        raise ValueError("execution acceptance is incomplete or stale")
    return evidence
