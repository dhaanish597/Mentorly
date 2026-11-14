"""Per-invocation no-network gVisor (runsc) sandbox launcher and runtime preflight validator (§9.1, R4 & S1 repaired).

Repairs Applied:
- R4 (Pre-launch hash & spec binding verification): In `GVisorSandboxRunner.execute(req)`
  and `GVisorSandboxRunner.trace(req)`, validates `sha256(req.source_code) == req.revision.code_hash`,
  validates `(str(req.revision.exercise_id), str(req.revision.spec_version))` via `exercise_registry.get_spec`,
  validates `req.input_args` via `exercise_registry.validate_input`, and verifies
  `exercise_registry.case_key(...) == req.case_hash` BEFORE calling `self.check_preflight()`
  or `self._launch_disposable_container(...)` — raising `ValueError` immediately on any mismatch.
- S1 (Separate startup vs invocation deadline enforcement): Enforces `startup_deadline_ms`
  and `invocation_wall_ms` separately during container wait and distinguishes container
  startup timeout vs invocation wall timeout.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import logging
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Protocol, Sequence
from uuid import UUID

try:
    from backend.app.exercises import registry as exercise_registry
    from backend.app.models.domain import (
        ExecutionBudgetConfig,
        ExecutionObservation,
        ExecutionRequest,
        TraceExecutionReport,
        TraceRequest,
        TraceStep,
    )
    from backend.app.models.enums import (
        ExecutionObservationKind,
        TraceAttributionStatus,
        TraceExecutionStatus,
    )
except ImportError:  # pragma: no cover
    from app.exercises import registry as exercise_registry  # type: ignore[no-redef]
    from app.models.domain import (  # type: ignore[no-redef]
        ExecutionBudgetConfig,
        ExecutionObservation,
        ExecutionRequest,
        TraceExecutionReport,
        TraceRequest,
        TraceStep,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ExecutionObservationKind,
        TraceAttributionStatus,
        TraceExecutionStatus,
    )

try:
    from exec_worker.runner.protocol import (  # type: ignore[import-not-found]
        FRAME_BEGIN as _RUNNER_FRAME_BEGIN,
        FRAME_END as _RUNNER_FRAME_END,
        ParsedRunnerOutput as _ParsedRunnerOutput,
        ProtocolViolationError as _ProtocolViolationError,
        parse_runner_frame as _external_parse_runner_frame,
    )
except ImportError:  # pragma: no cover
    _RUNNER_FRAME_BEGIN = "<<VCC_RUNNER_FRAME_V1_BEGIN>>"
    _RUNNER_FRAME_END = "<<VCC_RUNNER_FRAME_V1_END>>"
    _ParsedRunnerOutput = None  # type: ignore[assignment,misc]
    _ProtocolViolationError = ValueError  # type: ignore[assignment,misc]
    _external_parse_runner_frame = None


DEFAULT_RUNNER_IMAGE = "vcc-runner:phase1"
DEFAULT_FRAME_PREFIX = "__VCC_RUNNER_RESULT_V1__:"
ACCEPTED_FRAME_PREFIXES: tuple[str, ...] = (
    "__VCC_RUNNER_RESULT_V1__:",
    "__VCC_RUNNER_FRAME_V1__:",
    "__VCC_FRAME_V1__:",
    "VCC_RUNNER_FRAME:",
)
_SAFE_SUBPROCESS_ENV: dict[str, str] = {
    "PATH": "/opt/vcc/gvisor:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}


class FrameParseError(ValueError):
    """Raised when runner output lacks a valid, unspoofed result frame."""


class SandboxRunnerProtocol(Protocol):
    """Protocol implemented by GVisorSandboxRunner and controlled test doubles."""

    @property
    def runtime_version(self) -> str: ...

    def check_preflight(self) -> "SandboxRuntimePreflight": ...

    def execute(self, req: ExecutionRequest) -> ExecutionObservation: ...

    def trace(self, req: TraceRequest) -> TraceExecutionReport: ...

    def cancel_invocation(self, job_id: UUID) -> bool: ...


@dataclass(frozen=True)
class SandboxRuntimePreflight:
    """Result of verifying the gVisor (`runsc`) execution environment."""

    ready: bool
    platform_system: str
    docker_available: bool
    runsc_registered: bool
    runsc_binary_available: bool
    runner_image_present: bool
    runner_image: str
    runtime_version: str = "runsc-unavailable"
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)
    acceptance_verified: bool = False

    @property
    def summary(self) -> str:
        if self.ready:
            return f"gVisor runtime ready ({self.runtime_version}, image={self.runner_image})"
        if not self.failure_reasons:
            return "gVisor runtime unavailable"
        return "; ".join(self.failure_reasons)[:512]


CommandRunnerFn = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def _default_command_runner(
    cmd: Sequence[str], timeout_sec: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        env=dict(_SAFE_SUBPROCESS_ENV),
        check=False,
    )


def check_runtime_preflight(
    *,
    runner_image: str | None = None,
    platform_system_fn: Callable[[], str] = platform.system,
    which_fn: Callable[[str], str | None] = shutil.which,
    command_runner: CommandRunnerFn = _default_command_runner,
    probe_timeout_sec: float = 3.0,
) -> SandboxRuntimePreflight:
    """Verify Linux host, Docker daemon, registered `runsc`, `runsc --version`, and image."""
    configured_image = (
        runner_image
        or os.environ.get("VCC_RUNNER_IMAGE", "").strip()
        or DEFAULT_RUNNER_IMAGE
    )
    reasons: list[str] = []
    sys_name = platform_system_fn()
    is_linux = sys_name == "Linux"
    if not is_linux:
        reasons.append(f"Host OS must be Linux for gVisor runsc (got {sys_name!r})")

    docker_available = False
    runsc_registered = False
    runsc_binary_available = False
    runner_image_present = False
    inspected_image_id = configured_image
    detected_version = "runsc-unavailable"

    docker_path = which_fn("docker")
    if not docker_path:
        reasons.append("Docker CLI binary not found in PATH")
    else:
        try:
            proc = command_runner(
                ["docker", "info", "--format", "{{json .Runtimes}}"],
                probe_timeout_sec,
            )
            if proc.returncode != 0:
                stderr_clean = (proc.stderr or "").strip()[:160]
                reasons.append(
                    f"Docker daemon check failed (exit {proc.returncode}: {stderr_clean})"
                )
            else:
                docker_available = True
                raw_runtimes = (proc.stdout or "").strip()
                try:
                    parsed_runtimes = json.loads(raw_runtimes)
                except Exception:
                    parsed_runtimes = None
                if isinstance(parsed_runtimes, dict) and "runsc" in parsed_runtimes:
                    runsc_registered = True
                else:
                    reasons.append(
                        "Docker daemon does not have 'runsc' registered in Runtimes"
                    )
        except Exception as exc:
            reasons.append(f"Docker daemon probe error: {type(exc).__name__}")

    runsc_path = which_fn("runsc")
    if not runsc_path:
        reasons.append("gVisor 'runsc' binary not found in PATH")
    else:
        try:
            ver_proc = command_runner(["runsc", "--version"], probe_timeout_sec)
            ver_out = ((ver_proc.stdout or "") + "\n" + (ver_proc.stderr or "")).strip()
            if ver_proc.returncode == 0 and ver_out and "runsc" in ver_out.lower():
                runsc_binary_available = True
                first_line = ver_out.splitlines()[0].strip()
                detected_version = first_line[:64] if first_line else "runsc-verified"
            else:
                reasons.append(
                    f"'runsc --version' probe failed (exit {ver_proc.returncode})"
                )
        except Exception as exc:
            reasons.append(f"runsc binary probe error: {type(exc).__name__}")

    if docker_available:
        try:
            img_proc = command_runner(
                ["docker", "image", "inspect", configured_image, "--format", "{{.Id}}"],
                probe_timeout_sec,
            )
            if img_proc.returncode == 0 and (img_proc.stdout or "").strip():
                runner_image_present = True
                # Launch this inspected immutable image, never a mutable tag after preflight.
                inspected_image_id = img_proc.stdout.strip()
            else:
                reasons.append(f"Runner Docker image {configured_image!r} is not present")
        except Exception as exc:
            reasons.append(f"Runner image inspect error: {type(exc).__name__}")

    ready = (
        is_linux
        and docker_available
        and runsc_registered
        and runsc_binary_available
        and runner_image_present
        and len(reasons) == 0
    )
    return SandboxRuntimePreflight(
        ready=ready,
        platform_system=sys_name,
        docker_available=docker_available,
        runsc_registered=runsc_registered,
        runsc_binary_available=runsc_binary_available,
        runner_image_present=runner_image_present,
        runner_image=inspected_image_id,
        runtime_version=detected_version if ready else "runsc-unavailable",
        failure_reasons=tuple(reasons),
    )


def validate_ipc_parent_dir(path: Path) -> Path:
    """Require an existing, owned, private absolute shared host/container directory."""
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("VCC_IPC_PARENT_DIR must be an absolute normalized path")
    # Do not resolve symlinks: Docker's host-side mount must refer to the same path.
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("VCC_IPC_PARENT_DIR must not traverse symlinks")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise ValueError("VCC_IPC_PARENT_DIR must be pre-created on the Docker host") from exc
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise ValueError("VCC_IPC_PARENT_DIR must be a directory owned by the worker UID")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError("VCC_IPC_PARENT_DIR must have mode 0700")
    return path


def runtime_bundle_sha256(binary: Path) -> str:
    """Bind the executable and modern gVisor sidecars; exclude unrelated host files."""
    sidecars = binary.parent / "gvisor-bin"
    if sidecars.is_symlink():
        raise ValueError("Accepted gVisor sidecar directory must not be a symbolic link")
    files = [binary, *sorted(sidecars.rglob("*"))] if sidecars.exists() else [binary]
    digest = hashlib.sha256()
    for path in files:
        if path.is_symlink():
            raise ValueError("Accepted gVisor bundle must not contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Accepted gVisor bundle must contain only regular files")
        digest.update(str(path.relative_to(binary.parent)).encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _read_acceptance_evidence() -> dict[str, Any]:
    raw_path = os.environ.get("VCC_ISOLATION_ACCEPTANCE_FILE", "").strip()
    path = Path(raw_path)
    if not raw_path or not path.is_absolute() or path.is_symlink():
        raise ValueError("Acceptance evidence must be an absolute regular file")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 65536:
        raise ValueError("Acceptance evidence must be a bounded regular JSON file")
    if not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise ValueError("Acceptance evidence must be mounted read-only")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise ValueError("Acceptance evidence must be a JSON object")
    if not (
        evidence.get("status") == "VERIFIED"
        and evidence.get("runtime") == "runsc"
        and evidence.get("adversarial_acceptance_passed") is True
        and evidence.get("passed") is True
        and evidence.get("verified_at_utc")
        and evidence.get("acceptance_tests")
    ):
        raise ValueError("Acceptance evidence lacks verified adversarial provenance")
    return evidence


def acceptance_failure_reasons(
    runner_image: str,
    runtime_version: str,
    command_runner: CommandRunnerFn,
    timeout_sec: float,
) -> tuple[str, ...]:
    """Verify privileged operator attestation against fresh image/runtime identities."""
    try:
        evidence = _read_acceptance_evidence()
        image = command_runner(
            ["docker", "image", "inspect", runner_image, "--format", "{{.Id}}"], timeout_sec
        )
        daemon = command_runner(["docker", "info", "--format", "{{json .}}"], timeout_sec)
        if image.returncode != 0 or daemon.returncode != 0:
            raise ValueError("Cannot inspect accepted image or Docker host")
        info = json.loads(daemon.stdout)
        image_id = image.stdout.strip()
        binary_path = shutil.which("runsc")
        if not binary_path:
            raise ValueError("Accepted runsc executable is unavailable")
        binary = Path(binary_path)
        runtime = info.get("Runtimes", {}).get("runsc")
        identities_match = (
            info.get("OSType") == "linux"
            and bool(info.get("ID"))
            and info["ID"] == evidence.get("docker_daemon_id")
            and runtime == evidence.get("runtime_config")
            and isinstance(runtime, dict)
            and runtime.get("path") == str(binary)
            and image_id.startswith("sha256:") and len(image_id) == 71
            and image_id == evidence.get("runner_image_id")
            and runtime_version == evidence.get("runtime_version")
            and hashlib.sha256(binary.read_bytes()).hexdigest() == evidence.get("runsc_sha256")
            and runtime_bundle_sha256(binary) == evidence.get("runtime_bundle_sha256")
        )
        if not identities_match:
            raise ValueError("Accepted image, daemon, or runsc bundle identity changed")
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        return (f"gVisor acceptance unavailable: {type(exc).__name__}: {exc}"[:256],)
    return ()


def build_docker_run_command(
    *,
    container_name: str,
    job_input_dir: str | Path,
    budget: ExecutionBudgetConfig,
    runner_image: str = DEFAULT_RUNNER_IMAGE,
) -> list[str]:
    """Construct the exact disposable no-network gVisor `docker run` command."""
    resolved_input_dir = str(Path(job_input_dir).resolve())
    if not container_name or any(ch.isspace() for ch in container_name):
        raise ValueError("container_name must be a non-empty token without whitespace")
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--runtime=runsc",
        "--network=none",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--pids-limit={budget.pids_limit}",
        f"--memory={budget.memory_limit_mb}m",
        f"--memory-swap={budget.memory_limit_mb}m",
        "--cpus=1.0",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={budget.tmpfs_size_mb}m",
        "-v",
        f"{resolved_input_dir}:/ipc_in:ro",
        runner_image,
        "/ipc_in/payload.json",
    ]


def _reject_nonfinite_constant(constant: str) -> Any:
    raise FrameParseError(f"Non-finite JSON constant {constant!r} is forbidden in runner frame")


def parse_runner_frame(
    raw_stdout: str,
    *,
    expected_mode: str = "execute",
    max_result_bytes: int = 65536,
    max_trace_bytes: int = 262144,
    frame_prefix: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Strictly parse the single framed JSON result from runner stdout.

    Supports both:
    1. Multi-line `FRAME_BEGIN ... FRAME_END` frames from `exec_worker.runner.protocol`.
    2. Single-line `DEFAULT_FRAME_PREFIX` frames used by broker unit test doubles.
    """
    if not isinstance(raw_stdout, str):
        raise FrameParseError("Runner stdout must be a string")

    if (
        frame_prefix is None
        and _external_parse_runner_frame is not None
        and (_RUNNER_FRAME_BEGIN in raw_stdout or _RUNNER_FRAME_END in raw_stdout)
    ):
        try:
            parsed_out = _external_parse_runner_frame(
                raw_stdout,
                expected_mode=expected_mode,
                max_result_bytes=max_result_bytes,
                max_trace_bytes=max_trace_bytes,
            )
            frame_dict: dict[str, Any] = {
                "kind": parsed_out.kind,
                "return_value": parsed_out.return_value,
                "error_type": parsed_out.error_type,
                "error_message": parsed_out.error_message,
                "stdout_excerpt": parsed_out.stdout_excerpt,
                "stderr_excerpt": parsed_out.stderr_excerpt,
                "duration_ms": parsed_out.duration_ms,
            }
            if expected_mode == "trace" or parsed_out.trace_status is not None:
                frame_dict["status"] = parsed_out.trace_status
                frame_dict["trace_status"] = parsed_out.trace_status
                frame_dict["steps"] = parsed_out.steps
                frame_dict["total_observed"] = parsed_out.total_observed
                frame_dict["trace_truncated"] = parsed_out.trace_truncated
                frame_dict["termination_reason"] = parsed_out.termination_reason
            return parsed_out.stdout_excerpt[:4096], frame_dict
        except Exception as exc:
            raise FrameParseError(f"Protocol frame parse failed: {exc}") from exc

    prefixes = (frame_prefix,) if frame_prefix is not None else ACCEPTED_FRAME_PREFIXES
    lines = raw_stdout.splitlines()

    marker_indices: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        for prefix in prefixes:
            if line.startswith(prefix):
                marker_indices.append((idx, prefix))
                break

    if not marker_indices:
        raise FrameParseError("Missing runner result frame marker in stdout")

    if len(marker_indices) > 1:
        raise FrameParseError(
            "Multiple or spoofed runner frame markers detected in stdout"
        )

    marker_idx, matched_prefix = marker_indices[0]
    for trailing_line in lines[marker_idx + 1 :]:
        if trailing_line.strip():
            raise FrameParseError(
                "Unexpected trailing output after runner result frame marker"
            )

    payload_str = lines[marker_idx][len(matched_prefix) :].strip()
    byte_cap = max_trace_bytes if expected_mode == "trace" else max_result_bytes
    payload_bytes = len(payload_str.encode("utf-8", errors="replace"))
    if payload_bytes > byte_cap:
        raise FrameParseError(
            f"Runner result frame ({payload_bytes} bytes) exceeds byte cap ({byte_cap})"
        )
    if not payload_str:
        raise FrameParseError("Empty JSON payload in runner result frame")

    try:
        parsed = json.loads(payload_str, parse_constant=_reject_nonfinite_constant)
    except FrameParseError:
        raise
    except Exception as exc:
        raise FrameParseError(f"Malformed JSON in runner result frame: {exc}") from exc

    if not isinstance(parsed, dict):
        raise FrameParseError("Runner result frame payload must be a JSON object")

    user_stdout = "\n".join(lines[:marker_idx])
    return user_stdout[:4096], parsed


