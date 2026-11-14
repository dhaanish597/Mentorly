# Local operations runbook

**Last updated:** 2026-11-14. **Overall IN_PROGRESS.** Local controls are not production capacity, deployed isolation or legal-compliance certification.

## Runtime refresh and deliberate startup

**Final runtime refresh is BLOCKED_TOOL.** Existing http://127.0.0.1:5180/library uses an earlier-loaded backend. Browser observations precede final cache, HTTP freshness guard, per-message Replay and toolchain patches. The browser classifier outage prevented stopping/restarting services or clearing mobile viewport. Do not claim the running backend contains final source. User should stop only owned previews on 8020/5180, or wait for tool recovery, then relaunch and validate.

Use one coordinator on loopback 8020 and workbench on 5180. [ACCOUNT_HANDOFF.md](ACCOUNT_HANDOFF.md) gives exact absolute commands. `implementation/scripts/start_local.py --preview --port 8020` strips provider/operator/worker credentials, selects deterministic coaching, disables learner execution and isolates storage under `data/credential-free-preview`. The alternative `--env-file /Users/dhaanish/Desktop/VIVA/.env --port 8020` explicitly selects server-side configuration; startup itself makes no provider calls. Do not run competing coordinators or mix live/preview caches, databases or ledgers. Launch names are `vcc-expanded-coordinator` (credential-free) and `vcc-expanded-live-coordinator`; live browser QA storage is `data/live-browser-qa`.

Vite requires explicit `VCC_PREVIEW_API_TARGET=http://127.0.0.1:8020`; otherwise its proxy defaults to 8000. Direct live startup must prefix the public `VCC_CORS_ORIGINS=http://localhost:5180,http://127.0.0.1:5180` override so WebSocket origins match5180 even if private `.env` still names5173; the credential-free preview helper already sets5180. No secret values are passed on the command line. File-authoritative canonical credentials prevent ambient wrong-account/alias fallback; blanks/placeholders reject use. Preserve `.env` bytes/0600 and do not expose its contents, CLI key values, frontend secrets or interpolated Compose output.

Standard Groq startup requires private `VCC_GROQ_API_KEY`, `VCC_LLM_MODEL`, `VCC_LLM_PROVIDER=groq`; key/model are currently missing. Live-QA forced deterministic mode is not model acceptance. Current fallback is honest deterministic/no Groq call. No authorized Linux/runsc host, saved SSH target or local Docker daemon: custom execution stays disabled, without host/ordinary-Docker/AST-filter fallback.

## Request and connection limits

One coordinator is required for the account-wide speech dispatcher and process-local connection capacity. Defaults: 60s window;180 requests/direct peer,120/authenticated session,900 globally,six session creations/peer,32 in-flight HTTP/WS connections. SQLite counters are transactionally shared and survive restart. Canonical UUID spellings share a session bucket; invalid credentials cannot exhaust a victim bucket. Arbitrary forwarding headers are ignored. Trust only an explicitly configured private reverse proxy.

Exhaustion returns429 RATE_LIMITED with Retry-After; capacity/database unavailability returns explicit503 recovery responses. Caps do not establish provider tariffs or guaranteed availability.

## Speech cache economy / replay freshness

Server-owned generic intro/test audio can share **public bytes only**, keyed by public scope, version, language, voice and model. Two-session/one-mocked-TTS behavior is tested. Do not place caller-controlled or personalized text in this cache. Personalized entries remain session-scoped; private deletion preserves only generic public bytes. Public audio caching never permits hidden learner outputs or unpublished coaching facts to bypass authorization.

Durable HTTP speech idempotency replay checks revision freshness before returning audio bytes. Same key/body after code change is rejected with409/zero synthesis;28 tests and narrow review verified this boundary. Full artifact/revision/hint-keyed per-message Replay uses cached bytes without additional TTS; late acknowledgements cannot advance older hints. **Final two replay-cache bounds/error-eviction fixes remained in finalization at the consolidated-summary cutoff.** Validate/rerun after source changes; recorded suite is not automatically evidence for subsequent edits.

Provider work stopped. Exact cumulative usage: **11 authorized calls,373 TTS characters,27.76 STT seconds; plus2 unintended dummy-key401 tests=13 total attempts**. Initial8 calls189 chars19.36s; approved second3 calls: synthetic Tanglish2(122 chars8.4s STT) and browser Test Voice1(62 chars). Dummy requests were stopped/fixed MockTransport. Local replay adds zero requests. No additional provider consumption authorized. Tariff conversion/remaining credit remain unknown; post-dispatch unknown failures retain uncertain reservations. See [GNANI_CAPABILITIES.md](GNANI_CAPABILITIES.md).

## Retention and private cache cleanup

Expired sessions are swept in bounded batches (100 every60s by default). Tombstoning atomically records payload-free cleanup obligations before deleting code, transcripts, challenges, artifacts, traces and jobs. Broker IDs/audio cleanup survive restart. Completion subtracts only explicitly confirmed IDs from the current durable list, preserving newly captured/unattempted work. File errors leave cleanup pending. Small tombstones/accounting metadata remain for late-response protection.

