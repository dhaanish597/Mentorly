# Native execution authenticity proposal

The current Python guest harness executes learner code in the interpreter that
owns its output descriptor and serializer. A learner can write a valid framed
`RETURN` and terminate the process. A Python-held nonce, HMAC key, FD shuffle, or
external signature over the same untrusted Python envelope does not establish
that the requested function returned that value.

## Proposed boundary

Keep the genuine disposable microVM, private namespaces, UID/capability policy,
cgroup controls, read-only runtime and noexec scratch mount. Add an exact-version
native CPython driver, built and reviewed for Python 3.14.4 on the pinned Linux
image. Do not guess non-stable tracing ABI declarations.

The root controller gives the native driver a fresh key through a pipe. The
driver consumes and closes that pipe before any top-level learner source runs.
It copies source, input/case, job and trace bindings into private C storage,
permanently locks initialization and rejects reentrant execution. Signing is
fenced to the original process and native thread IDs, including after a fork.
No Python-visible signing function or key object is exposed.

The driver calls the requested function through the C API and serializes its
actual return object in native code with exact-type, size and work bounds. It
does not obtain an observation envelope from the old mutable Python harness or
call learner-controlled repr, exception formatting or stream serializers.
Learner stdout/stderr go to separate bounded controller pipes. An authenticated
result pipe carries a V2 body and MAC bound to this invocation. The production
controller rejects every V1, unsigned, altered and replayed frame. It destroys
the complete process tree after authenticated completion or any failure.

## Controls needed to protect native state

Private C memory is not enough while arbitrary FFI/native code can read it.
Before learner execution, preload the explicitly approved native standard-library
modules and then deny subsequent native loads by actual file identity/path,
including ExtensionFileLoader aliases. Remove unsafe extension/test modules
and site-packages from the learner root. Keep learner `/proc` absent.

Install an immutable native C audit hook before source compilation/execution.
Block unsafe bytecode construction/deserialization, FFI, subinterpreters and
frame/heap introspection, including `_getframe`, `_current_frames`, GC enumerators,
and traceback/generator/coroutine frame access. For tracing, this also prevents
direct `frame.f_trace` mutation; blocking `sys.settrace` alone is insufficient.

An inherited seccomp policy must deny ptrace/process-memory read/write, new
executable mappings/protection changes, and native exec paths that undermine this
policy. The policy must check the architecture and reject alternate syscall ABIs.
The read-only/noexec mounts remain necessary independent controls. These are
additional barriers inside the existing OS sandbox, not an AST-filter fallback.

## Trace provenance

Collect line/call/return events and bounded exact-type local snapshots through a
native trace callback into C-owned records. Bind code-object identity to the
submitted source. Protect trace installation and records from Python reflection.
Collect the real return separately from trace data. Trace needs its own acceptance
flag and stays unavailable until adversarial provenance and normal algorithm
coverage pass. Native tracing must not silently degrade to the old forgeable
Python trace envelope.

## Threat limitations and acceptance

This relies on patched CPython and a vetted native-module surface, as well as the
existing Linux/VM boundary. It does not promise unrestricted FFI, arbitrary native
code loading, unsafe bytecode construction or frame-debugger compatibility. These
features must fail explicitly; normal algorithm Python and approved standard
modules must retain meaningful coverage. Native interpreter memory-corruption
vulnerabilities remain part of the runtime security assumption.

Before enablement, prove native loading and the denial controls on the actual
Linux image. Test direct V1/V2 forgery, MAC modification/replay, FD discovery,
fork/reload/reentrancy, native-module aliases, process-memory and bytecode attacks,
plus genuine return/exception and trace behavior. Preserve all external resource,
cancellation and durable cleanup acceptance. Native source/binary, compiler flags,
CPython/runtime and policy identities must invalidate old acceptance.

The native runtime and trusted controller wiring are now prepared in
`native/guard.c`, `native/build.py`, `native_protocol.py`, and `supervisor.py`.
Central immutable frame descriptors also reject GC-retained frame trace-state
mutation; snapshots use bounded declared-variable extraction. The build contract
and fixed controls are in `native/BUILD_CONTRACT.md` and `live_acceptance.py`.
No compiler execution, Linux load, native learner execution or live acceptance
has run. The current public gate remains disabled.

## Fixed capability probe, 15 November 2026

The single authorized deny-all nonpersistent VM authenticated with project OIDC.
Its pinned image reported Python 3.14.4 and exported the eleven queried C API
symbols. It had no compiler or `python-config`, and its configured
`/usr/include/python3.14` lacked both `Python.h` and `patchlevel.h`. Exact patch
version headers therefore remain unverified. The fixed command exited zero;
the VM was deleted in cleanup. No learner source, native driver or trusted
application secrets were sent to it. `native-capability-probe.json` records
`accepted: false` and `learner_executed: false`.

The native driver cannot currently be built against verified matching headers
in this image. A manual external build on a free public standard GitHub runner
has been prepared using exact Python 3.14.4 headers. It remains unexecuted;
exported symbols alone do not establish a correct tracing ABI. No guessed ABI
declarations, new VM, snapshot or development-package installation was used.
