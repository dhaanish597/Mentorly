# Audit repairs and Astra verification status

15 November 2026. Implementation and local verification are complete in `codex/viva-audit-remediation` at `/Users/dhaanish/.codex/worktrees/viva-audit-remediation/VIVA`. Integration and external deployment acceptance remain pending. No commit, push, deployment, production migration, live provider request or microphone permission was performed by this remediation. The source and deployment checkouts were not edited.

## FIX-by-FIX result

| Requirement | Implemented and locally verified | External limit |
|---|---|---|
| FIX-01 | Evidence-grounded semantic review with exact citations, answer/context hashes, provenance, aggregate consistency, neutral follow-ups and end-only interview debrief | Live semantic quality and effectiveness not assessed; absent provider remains unassessed |
| FIX-02 | Stable objective option IDs, separate optional explanation review, explicitly authored numeric/boolean/enumeration contracts, immutable snapshots and objective credit preservation | Model prose never grants objective completion or mastery |
| FIX-03 | Explicit model readiness/error states, bounded deadlines, app-selected settings, shared durable legacy model-call budgets and visible honest feedback | No live provider success or capacity claimed; uncertain calls stay charged/occupied |
| FIX-04 | All 13 language modes persisted and usable; requested/verified concurrency settings and shared fenced account admission across REST/SSE/WS/module calls | Effective default remains one; live language quality and higher entitlement not verified |
| FIX-05 | Central trusted GitHub/GitLab archive adapters, nested GitLab namespaces and ZIP fallback, retaining pinned public TLS/DNS and archive protections | No arbitrary host, private credentials or unverified extra provider support |
| FIX-06 | Canonical backend8020/frontend5173, validated overrides, matching loopback CORS/proxy, redacted doctor; actual isolated launch on8137/5273 checked | Production routing uses explicit API origin/same-origin proxy, not Vite |
| FIX-07 | Explicit permission-validated env files, authoritative selected DB URL, blank DB URL normalized, credential-free preview strips credentials/database/cloud settings | Ambient env-file discovery remains disabled |
| FIX-08 | Scoped validated atomic WAV cache; read/write outages are cache misses and valid synthesis can still be delivered | Cache is disposable; no durable object cache added |
| FIX-09 | High-entropy opt-in workspace recovery, hashed credentials, rotation/revocation/expiry, durable attempt limits, on-demand DSA capability restoration, private archives and versioned device drafts | Losing both local state and recovery credential remains unrecoverable; no account identity is invented |
| FIX-10 | Actual PostgreSQL application runtime/schema/UOW, HTTP parity, atomic admission/idempotency, shared leases, fenced maintenance, stale-import recovery and private reconciliation/cutover tooling | Writes retain serialized semantics; cloud-worker lifetime, production cutover and Linux execution acceptance remain separate |

Deletion and retention tombstone owned linked DSA records in the same transaction and preserve durable cleanup obligations. Recovery restores selected sessions on demand rather than exhausting rate limits by rotating every session. Cache loss is not authoritative progress loss. PostgreSQL never silently falls back to SQLite.

## Astra result

The left panel now contains Astra and actual voice controls. The right defaults to a real chronological transcript. Full mentor text appears during playback; history has avatars, roles, timestamps, stable identities, explicit interim/draft states, replay deduplication and independent scrolling. Identical new drafts remain distinct from earlier sent messages. Evidence and Session become available only after genuine execution actions; session, code hash and code version bind evidence to the current revision. A new edit cannot reuse old verification as current.

Verified root cause: raw microphone RMS >=0.02 invoked speech activity and then `stopAudioPlayback`, while the drained microphone graph stayed active during TTS. Fan/echo/spikes could therefore stop mentor audio. Capture now closes before provider submission and playback. Stop Audio aborts pending audio and stops current playback without cancelling the learning turn; Cancel turn remains separate. Epoch/session/turn fences reject late responses, chunks, recorder disposal and stale execution results. Playback completion is independent of server TTS completion.

A conservative 20-ms activity heuristic uses band/envelope variation, adaptive ambient estimation and sustained activity rather than raw volume. Browser processing constraints are requested only when supported; actual enabled/disabled/unreported settings are visible. The 10-second quiet timer arms only after accepted speech-like activity; manual Send Voice and timer/button deduplication remain. Automatic full-duplex intentional barge-in is not claimed. Uninterrupted half-duplex playback with explicit Stop Audio is the safe fallback.

Independent review found and fixed aggregate semantic consistency, recovery request exhaustion, a PostgreSQL JSON comparison, transcript draft identity and transcript crowding. Final storage, provider fixture and frontend reviews report zero remaining findings. Browser review measured a former22px transcript log and verified the corrected usable scrolling area; this was not dismissed because component tests passed.

