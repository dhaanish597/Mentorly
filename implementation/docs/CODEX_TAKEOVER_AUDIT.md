# Execution-based takeover audit

Updated: 2026-11-14. Scope is the single local implementation, not a claim that P0–P9 is complete.

## Local continuation completed (2026-11-14)

Shared pinned Hypothesis generation now powers the worker, with bounded attempts/time, exclusions and safe serialized provenance. Local operational controls include durable SQLite admission, canonical UUID buckets, bounded connection capacity, restart-safe cleanup obligations/confirmed-ID deltas, cache caps, owner-only verified backups and protected readiness. Targeted review findings were reproduced and repaired, including backup sidecars/canonical-path races and cleanup snapshot loss.

Latest full runner: 266 backend tests, 123 worker tests, 53 frontend tests passed; 17 passing checks, zero failed checks, four explicitly blocked markers. Nine real-isolation tests remain skipped. Actual local HTTP smoke verified hidden challenge/idempotency, honest unavailable results, export/delete and 429 backpressure with no provider calls or learner executions. Evidence: workspace `evidence/local-completion-20261114/full-check-final` and `http-smoke.json`. Drive is deferred by the user.

## Baseline actually observed

- Imported raw bytes: 278 present, all recorded SHA-256 checks passed. Five native handoff exports were zero bytes.
- Initial current Python pass: **10 failed, 95 passed, 9 skipped**. The concrete startup blocker was the application factory passing `settings` to a constructor that neither accepted it nor defined it.
- Initial frontend typecheck/tests/build passed; this did not establish backend integration.
- Read-only OpenAPI and TypeScript drift checks failed **before** any regeneration. Evidence: `../../evidence/claude-takeover-20261113/{openapi-baseline,typescript-baseline}.log`.
- After source/schema repairs, intentional maintenance regeneration was performed; read-only drift and the six mutation self-tests then passed.

## Defects addressed with reproductions

| New identifier | Defect / repaired behavior | Acceptance evidence |
|---|---|---|
| LOCAL-STARTUP | Speech settings constructor, configured budgets/endpoint | test_startup_settings.py |
| LOCAL-CONTRACT | Mounted session routes and DTOs missing from frozen contracts | OpenAPI --check; TS --check --self-test |
| LOCAL-LIFECYCLE | Capture confirmation/cancellation CAS; stale REST/WS publication; saves/spec transitions | test_learning_lifecycle.py; test_atomic_revision_publication.py |
| LOCAL-REPAIR | Retained prior failure; standalone verification/transfer; unavailable execution retry | test_learning_lifecycle.py; test_worker_deadline.py |
| LOCAL-REDACTION | Foreign verifier case hidden behind its own immutable prediction challenge across response/export/coaching paths | test_learning_lifecycle.py |
| LOCAL-VOICE-USAGE | Unknown post-dispatch STT/TTS errors and post-upgrade WS schema errors retain uncertain usage | test_startup_settings.py; test_speech_takeover.py |
| LOCAL-WORKBENCH | Full-revision restore, source edits/cancellation, discriminated claims, verify feedback, trace pointers | frontend lifecycle/sessionLifecycle/API tests |
| LOCAL-PACKAGING | Shared host/broker IPC; actual runsc bundle; immutable image identity; image dependencies and branding input | test_deployment_packaging.py; test_check_runner.py |
| LOCAL-CHECKS | Reject zero/skipped-only tests and mocked/empty P8 success; truthful blocked status; full redacted logs | test_check_runner.py |
| LOCAL-SNAPSHOT | Exclude keys, recordings, cache/runtime data and SQLite sidecars | test_check_runner.py |

Original R1–R9 names remain unchanged in test_r1_to_r9_regressions.py. No aliases to unseen Gemini findings are invented.

## Real execution limits

Protocol/state doubles are labelled as such and do not execute learner programs. Local browser inspection observed session creation, immutable hidden input, edited prediction confirmation, and honest EXECUTION_UNAVAILABLE/NOT_EVALUATED with retry available. It did **not** prove successful sandbox execution, trace production, repair success or a completed transfer checkpoint.

One dispatcher-controlled live Gnani TTS request received HTTP 401. It stopped immediately: zero STT attempts and zero retries. Provider ID/confidence are unknown; no accuracy or successful roundtrip claim is made.

Linux/runsc acceptance and P8 code evaluation remain blocked. Coverage/wheel build tools were absent; installing additional chosen tools was denied. Eighty-percent coverage and a built wheel are not certified. Final check logs and their structured results are the authoritative current counts.

## Remaining scope

A successful real-gVisor central journey, live REST/WS/SSE and real human speech/barge-in measurements, missing native exports/Drive concurrency/read-back, full 24-clip evaluation/user study, complete operations acceptance and HTTPS deployment must still be completed. The latest generation implementation uses the shared, pinned Hypothesis engine; local metadata and budget tests do not establish real sandbox acceptance. These requirements are retained, not silently removed.