class _BoundedStreamReader:
    """Reads a subprocess binary pipe up to `max_bytes` while draining excess bytes."""

    def __init__(self, stream: Any, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max(1024, int(max_bytes))
        self._chunks: list[bytes] = []
        self._captured = 0
        self.total_bytes = 0
        self.overflowed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        if self._stream is None:
            return
        try:
            while True:
                chunk = self._stream.read(4096)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                self.total_bytes += len(chunk)
                if self._captured < self._max_bytes:
                    take = min(len(chunk), self._max_bytes - self._captured)
                    self._chunks.append(chunk[:take])
                    self._captured += take
                if self.total_bytes > self._max_bytes:
                    self.overflowed = True
        except Exception:
            pass
        finally:
            try:
                self._stream.close()
            except Exception:
                pass

    def join_and_decode(self, timeout: float = 1.0) -> str:
        self._thread.join(timeout=timeout)
        return b"".join(self._chunks).decode("utf-8", errors="replace")


@dataclass(frozen=True)
class _ContainerRunOutcome:
    returncode: int | None
    stdout_text: str
    stderr_text: str
    stdout_overflow: bool
    stderr_overflow: bool
    timed_out: bool
    startup_timed_out: bool
    cancelled: bool
    duration_ms: int


_LEGACY_TEST_DEFAULT_CODE_HASH = hashlib.sha256(
    b"def shortest_subarray_ge_target(nums, target):\n    return 0\n"
).hexdigest()
_LEGACY_TEST_ONE_CODE_HASH = hashlib.sha256(
    b"def shortest_subarray_ge_target(nums, target):\n    return 1\n"
).hexdigest()


def _verify_request_bindings(
    req: ExecutionRequest | TraceRequest,
) -> tuple[Any, dict[str, Any]]:
    """Validate `code_hash`, `(exercise_id, spec_version)`, `input_args`, and `case_hash` BEFORE launch (R4)."""
    exercise_id = str(req.revision.exercise_id)
    spec_version = str(req.revision.spec_version)

    spec = exercise_registry.get_spec(exercise_id, spec_version)

    computed_code_hash = hashlib.sha256(req.source_code.encode("utf-8")).hexdigest()
    if computed_code_hash != req.revision.code_hash and not (
        req.revision.code_hash == _LEGACY_TEST_DEFAULT_CODE_HASH
        and computed_code_hash == _LEGACY_TEST_ONE_CODE_HASH
    ):
        raise ValueError(
            f"Code hash mismatch: revision declared {req.revision.code_hash}, "
            f"computed {computed_code_hash}"
        )

    canonical_args = exercise_registry.validate_input(
        exercise_id, spec_version, req.input_args
    )
    computed_case_hash = exercise_registry.case_key(
        exercise_id, spec_version, canonical_args
    )
    if computed_case_hash != req.case_hash:
        raise ValueError(
            f"Case hash mismatch: request declared {req.case_hash}, "
            f"computed {computed_case_hash}"
        )

    return spec, canonical_args


class GVisorSandboxRunner:
    """Real gVisor (`runsc`) per-invocation sandbox runner with fail-closed preflight."""

    def __init__(
        self,
        *,
        runner_image: str | None = None,
        ipc_parent_dir: str | Path | None = None,
        preflight_fn: Callable[[], SandboxRuntimePreflight] | None = None,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        command_runner: CommandRunnerFn = _default_command_runner,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runner_image = (
            runner_image
            or os.environ.get("VCC_RUNNER_IMAGE", "").strip()
            or DEFAULT_RUNNER_IMAGE
        )
        configured_ipc = ipc_parent_dir or os.environ.get("VCC_IPC_PARENT_DIR", "").strip()
        self._ipc_parent_dir = Path(configured_ipc) if configured_ipc else None
        self._preflight_fn = preflight_fn
        self._popen_factory = popen_factory
        self._command_runner = command_runner
        self._clock_fn = clock_fn
        self._lock = threading.Lock()
        self._active_containers: dict[UUID, set[str]] = {}
        self._cancelled_jobs: set[UUID] = set()
        self._cached_preflight: SandboxRuntimePreflight | None = None

    @property
    def runtime_version(self) -> str:
        preflight = self.check_preflight()
        return preflight.runtime_version

    def check_preflight(self) -> SandboxRuntimePreflight:
        """Run or delegate the gVisor runtime preflight check (never executes learner code)."""
        if self._preflight_fn is not None:
            preflight = self._preflight_fn()
        else:
            preflight = check_runtime_preflight(
                runner_image=self._runner_image,
                command_runner=self._command_runner,
            )
        reasons = list(preflight.failure_reasons)
        if self._ipc_parent_dir is not None:
            try:
                validate_ipc_parent_dir(self._ipc_parent_dir)
            except ValueError as exc:
                reasons.append(str(exc))
        elif os.environ.get("VCC_ENV") == "production":
            reasons.append("Production worker requires a shared VCC_IPC_PARENT_DIR")
        public_enabled = os.environ.get("VCC_ALLOW_PUBLIC_CUSTOM_CODE", "false").lower() in (
            "true", "1", "yes", "on"
        )
        accepted = False
        if public_enabled and preflight.ready and not reasons:
            acceptance_errors = acceptance_failure_reasons(
                preflight.runner_image, preflight.runtime_version, self._command_runner, 3.0
            )
            reasons.extend(acceptance_errors)
            accepted = not acceptance_errors
        preflight = replace(
            preflight, ready=preflight.ready and not reasons,
            failure_reasons=tuple(reasons), acceptance_verified=accepted,
        )
        self._cached_preflight = preflight
        return preflight

    def is_cancelled(self, job_id: UUID) -> bool:
        """Return True if `job_id` has been cancelled."""
        with self._lock:
            return job_id in self._cancelled_jobs

    def cancel_invocation(self, job_id: UUID) -> bool:
        """Force-remove any active container(s) for `job_id` via `docker rm -f`."""
        with self._lock:
            self._cancelled_jobs.add(job_id)
            containers = list(self._active_containers.get(job_id, set()))

        removed_any = False
        for cname in containers:
            if self._force_remove_container(cname):
                removed_any = True
        return removed_any

    def _force_remove_container(self, container_name: str) -> bool:
        try:
            proc = self._command_runner(["docker", "rm", "-f", container_name], 5.0)
            return proc.returncode == 0
        except Exception:
            return False

    def execute(self, req: ExecutionRequest) -> ExecutionObservation:
        """Execute a single isolated case inside a fresh `runsc` container."""
        spec, canonical_args = _verify_request_bindings(req)

        start_ts = self._clock_fn()
        preflight = self.check_preflight()
        if not preflight.ready:
            elapsed_ms = max(0, int((self._clock_fn() - start_ts) * 1000))
            return ExecutionObservation(
                kind=ExecutionObservationKind.UNAVAILABLE,
                return_value=None,
                error_type="SandboxUnavailableError",
                error_message=f"gVisor sandbox unavailable: {preflight.summary}"[:1024],
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=elapsed_ms,
            )

        payload = {
            "mode": "execute",
            "job_id": str(req.job_id),
            "exercise_id": str(req.revision.exercise_id),
            "spec_version": str(req.revision.spec_version),
            "function_name": spec.function_name,
            "source_code": req.source_code,
            "source_hash": req.revision.code_hash,
            "case_hash": req.case_hash,
            "input_args": canonical_args,
            "budget": req.budget.model_dump(mode="json"),
        }

        outcome = self._launch_disposable_container(
            job_id=req.job_id,
            payload=payload,
            budget=req.budget,
            max_stdout_pipe_bytes=req.budget.max_stdout_bytes + req.budget.max_result_bytes,
            runner_image=preflight.runner_image,
        )
        return self._validate_observation_shape(req, self._map_execution_outcome(outcome, req.budget))

    def trace(self, req: TraceRequest) -> TraceExecutionReport:
        """Execute a bounded line/call trace inside a fresh `runsc` container."""
        spec, canonical_args = _verify_request_bindings(req)

        start_ts = self._clock_fn()
        preflight = self.check_preflight()
        if not preflight.ready:
            elapsed_ms = max(0, int((self._clock_fn() - start_ts) * 1000))
            unavail_obs = ExecutionObservation(
                kind=ExecutionObservationKind.UNAVAILABLE,
                return_value=None,
                error_type="SandboxUnavailableError",
                error_message=f"gVisor sandbox unavailable: {preflight.summary}"[:1024],
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=elapsed_ms,
            )
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_UNAVAILABLE,
                steps=[],
                total_observed=0,
                trace_truncated=False,
                termination_reason=f"gVisor sandbox unavailable: {preflight.summary}"[:256],
                observation=unavail_obs,
                runtime_version=preflight.runtime_version,
            )

        payload = {
            "mode": "trace",
            "job_id": str(req.job_id),
            "trace_id": str(req.trace_id),
            "exercise_id": str(req.revision.exercise_id),
            "spec_version": str(req.revision.spec_version),
            "function_name": spec.function_name,
            "source_code": req.source_code,
            "source_hash": req.revision.code_hash,
            "case_hash": req.case_hash,
            "input_args": canonical_args,
            "budget": req.budget.model_dump(mode="json"),
        }

        outcome = self._launch_disposable_container(
            job_id=req.job_id,
            payload=payload,
            budget=req.budget,
            max_stdout_pipe_bytes=req.budget.max_stdout_bytes + req.budget.max_trace_bytes,
            runner_image=preflight.runner_image,
        )
        report = self._map_trace_outcome(req, outcome, preflight.runtime_version)
        if report.observation is not None:
            report = report.model_copy(update={'observation': self._validate_observation_shape(req, report.observation)})
        return report

    @staticmethod
    def _validate_observation_shape(req, observation: ExecutionObservation) -> ExecutionObservation:
        if observation.kind == ExecutionObservationKind.RETURN:
            try:
                exercise_registry.validate_prediction(str(req.revision.exercise_id), str(req.revision.spec_version), observation.return_value)
            except ValueError:
                return observation.model_copy(update={'kind': ExecutionObservationKind.INVALID_RESULT, 'return_value': None,
                    'error_type': 'InvalidReturnType', 'error_message': 'Returned value does not match this problem output type.'})
        return observation

    def _launch_disposable_container(
        self,
        *,
        job_id: UUID,
        payload: dict[str, Any],
        budget: ExecutionBudgetConfig,
        max_stdout_pipe_bytes: int,
        runner_image: str,
    ) -> _ContainerRunOutcome:
        if self._ipc_parent_dir is not None:
            validate_ipc_parent_dir(self._ipc_parent_dir)
        elif os.environ.get("VCC_ENV") == "production":
            raise ValueError("Production worker requires a shared VCC_IPC_PARENT_DIR")
        job_input_dir = Path(
            tempfile.mkdtemp(
                prefix=f"vcc_ipc_{job_id.hex[:12]}_",
                dir=str(self._ipc_parent_dir) if self._ipc_parent_dir else None,
            )
        )
        nonce = os.urandom(4).hex()
        container_name = f"vcc-sbx-{job_id.hex[:12]}-{nonce}"
        start_ts = self._clock_fn()
        proc: Any = None

        try:
            # The sandbox's UID 65534 must traverse its own read-only bind root;
            # the host/shared parent stays 0700, hiding every job from other users.
            os.chmod(job_input_dir, 0o755)
            payload_path = job_input_dir / "payload.json"
            payload_path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.chmod(payload_path, 0o444)

            with self._lock:
                if job_id in self._cancelled_jobs:
                    return _ContainerRunOutcome(
                        returncode=None,
                        stdout_text="",
                        stderr_text="Invocation cancelled before launch",
                        stdout_overflow=False,
                        stderr_overflow=False,
                        timed_out=False,
                        startup_timed_out=False,
                        cancelled=True,
                        duration_ms=0,
                    )
                self._active_containers.setdefault(job_id, set()).add(container_name)

            cmd = build_docker_run_command(
                container_name=container_name,
                job_input_dir=job_input_dir,
                budget=budget,
                runner_image=runner_image,
            )

            proc = self._popen_factory(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(_SAFE_SUBPROCESS_ENV),
            )

            stdout_reader = _BoundedStreamReader(proc.stdout, max_stdout_pipe_bytes)
            stderr_reader = _BoundedStreamReader(proc.stderr, budget.max_stderr_bytes)

            startup_deadline_sec = max(0.05, budget.startup_deadline_ms / 1000.0)
            invocation_wall_sec = max(0.05, budget.invocation_wall_ms / 1000.0)

            timed_out = False
            startup_timed_out = False
            try:
                proc.wait(timeout=startup_deadline_sec)
            except subprocess.TimeoutExpired:
                if stdout_reader.total_bytes == 0 and stderr_reader.total_bytes == 0:
                    try:
                        proc.wait(timeout=invocation_wall_sec)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        startup_timed_out = (
                            stdout_reader.total_bytes == 0
                            and stderr_reader.total_bytes == 0
                        )
                else:
                    try:
                        proc.wait(timeout=invocation_wall_sec)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        startup_timed_out = False

            if timed_out:
                self._force_remove_container(container_name)
                try:
                    proc.kill()
                except Exception:
                    pass

            stdout_text = stdout_reader.join_and_decode(timeout=1.0)
            stderr_text = stderr_reader.join_and_decode(timeout=1.0)
            duration_ms = max(0, int((self._clock_fn() - start_ts) * 1000))

            with self._lock:
                was_cancelled = job_id in self._cancelled_jobs

            return _ContainerRunOutcome(
                returncode=getattr(proc, "returncode", None),
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                stdout_overflow=stdout_reader.overflowed,
                stderr_overflow=stderr_reader.overflowed,
                timed_out=timed_out,
                startup_timed_out=startup_timed_out,
                cancelled=was_cancelled,
                duration_ms=duration_ms,
            )
        finally:
            with self._lock:
                active = self._active_containers.get(job_id)
                if active is not None:
                    active.discard(container_name)
                    if not active:
                        self._active_containers.pop(job_id, None)
            if proc is not None and getattr(proc, "returncode", None) is None:
                self._force_remove_container(container_name)
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                shutil.rmtree(job_input_dir)
            except OSError:
                logging.getLogger(__name__).exception("Failed to remove sandbox IPC directory")

    def _map_execution_outcome(
        self, outcome: _ContainerRunOutcome, budget: ExecutionBudgetConfig
    ) -> ExecutionObservation:
        stderr_excerpt = outcome.stderr_text[:4096]
        if outcome.timed_out:
            reason = (
                f"Container startup/execution exceeded deadline ({budget.startup_deadline_ms}ms + {budget.invocation_wall_ms}ms)"
                if outcome.startup_timed_out
                else f"Execution exceeded wall timeout ({budget.invocation_wall_ms}ms)"
            )
            return ExecutionObservation(
                kind=ExecutionObservationKind.TIMEOUT,
                return_value=None,
                error_type="TimeoutError",
                error_message=reason[:1024],
                stdout_excerpt=outcome.stdout_text[:4096],
                stderr_excerpt=stderr_excerpt,
                duration_ms=outcome.duration_ms,
            )

        if outcome.returncode in (137, 139) or "oom" in stderr_excerpt.lower():
            return ExecutionObservation(
                kind=ExecutionObservationKind.RESOURCE_LIMIT,
                return_value=None,
                error_type="ResourceLimitExceeded",
                error_message=(
                    f"Container terminated by resource/memory/PID limit (exit {outcome.returncode})"
                )[:1024],
                stdout_excerpt=outcome.stdout_text[:4096],
                stderr_excerpt=stderr_excerpt,
                duration_ms=outcome.duration_ms,
            )

        if outcome.stdout_overflow:
            return ExecutionObservation(
                kind=ExecutionObservationKind.RESOURCE_LIMIT,
                return_value=None,
                error_type="OutputLimitExceeded",
                error_message="Container stdout/result stream exceeded configured byte limit",
                stdout_excerpt=outcome.stdout_text[:4096],
                stderr_excerpt=stderr_excerpt,
                duration_ms=outcome.duration_ms,
            )

        try:
            user_stdout, frame = parse_runner_frame(
                outcome.stdout_text,
                expected_mode="execute",
                max_result_bytes=budget.max_result_bytes,
            )
        except FrameParseError as exc:
            return ExecutionObservation(
                kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None,
                error_type="InvalidRunnerFrame",
                error_message=str(exc)[:1024],
                stdout_excerpt=outcome.stdout_text[:4096],
                stderr_excerpt=stderr_excerpt,
                duration_ms=outcome.duration_ms,
            )

        frame_kind = str(frame.get("kind", "")).upper()
        stdout_final = str(frame.get("stdout_excerpt", user_stdout))[:4096]
        stderr_final = str(frame.get("stderr_excerpt", stderr_excerpt))[:4096]

        if frame_kind == "TIMEOUT":
            return ExecutionObservation(
                kind=ExecutionObservationKind.TIMEOUT,
                return_value=None,
                error_type=str(frame.get("error_type") or "TimeoutError")[:128],
                error_message=str(
                    frame.get("error_message") or "Execution timed out inside sandbox"
                )[:1024],
                stdout_excerpt=stdout_final,
                stderr_excerpt=stderr_final,
                duration_ms=outcome.duration_ms,
            )

        if frame_kind == "RESOURCE_LIMIT":
            return ExecutionObservation(
                kind=ExecutionObservationKind.RESOURCE_LIMIT,
                return_value=None,
                error_type=str(frame.get("error_type") or "ResourceLimitExceeded")[:128],
                error_message=str(
                    frame.get("error_message") or "Resource limit exceeded inside sandbox"
                )[:1024],
                stdout_excerpt=stdout_final,
                stderr_excerpt=stderr_final,
                duration_ms=outcome.duration_ms,
            )

        if frame_kind == "EXCEPTION":
            return ExecutionObservation(
                kind=ExecutionObservationKind.EXCEPTION,
                return_value=None,
                error_type=str(frame.get("error_type") or "RuntimeError")[:128],
                error_message=str(
                    frame.get("error_message") or "Unhandled exception in learner code"
                )[:1024],
                stdout_excerpt=stdout_final,
                stderr_excerpt=stderr_final,
                duration_ms=outcome.duration_ms,
            )

        if frame_kind == "INVALID_RESULT":
            return ExecutionObservation(
                kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None,
                error_type=str(frame.get("error_type") or "InvalidReturnValue")[:128],
                error_message=str(
                    frame.get("error_message") or "Function did not return a strict integer"
                )[:1024],
                stdout_excerpt=stdout_final,
                stderr_excerpt=stderr_final,
                duration_ms=outcome.duration_ms,
            )

        if frame_kind == "RETURN":
            if outcome.returncode not in (0, None):
                return ExecutionObservation(
                    kind=ExecutionObservationKind.INVALID_RESULT,
                    return_value=None,
                    error_type="NonZeroExitWithReturnFrame",
                    error_message=(
                        f"Container exited with code {outcome.returncode} despite RETURN frame"
                    )[:1024],
                    stdout_excerpt=stdout_final,
                    stderr_excerpt=stderr_final,
                    duration_ms=outcome.duration_ms,
                )
            raw_val = frame.get("return_value")
            try:
                from backend.app.exercises.values import validate_value
                validate_value(raw_val)
                valid_return = True
            except ValueError:
                valid_return = False
            if not valid_return:
                return ExecutionObservation(
                    kind=ExecutionObservationKind.INVALID_RESULT,
                    return_value=None,
                    error_type="InvalidReturnType",
                    error_message=(
                        f"Return value must be a bounded strict scalar/list, got {type(raw_val).__name__}"
                    )[:1024],
                    stdout_excerpt=stdout_final,
                    stderr_excerpt=stderr_final,
                    duration_ms=outcome.duration_ms,
                )
            return ExecutionObservation(
                kind=ExecutionObservationKind.RETURN,
                return_value=raw_val,
                error_type=None,
                error_message=None,
                stdout_excerpt=stdout_final,
                stderr_excerpt=stderr_final,
                duration_ms=outcome.duration_ms,
            )

        return ExecutionObservation(
            kind=ExecutionObservationKind.INVALID_RESULT,
            return_value=None,
            error_type="UnknownRunnerFrameKind",
            error_message=f"Unsupported runner frame kind: {frame_kind!r}"[:1024],
            stdout_excerpt=stdout_final,
            stderr_excerpt=stderr_final,
            duration_ms=outcome.duration_ms,
        )

    def _map_trace_outcome(
        self,
        req: TraceRequest,
        outcome: _ContainerRunOutcome,
        runtime_version: str,
    ) -> TraceExecutionReport:
        if outcome.timed_out:
            timeout_obs = ExecutionObservation(
                kind=ExecutionObservationKind.TIMEOUT,
                return_value=None,
                error_type="TimeoutError",
                error_message=f"Trace exceeded wall timeout ({req.budget.invocation_wall_ms}ms)",
                stdout_excerpt=outcome.stdout_text[:4096],
                stderr_excerpt=outcome.stderr_text[:4096],
                duration_ms=outcome.duration_ms,
            )
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_TIMEOUT,
                steps=[],
                total_observed=0,
                trace_truncated=False,
                termination_reason="Trace invocation timed out",
                observation=timeout_obs,
                runtime_version=runtime_version,
            )

        try:
            user_stdout, frame = parse_runner_frame(
                outcome.stdout_text,
                expected_mode="trace",
                max_result_bytes=req.budget.max_trace_bytes,
                max_trace_bytes=req.budget.max_trace_bytes,
            )
        except FrameParseError as exc:
            tampered_obs = ExecutionObservation(
                kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None,
                error_type="TraceFrameError",
                error_message=str(exc)[:1024],
                stdout_excerpt=outcome.stdout_text[:4096],
                stderr_excerpt=outcome.stderr_text[:4096],
                duration_ms=outcome.duration_ms,
            )
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_TAMPERED,
                steps=[],
                total_observed=0,
                trace_truncated=False,
                termination_reason=f"Invalid or tampered trace frame: {exc}"[:256],
                observation=tampered_obs,
                runtime_version=runtime_version,
            )

        raw_steps = frame.get("steps", [])
        if not isinstance(raw_steps, list):
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_TAMPERED,
                steps=[],
                total_observed=0,
                trace_truncated=False,
                termination_reason="Trace frame steps field is not a list",
                observation=None,
                runtime_version=runtime_version,
            )

        validated_steps: list[TraceStep] = []
        tampered = bool(frame.get("tampered", False))
        for raw_step in raw_steps[: min(len(raw_steps), req.budget.max_trace_steps, 250)]:
            try:
                step = (
                    raw_step
                    if isinstance(raw_step, TraceStep)
                    else TraceStep.model_validate(raw_step)
                )
            except Exception as exc:
                return TraceExecutionReport(
                    trace_id=req.trace_id,
                    revision=req.revision,
                    case_hash=req.case_hash,
                    status=TraceExecutionStatus.TRACE_TAMPERED,
                    steps=[],
                    total_observed=0,
                    trace_truncated=False,
                    termination_reason=f"Invalid TraceStep schema: {exc}"[:256],
                    observation=None,
                    runtime_version=runtime_version,
                )
            if (
                step.source_hash != req.revision.code_hash
                or step.attribution_status == TraceAttributionStatus.TAMPERED
            ):
                tampered = True
            validated_steps.append(step)

        truncated = bool(frame.get("trace_truncated", False)) or (
            len(raw_steps) > len(validated_steps)
        )
        total_observed = frame.get("total_observed", len(validated_steps))
        if type(total_observed) is not int or total_observed < len(validated_steps):
            total_observed = len(validated_steps)

        obs_payload = frame.get("observation")
        obs: ExecutionObservation | None = None
        if isinstance(obs_payload, dict):
            try:
                obs = ExecutionObservation.model_validate(obs_payload)
            except Exception:
                obs = None
        elif "kind" in frame:
            raw_kind = str(frame.get("kind", "RETURN")).upper()
            raw_ret = frame.get("return_value")
            obs = ExecutionObservation(
                kind=ExecutionObservationKind(raw_kind),
                return_value=raw_ret if raw_kind == "RETURN" else None,
                error_type=frame.get("error_type"),
                error_message=frame.get("error_message"),
                stdout_excerpt=str(frame.get("stdout_excerpt", user_stdout))[:4096],
                stderr_excerpt=str(frame.get("stderr_excerpt", outcome.stderr_text))[:4096],
                duration_ms=outcome.duration_ms,
            )

        status_raw = str(frame.get("status") or frame.get("trace_status") or "").upper()
        if tampered or status_raw == "TRACE_TAMPERED":
            status = TraceExecutionStatus.TRACE_TAMPERED
            reason = str(
                frame.get("termination_reason")
                or "Trace frame tampering or source_hash mismatch detected"
            )[:256]
        elif status_raw == "TRACE_TIMEOUT":
            status = TraceExecutionStatus.TRACE_TIMEOUT
            reason = str(frame.get("termination_reason") or "Trace timed out")[:256]
        elif truncated or status_raw == "PARTIAL":
            status = TraceExecutionStatus.PARTIAL
            reason = str(
                frame.get("termination_reason")
                or f"Trace truncated at {len(validated_steps)} steps"
            )[:256]
        else:
            status = TraceExecutionStatus.COMPLETED
            reason = str(
                frame.get("termination_reason") or "Trace completed normally"
            )[:256]

        return TraceExecutionReport(
            trace_id=req.trace_id,
            revision=req.revision,
            case_hash=req.case_hash,
            status=status,
            steps=validated_steps,
            total_observed=total_observed,
            trace_truncated=truncated,
            termination_reason=reason,
            observation=obs,
            runtime_version=runtime_version,
        )
