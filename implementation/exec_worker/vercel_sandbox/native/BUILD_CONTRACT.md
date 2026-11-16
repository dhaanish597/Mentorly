# Exact native runner build contract

The reviewed public GitHub build passed on 15 November 2026 in run
`43704424706`, commit `8bfc1fb314ccb94facb04a3de6ada374e0740d7f`.
The decoded ELF64 x86_64 shared object is 39,184 bytes, with SHA-256
`7576db6f8e031b07626428dec6b4970ce52b521fd4975fd41a696213552c5881`.
Source, build script, binary and workflow identities were independently checked.
No native guest acceptance has passed. Public execution remains closed.

## Build

The manual workflow is `.github/workflows/native-runner-build.yml`. It uses only
the standard `ubuntu-24.04` runner in a public repository, a ten-minute deadline,
read-only repository permission, immutable checkout/setup-python Action commit
pins, exact Python `3.14.4` x64, and no artifact, cache, package upload or snapshot.
The root coordinator owns reviewing, committing, pushing and dispatching it.
GitHub requires a dispatchable workflow to exist on the default branch; selecting
the reviewed release ref must be checked before invoking it.

After that prerequisite, the root can run:

```sh
gh workflow run native-runner-build.yml --repo dhaanish597/Mentorly --ref REVIEWED_RELEASE_REF
gh run list --repo dhaanish597/Mentorly --workflow native-runner-build.yml --limit 5
gh run view VERIFIED_RUN_ID --repo dhaanish597/Mentorly --log > /private/tmp/viva-native-build.log
```

Replace the ref/run placeholders with the reviewed default branch and verify
the observed run's full commit. GitHub rejected the abbreviated commit as a
dispatch ref; `main` was inspected before dispatch and the run's commit matched.
Do not accept a run on another commit, a private repository, a larger runner or
an unreviewed workflow.

`native/build.py` checks Linux x86_64, the exact patch version, non-debug GIL
configuration, expected SOABI and installed development headers. It builds a
shared `_viva_native.so` with GCC, stack protection, fortified libc operations,
RELRO and immediate binding, linked to OpenSSL's major-3 ABI. CPython symbols
resolve from the guest interpreter. The reviewed build completed successfully;
actual guest loading remains unverified.

The emitted binary is capped at 131,072 bytes. It is base64 encoded between
`VIVA_NATIVE_BINARY_BEGIN` and `VIVA_NATIVE_BINARY_END`; each data line starts
`VIVA_NATIVE_BINARY `. A single `VIVA_NATIVE_PROVENANCE ` JSON line records the
source, script, full installed header tree, selected headers, build interpreter
and binary SHA256s; SOABI/GIL/debug configuration; compiler flags; ELF dynamic
dependencies and symbol-version requirements; workflow commit and run ID.
The provenance explicitly records `live_accepted: false`.

Before staging, compare the run commit, source/script hashes and actual decoded
binary SHA256/size with the reviewed checkout. These comparisons passed for run
`43704424706`; actual dependencies require OpenSSL 3.0.0 and at most glibc 2.17.
Preserve the exact nonsecret
provenance beside the binary. Reject missing/duplicate/truncated records or any
hash mismatch. Logs are bounded transport, not an acceptance attestation.

## Required next wiring and acceptance

The prepared supervisor now uses a separate native-result pipe and fresh
controller-held key pipe, binds the exact payload SHA256, stages native
dependencies, and leaves learner `/proc` empty. Its controller uses
`native_protocol.py` to authenticate the native V2 frame before converting it to
the existing strict V1 domain parser. Ordinary stdout/stderr remain independent
bounded channels. This wiring has not run on Linux or in the cloud.
The raw learner stdout channel must never supply a return or trace envelope.