Tracked personalized audio is cancelled/awaited before cache eviction. Cache caps include age24h,total32MiB,entrycount1024; oversized completed audio can be delivered without disk caching. Entries are scoped and symlinks are not followed. Public generic bytes are not personalized session records. External provider retention/historical backups are outside local deletion guarantees. No legal certification.

## Protected readiness

GET `/api/v1/ops/readiness` requires separate `VCC_OPERATIONS_TOKEN` Bearer header and is disabled without a valid token. No tokens in queries, frontend, CLI values, source or logs.

Readiness checks SQLite and accepted broker/runtime identity. The canary uses fixed trusted code/input through genuine accepted gVisor with bounded budgets; it does not accept caller code, create a marker, enable execution or prove adversarial isolation. Without accepted runsc evidence it is NOT_RUN/readiness BLOCKED_EXTERNAL. Separate genuine speech protocol evidence exists but does not certify human quality or capacity; readiness does not call speech. `run_canary=false` is not full READY. Browser/tool outage is a separate BLOCKED_TOOL runtime-refresh condition.

## Private verified backup/restore

From `/Users/dhaanish/Desktop/VIVA`, use a new owner-only directory outside source. Existing unsafe storage is refused.

```bash
mkdir -m 700 -p data/backups
PYTHONPATH=implementation/backend:implementation ./.venv-takeover/bin/python -m backend.app.operations.backup backup --source data/vcc.db --destination data/backups/checkpoint.sqlite3
PYTHONPATH=implementation/backend:implementation ./.venv-takeover/bin/python -m backend.app.operations.backup verify --source data/backups/checkpoint.sqlite3
PYTHONPATH=implementation/backend:implementation ./.venv-takeover/bin/python -m backend.app.operations.backup restore --source data/backups/checkpoint.sqlite3 --destination data/backups/restored.sqlite3
```

SQLite online backup includes committed WAL. Integrity,foreign keys,current migration checksums verified. Destinations/-journal/-wal/-shm must not exist,including dangling symlinks. Lexical/resolved ancestry trusted; owner-only canonical staging publishes atomically without overwrite; files0600. Never overwrite a live database or change its configured path implicitly.

Restore to a new inactive path,inspect,then explicitly restart with that `VCC_DATABASE_PATH`. Match application migration identities; back up with the running version before upgrades and stage cross-version migrations separately. Private backups require separate retention and never belong in source checkpoints or these docs.

## Consolidated checks / coverage / packaging

Workspace `evidence/workspace-expansion-20261114/final-checkpoint-checks/`: **503 backend PASS,207 worker PASS,120 frontend PASS,9 genuine gVisor/trace/execution SKIPS;17 PASS checks,0 FAIL,4 omitted/external markers**. Typecheck/build/drift/secrets/archive pass. Credential-free and omitted-live markers are deliberate; actual isolation/code evaluation remains blocked.

Python aggregate statement coverage **81.4403149% (7034/8637)**; frontend **81.05% statements(1703/2101),88.53% lines,77.29% branches,74.00% functions**. Both statement thresholds met,not all metrics. Older under-80/mapper snapshots superseded,not averaged; no module exclusions/authored-source execution to inflate coverage. Missing accepted runsc behavior/coverage remains partial.

Node24.21/Vite6.4.6/Vitest+coverage4.1.12/React plugin4.7.0/DOMPurify3.4.17;React18/Monaco0.57 unchanged. Final `npm-audit-final.json` zero all severities/empty vulnerabilities; earlier advisories superseded in this snapshot,not a future guarantee. Reviewed compatible updates/no forced major transitive override. Monaco chunk warning remains. No supplied completed Python registry-audit result claimed.

Wheel-final built and isolated installed-wheel HTTP catalog31 passed with explicit external branding/no repository module-path fallback/provider0/learner0. This is local packaging/import/HTTP evidence,not deployed isolation,capacity or rollback acceptance.

## Remaining evaluation / local-only boundary

No physical human mic/speaker check or study. Browser3.84s WebAudio/clock completion and automated1.1ms source.stop/6.7ms ended are debug software observations,not NFR benchmark/physical audible/foreground guarantee. Human preparation24 clip slots0 recordings,4 speaker slots0 consent;6–8 classmates still needed. Private evaluation validator/freeze procedure in existing `implementation/evaluation/README.md`; no synthetic replacement.

Full WCAG/browser/hardware/latency,accepted Linuxhost/TLS,deployed capacity/evaluator arrangements,latest runtime refresh and last2Replay validation remain open. Same-model reviews not Codex audit. Parent owns code/evidence/browser/checkpoint; expected future local checkpointmanifest not created by this docs pass. Historical manifests remain historical. No Drive/public publication,git commit/push,paid provisioning,sharing change or submission. Exclude secrets,DB/backups/sidecars,audio/cache,consent/identity mappings and private transcripts from docs/source archives.