## Final commands and observed results

Commands below ran in the isolated `implementation` directory, except frontend commands ran in `implementation/frontend`. Python runtime: `/Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python` (3.11.17). Browser frontend/backend ports were5273/8137, separate from deployment processes.

| Check | Observed result | Evidence |
|---|---|---|
| `PYTHONPATH=backend:. python -m pytest backend/tests exec_worker/tests -q -rfs` | **1380 passed,114 skipped,5 warnings**,53.74s | `backend-final.log` |
| All actual `test_postgres_*.py` via private disposable PG16 cluster, psycopg3.3.9 | **105 passed,4 warnings**,34.56s | `postgres-final.log`, `postgres-test-runner.py` |
| `NODE_OPTIONS=--no-experimental-webstorage npm test -- --reporter=dot` | **930 passed in58 test files**,18.02s | `frontend-final.log` |
| `npm run typecheck`, `npm run lint`, `npm run build`, `npm run contracts:check` | Passed; existing Monaco chunk-size warning | `quality-checks.md` |
| OpenAPI `--check`; schema `--check --self-test` | Passed; zero drift across27 enums/61 interfaces/1 union;6 mutations rejected | `quality-checks.md` |
| `scripts/check_secrets.py`; `git diff --check`; compileall | Passed;0 secret violations | `quality-checks.md` |
| Archive sentinel and minimal runner COPY import | Passed; import is not execution/isolation proof | `quality-checks.md` |
| Speech ablation/AST latency | Offline `overall_pass=true`,3 scripted utterances; not live speech accuracy | `speech-ablation-final.log` |
| `scripts/smoke_gnani.py --allow-blocked` | **BLOCKED_EXTERNAL**, live provider not requested | `quality-checks.md` |
| Wheel packaging + scoped storage Ruff/dialect | Passed;2 dialect tests | `storage-wheel.log`, review evidence |

The114 aggregate skips comprise105 PostgreSQL tests run separately and9 genuine Linux/gVisor cases unavailable on Darwin. PostgreSQL skips are not counted as passes in the aggregate. Existing Python namespace/deprecation/ZIP warnings and React act warnings remain; frontend lint itself has zero warnings. The full project runner's duplicated checks were run individually; no claim is made that its external execution gate passed.

## Browser and audio evidence

Actual local preview checked: correct objective answer completed the lesson while optional explanation stayed UNASSESSED/MODEL_DISABLED; workspace recovery settings rendered; real typed learner text and deterministic mentor guidance appeared before code submission; Evidence/Session were absent initially. Code submission returned EXECUTION_UNAVAILABLE honestly. Returning to Transcript preserved both messages. The browser did not call live providers or request microphone permission.

Desktop1440x1000, mobile390x844 and short desktop1440x768 were checked. Mobile document scroll width equalled390px; short desktop scroll width equalled1440px and document height976px allowed vertical access to the518px result pane. The conversation log was182px after correction and has a160px minimum. Screenshots: `astra-desktop.jpg` and `astra-mobile.jpg`.

Deterministic tests cover stationary fan/DC/high-frequency noise, short bursts/spikes, sustained modulated activity, fan-plus-activity, repeated text, view/history restoration, manual/timer submission races, capture shutdown, stale callback cancellation and explicit Stop Audio. Existing WAV fixtures are explicitly synthesized speech through a virtual microphone: offline detector acceptance was220/197 activity frames, and219/193 after adding synthetic fan noise. These are neither consented human microphone recordings nor measurements of live recognition quality.

Manual acceptance target: zero automatic playback cancellations during each consented60-second fan, AC, typing, transient and speaker-echo scenario; exactly one submission after a genuine utterance and10seconds of quiet; explicit Stop Audio works and no stale chunk resumes. Those real hardware/provider scenarios have **not been run**. The heuristic does not perfectly distinguish environmental audio; the manual control remains available.

## Integration and remaining gates

Use `REMEDIATION_INTEGRATION_HANDOFF.md` and the task-only bundle with exact base/current hashes. Do not apply the full Git diff against HEAD or replace the deployment checkout with this snapshot. Tests must run again after conflict resolution with current deployment edits.

Remaining external gates: genuine microphone/Chrome/Safari behavior, live Gnani/model/language acceptance, verified entitlement, Linux/gVisor custom execution, deployed distributed worker lifetimes and production cutover. Custom execution stays disabled until actual isolation acceptance. No weekend deployment was scheduled or executed by this task.
