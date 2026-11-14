# Execution Worker & Disposable gVisor Sandbox (`exec_worker/` — Phase 1 / T-02)

This package implements the **Phase 1 (`T-02`) Safe Execution Broker and Disposable Runner** according to `IMPLEMENTATION_PLAN.md` §5.2, §6.1, §7, §9, §11.1, and §12.3.

## Architecture & Trust Boundary

1. **`exec_worker/worker_app/` (Trusted Broker Control Plane — `Dockerfile.worker`):**
   - `main.py`: FastAPI service (`create_broker_app`) authenticated via `X-Internal-Worker-Secret` (`secrets.compare_digest`). Exposes `/internal/health`, `/internal/execute`, `/internal/verify`, `/internal/trace`, and `/internal/cancel/{job_id}`.
   - `sandbox_runner.py`: Implements `check_runtime_preflight()`, `build_docker_run_command()`, and `GVisorSandboxRunner`. Launches a fresh per-invocation container (`docker run --rm --runtime=runsc --network=none --read-only --user 65534:65534 --cap-drop=ALL --security-opt=no-new-privileges`) with a job-private read-only bind mount (`-v <job_input_dir>:/ipc_in:ro`). Never falls back to ordinary Docker (`runc`), host `subprocess`, `RestrictedPython`, or in-broker execution.
   - `verifier_harness.py`: Runs `ast.parse` syntax validation, evaluates trusted reference oracles (`backend.app.exercises.registry.evaluate`) and output comparisons (`registry.compare_output`) strictly outside the sandbox, enforces `job_wall_ms` and `replay_reserve_ms`, and replays every candidate failure in a second fresh sandbox invocation (`COUNTEREXAMPLE_CONFIRMED` vs `REPLAY_UNCONFIRMED` vs `VERIFICATION_INCOMPLETE`).
   - `trace_recorder.py`: Implements `InSandboxTracer` (`sys.settrace` post-line local snapshots with `200` head + `50` tail ring buffer, `max_trace_snapshots_work=2000`, `AMBIGUOUS` exception markers, and `TAMPERED` detection) and broker-side `record_execution_trace`.

2. **`exec_worker/runner/` (Untrusted In-Sandbox Entrypoint — `Dockerfile.runner`):**
   - `run_invocation.py`: Runs inside `runsc` as UID/GID `65534:65534` (the Docker ENTRYPOINT explicitly bootstraps the trusted `/app` package path under `python3 -I -B`). Duplicates FD 1 for the framed result channel and redirects standard FD 1 to `/dev/null` while binding `sys.stdout`/`sys.stderr` to `BoundedTextStream(65536)` so learner `print()` or `os.write(1, ...)` calls cannot spoof the result frame.
   - `protocol.py`: Enforces `<<VCC_RUNNER_FRAME_V1_BEGIN>>` / `<<VCC_RUNNER_FRAME_V1_END>>` framing, rejects `FORBIDDEN_LEARNER_KEYS` (`reference_output`, `challenge_id`, `case_hash`, `verification_status`), and rejects `bool`/`float` return values (`type(val) is int`).
   - `safe_serializer.py`: Serializes frame locals using exact built-in type checks (`type(v) is ...`) without ever calling `__repr__`, `__str__`, `__iter__`, `__getattr__`, `__eq__`, or `__hash__` on learner objects.

## Running Offline Unit Tests vs Live gVisor Acceptance

```bash
# Safe offline unit tests (runs on any Python 3.11+ environment or Google Colab)
PYTHONPATH=backend:. python3 -m unittest discover -s exec_worker/tests -p "test_*.py" -v

# Daemon-free packaging checks (no learner execution; not runtime acceptance)
python3 -m pytest exec_worker/tests/test_deployment_packaging.py -q

# Actual acceptance is an operator-only Linux gate; follow ../docs/DEPLOYMENT.md.
# Do not interpret offline/mocked/skipped tests as passed gVisor acceptance.
```

## Deployment packaging boundary

See [deployment prerequisites and acceptance gates](../docs/DEPLOYMENT.md).
The worker image deliberately packages `models`, `exercises`, and `verification`
(shrinking dependency), plus broker/runner modules; it does not copy backend
routes, databases or tests. Docker CLI is packaged, but the **verified host gVisor
installation including sidecars** must be mounted read-only at `/opt/vcc/gvisor`.
The host daemon must register this exact absolute runsc path.

`VCC_IPC_PARENT_DIR` must be an existing root-owned `0700`, absolute, non-symlink
host directory mounted at the **same absolute path** in the worker. Default Compose
uses `/var/lib/vcc/ipc`; a worker-private `/tmp` bind path does not work with the host
socket. Each fresh sandbox sees only its own read-only job directory. UID 65534
needs that job root `0755` and payload `0444`; the shared parent stays private.
Invocation cleanup removes job directories and logs cleanup failures. After a
crash, stop the worker and clean only verified orphaned sandbox containers and
`vcc_ipc_*` directories; never prune unrelated host resources.

Both services default `VCC_ALLOW_PUBLIC_CUSTOM_CODE=false`. An operator-reviewed
real acceptance record is mounted read-only into both at
`/etc/vcc/acceptance/accepted.json` via `VCC_ISOLATION_ACCEPTANCE_FILE`. Marker
presence alone cannot enable execution: worker preflight binds the accepted
immutable runner image, Linux Docker daemon identity/runtime configuration,
runsc version, binary SHA256 and sidecar-bundle SHA256 to fresh probes. Internal
health adds `acceptance_verified`, false unless public opt-in passes all bindings.
Changed/missing evidence degrades readiness. No fallback executes learner code on
the host or worker Python interpreter, or in ordinary Docker.

The Docker socket remains host-root-equivalent despite container hardening. Use a
dedicated Linux host and keep the worker internal. This packaging was checked
without a daemon on macOS: images, runtime acceptance and public hosting are **not
verified or provisioned**.