The native `run` method consumes and closes the key pipe before top-level learner
source executes. Initialization is permanently one-shot. A real return/exception
is obtained through the C API and serialized with exact-type/work bounds. Native
line/local records are collected from the submitted source's code identities.
Declared local/cell/free-variable names are cached before source execution, then
read individually with the public `PyFrame_GetVar` C API under the work budget.
Dynamic extra entries added through `locals()` are omitted and each snapshot
reports `dynamic_extra_locals_omitted`. The controller never materializes or scans
the learner's complete extra-locals map.
Signing is fenced to the original PID/TID and binds the complete payload hash.
The process exits directly after writing the signed frame, without invoking a
mutable Python serializer, `atexit`, or learner destructors after signing.

The immutable native audit policy rejects FFI, unsafe bytecode deserialization
and construction, heap/frame introspection, monitoring/trace manipulation,
subinterpreters and subsequent native module loads, including string-subclass
loader aliases. Central native frame descriptors reject trace-state and line
mutation, including direct `object.__setattr__` and GC-retained frame routes.
An architecture-checked inherited seccomp filter rejects process
memory operations, native execution/executable mappings and shared-memory thread
creation and signal-handler installation. Fixed native policy checks test
process-memory denial and read/write versus executable mappings before source
execution. The external mount, UID/capability, cgroup, network and pipe limits
remain required independent controls.

Before learner dispatch, verify actual guest CPython `3.14.4`, non-debug GIL,
SOABI, x86_64, disabled JIT, OpenSSL/libc/ELF dependency compatibility, and the
exact binary hash. Guest load is a fixed capability control, separate from the
build. Do not guess ABI declarations or treat exported symbols as compatibility.

The prepared CLI makes at most **32 disposable VMs**: 31 fixed controls plus one
cancellation control, with no caller-supplied source. Every fixed source parsed
and passed domain/guest budget validation without execution. The locals control
uses the valid minimum work budget of 50. No native cloud control has run.
The live control plan covers genuine returns/exceptions and common DSA
stdlib algorithms; normal trace line/local/recursion behavior; direct V1 and V2
frame forgery followed by exit; altered/replayed MACs; descriptor discovery;
fork/reload/reentry; native aliases, FFI/process-memory/bytecode attacks;
monitoring registration; GC callbacks and retained-frame trace mutation;
signal-handler denial; output,
memory, CPU, wall, PID, tmpfs and cross-VM limits; cancellation; and durable
cleanup/recovery. Every VM is disposable, deny-all and receives no application
credentials. No further VM creation is authorized by this preparation.

Native audit/OS restrictions intentionally reject unrestricted FFI, unsafe
bytecode, new native modules, threads sharing process memory and debugger/frame
introspection. The common preloaded DSA library set still needs actual coverage
tests. A failed or unsupported operation must report an explicit failure. Trace
never falls back to the forgeable Python envelope. No unrestricted Python,
native return authenticity or live trace acceptance is claimed yet.

## Persistence and deployment gaps

The separate cleanup workstream has prepared private-schema migration `0007`
and a store using the shared PostgreSQL runtime. Source review and an independent
local PostgreSQL rerun passed 38 tests, including all 19 cleanup tests. The store
preserves verified TLS, transaction-pooler compatibility, ownership and the
120-second ambiguous-creation recovery fence. The root coordinator owns applying
the reviewed additive migration and constructing the factory. The native
acceptance workstream has not applied any database migration. Do not apply the
cleanup SQL by itself to Supabase.

The local backend factory now connects the trusted repository, durable admission
and cancellation state to `InProcessWorkerClient` and the compatible cleanup store
to `VercelSandboxTransport`. Independent final tests and guarded CLI review are
pending. Package
`integration.py`, `cleanup_store.py/.sql`, `live_acceptance.py`,
`native_protocol.py`, reviewed native binary/provenance and their exact digest
dependencies. No acceptance artifact exists. The staged web/API deployment must
keep `VCC_PUBLIC_EXECUTION_ENABLED=false` until all owning-source and actual
cloud acceptance gates pass.
