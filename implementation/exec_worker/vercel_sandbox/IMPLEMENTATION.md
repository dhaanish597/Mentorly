# Disposable execution runner status

The synchronous interface is `exec_worker.vercel_sandbox.adapter.VercelSandboxRunner`.
It preserves the existing gVisor runner and reuses its strict result parser and
request/spec/case validation. It independently rejects every source SHA256 mismatch.
Only allowlisted guest assets, the reviewed native binary and trusted controller
are eligible for upload; a missing/stale build fails before VM creation.

The supervisor creates private mount, PID, network, IPC and UTS namespaces, a
read-only chroot containing the Python runtime, and an 8 MB scratch tmpfs with
`noexec,nosuid,nodev`. The learner runs as UID/GID 65534 with all capability sets
dropped and `no_new_privs`. An external cgroup caps memory at 256 MB, swap at zero,
and PIDs at 16. External aggregate CPU accounting, startup/wall deadlines, bounded
pipes and full-cgroup termination supplement the guest's existing limits.

Every invocation uses a new nonpersistent one-vCPU Vercel microVM, deny-all
networking, no exposed ports, no drives, no guest environment secrets and a
20-second provider lifetime. Creation uses the supported universal repository
reference. Its returned digest must equal the exact accepted immutable image
before any staging or code execution. Runtime identity must also match acceptance
before the learner starts. No snapshots are requested. Every known VM deletion is attempted;
failed deletion records an obligation and blocks later public preflight.

## Current evidence

- 69 focused offline transport/integration/authentication tests pass. They establish transport/gate
  behavior and bounded coordinator responses, not Linux isolation.
- A fixed runtime-only Python SDK probe succeeded and was deleted. It observed
  Python 3.14.4, kernel 6.18.56 and universal image digest
  `9b2669397f26336812ec6835c2f67db6a546074cbabb05db93bf5e669f71ec5d`.
- Both supervised creation attempts failed with provider HTTP 403. Read-only
  Sandbox inventory, account lookup and project lookup also returned 403. No
  supervised learner invocation or live isolation acceptance has run.
- The later ambiguous attempt is recorded in `supported-reference-probe.json`.
  Its Sandbox name requires inventory/deletion confirmation when access returns.
  The earlier failed attempt predates name recording, so its possible resource
  must be checked in the provider inventory as well. Both requested nonpersistence.
- Independent code review found and fixed an `ldd` mount defect, invalid UTF-8
  replacement, incomplete inherited-code acceptance hashing and deletion records
  lost during simultaneous provider/client cleanup failures. Follow-up review also
  found and fixed cross-instance recovery and unexecuted forgery-control false positives.
  Final Python review verified the fixes; it did not perform cloud acceptance.
- Project OIDC subsequently authenticated the Python SDK. The single authorized
  fixed native-capability probe completed on the pinned image and confirmed all
  eleven queried C API symbols, Python 3.14.4, and no compiler, `python-config`,
  `Python.h` or `patchlevel.h` at the configured include directory. Matching
  headers could not be established. Its command exited zero, the VM was deleted,
  and no learner source or native driver was executed. See
  `native-capability-probe.json`. The proposed exact-version native driver cannot
  be built in this image with the currently installed development dependencies.
  No additional compiler/header provisioning or sandbox creation was performed.

## Acceptance and integration

`live_acceptance.py` runs only fixed finite controls, at most 32 new VMs, never
caller-supplied learner code. It tests below/above memory, PID and tmpfs controls,
CPU/wall/output limits, network/filesystem/privileges, trace behavior, process-tree
cleanup, cancellation and a forged valid single result frame. It stops on the
first transport error and saves failed evidence. It has not been run here.

The earlier Python harness exposed its result FD and mutable serializer to learner
code. The prepared native runner consumes its private key before learner code,
captures actual C API return/trace values, seals frame mutation, and signs a
separate result pipe bound to the invocation payload. The controller authenticates
that V2 frame before using the existing strict domain parser. Source review and
offline authentication tests are not native runtime acceptance. No compiler
execution or live native control ran. No `accepted-runtime.json`
has been produced, and public execution remains disabled.

The in-process coordinator preserves the inherited overall response deadline.
After acquiring its bounded capacity slot, a worker owns the synchronous
transport and registry cleanup. On a caller timeout, cancellation is requested
without waiting on a blocked SDK call; no eventual observation is published.
The worker keeps its slot until transport cleanup finishes. Revision checks and
verification cancellation checks still run around dispatch. These are offline
contract tests; they do not establish physical cloud cancellation or isolation.

After real controls and independent review pass, package the exact nonsecret
acceptance JSON and provide its file path and separately reviewed SHA256 as
`VCC_VERCEL_SANDBOX_ACCEPTANCE_PATH` and
`VCC_VERCEL_SANDBOX_ACCEPTANCE_SHA256`. `VCC_PUBLIC_EXECUTION_ENABLED` alone cannot
enable this runner. Any guest, adapter, gate, harness or image/runtime change
invalidates the bound artifact.

The trusted deployment needs `vercel-sandbox==1.0.0`, the backend's Psycopg driver,
all `exec_worker/runner/*.py`,
all `exec_worker/worker_app/*.py` (the package eagerly imports its broker), and
`vercel_sandbox/{__init__,adapter,supervisor,acceptance,live_acceptance,cleanup_store}.py`
and `cleanup_store.sql` (both gate/harness/store sources participate in the acceptance hash).
Only the allowlist returned by `acceptance.guest_files()` enters a microVM.
The legacy Node probe dependency is not required by the Python transport.
Install the exact six SDK/runtime pins in `requirements.txt`; acceptance verifies
their installed versions. The backend's existing Pydantic pin is unchanged.

Before production integration, apply `cleanup_store.sql` through the backend's
trusted migration path and construct `PostgresSandboxCleanupStore` with its private
DSN factory. Pass this store to `VercelSandboxTransport(cleanup_store=store)` and
that transport to `VercelSandboxRunner(transport=transport)`. The store commits a
name before cloud creation and removes it only after confirmed provider deletion
or absence. Its table enables RLS and denies anonymous/authenticated client access.
Recovery atomically claims only expired records, with a conservative 120-second
delay beyond the 20-second VM lifetime and bounded SDK creation requests. Owner
IDs prevent a late creator from clearing another recovery owner's record. Fresh
registrations remain active across serverless instances; stale or cleanup-required
records block public preflight. Ambiguous, unacknowledged creations are never
cleared automatically, including after a provider 404. Inventory confirmation is
required for those records. `transport.recover_cleanup()` never resumes VMs.
Registration/DB failures fail closed.
The default transport has no durable store, so public preflight always fails.

The SQL/store have not been applied or exercised against Supabase in this task.
The local probe's older ambiguous attempts also require inventory confirmation;
the new store cannot retrospectively recover an unknown name. Existing backend
job admission, serialized capacity and free-account quota enforcement remain the
integration owner's responsibility. Do not enable execution until real persistence,
restart recovery, isolation and forged-frame controls all pass.

The acceptance CLI requires `--confirmed-free-hobby`, `--output`, and a private
PostgreSQL DSN environment variable selected by `--postgres-dsn-env` (default
`VCC_DATABASE_URL`). It does not accept a secret as a command-line value. Apply
the cleanup schema first. Missing storage or package bindings abort acceptance.
