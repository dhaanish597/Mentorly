# Implementation status

**Last updated:** 2026-11-14. **Overall `IN_PROGRESS` — local candidate, not complete, not an accepted P0–P9 release.**

Authority: `/Users/dhaanish/Desktop/VIVA/IMPLEMENTATION_PLAN.md` v2.0.0, FR-01–22/NFR-01–07 and §12.3, supplemented by the user's explicit exercise/UI/voice expansion. Original three exercises/four specs are preserved minimum scope, not the catalog ceiling. See [FEATURE_COVERAGE.md](FEATURE_COVERAGE.md) and [DECISIONS.md](DECISIONS.md).

## Consolidated final local checks

Authoritative recorded suite: workspace `evidence/workspace-expansion-20261114/final-checkpoint-checks/{full_check_results.json,check_results.json,TEST_LOGS.txt}`.

- **503 backend PASS, 207 worker PASS, 120 frontend PASS; 9 genuine gVisor/trace/execution SKIPS.** Subset checks overlap main suites and are not extra distinct tests.
- **17 checks PASS, 0 FAIL, 4 omitted/external markers.** Frontend typecheck/build, contract drift, secret hygiene and archive exclusion pass.
- Markers: credential-free `smoke_without_key`, omitted `live_gnani_smoke`, `live_gvisor_isolation_acceptance`, and runsc-only code evaluation. The first two are deliberate offline boundaries; separately authorized genuine provider success exists. Isolation/code evaluation remain actual blockers, not passes.
- Parse-only notebooks, minimal runner imports and protocol doubles do not execute learner programs. No real sandbox output/trace/repair/transfer acceptance is claimed.
- Final wheel built and passed an isolated installed-wheel HTTP catalog check for 31 problems using **explicit external branding configuration**, no repository module-path fallback, zero provider calls and zero learner executions. This is packaging/import/HTTP evidence, not deployed isolation or full deployment acceptance.

### Measured coverage — do not average older mappers

| Area / metric | Final measured coverage | >=80% statement target |
|---|---|---|
| Python aggregate statements | **81.4403149% — 7034/8637** | Met |
| Frontend statements | **81.05% — 1703/2101** | Met |
| Frontend lines | **88.53%** | Not the statement denominator |
| Frontend branches | **77.29%** | Below 80% |
| Frontend functions | **74.00%** | Below 80% |

Evidence: workspace `evidence/workspace-expansion-20261114/verified-coverage.json` and `frontend-coverage-verified/coverage-summary.json`. Both statement thresholds are met; **not all coverage metrics**. Missing real-runsc coverage/behavior acceptance remains partial. Earlier Python 78.5573% (6763/8609), intermediate 81.4613% (7013/8609), and earlier frontend 82.42%/Vitest-4 mapper results are historical, superseded observations, not values to average or rewrite. Additional tests did not exclude modules or execute authored source fixtures.

### Toolchain / dependency snapshot

Node 24.21; Vite 6.4.6; Vitest and coverage 4.1.12; React plugin 4.7.0; DOMPurify 3.4.17. React 18 and Monaco 0.57 remain unchanged. Scoped Monaco sanitizer override installed and reviewed compatible development-tool updates passed typecheck, 120 frontend tests and production build. `npm-audit-final.json` records **zero advisories at every severity / empty vulnerabilities** in this snapshot, superseding earlier 12/4-critical and 10-dev-only snapshots. No forced major transitive override or universal future security guarantee. Monaco large-chunk warning remains. No completed registry-backed Python dependency-audit result is supplied by this summary; do not invent one.

## Phase gates

| Phase / task | Correct definition | Current status | Remaining acceptance |
|---|---|---|---|
| P0 / T-01 | Foundations/contracts | VERIFIED (local subset) | Strict typed catalog/oracles/migrations/drift pass; no remote promotion |
| P1 / T-02 | Safe execution | IMPLEMENTED_UNVERIFIED / BLOCKED_EXTERNAL | Actual dedicated Linux/runsc adversarial/resource/cleanup acceptance |
| P2 / T-03 | Voice foundation | IMPLEMENTED_UNVERIFIED | Genuine REST/codemix/SSE protocol observed; human/device accuracy pending |
| P3 / T-04 | First end-to-end loop | IMPLEMENTED_UNVERIFIED | Hidden prediction/typed unavailable journeys observed; real sandbox loop blocked |
| P4 / T-05 | Full verification/learning | IMPLEMENTED_UNVERIFIED | Typed generation/shrink/replay/repair/transfer logic tested; actual runsc behavior pending |
| P5 / T-06 | Workbench/deterministic coaching | IMPLEMENTED_UNVERIFIED | 13 states, compact UI, chips/hints/restore; final patched-runtime browser refresh BLOCKED_TOOL |
| P6 / T-07 | Advanced voice/model | IMPLEMENTED_UNVERIFIED | REST/WS/SSE/WAV/cache and replay tests; model unconfigured, human/device/latency unverified |
| P7 / T-08 | Persistence/privacy/operations | IMPLEMENTED_UNVERIFIED | Admission/retention/backups/public-private cache/replay freshness tested; deployed capacity/evaluator arrangements pending |
| P8 / T-09 | Evaluation/hardening | BLOCKED_EXTERNAL | Statement targets met; runsc evaluation, four consenting speakers/24 clips and 6–8-classmate study absent |
| P9 / T-10 | Deploy/document | IMPLEMENTED_UNVERIFIED | Wheel/install/catalog/build docs pass locally; host/images/TLS/deployed rollback/final runtime acceptance pending |

## Expanded product and retained boundaries

**31 distinct original problems / 32 specs**; original `ex1_shortest_subarray`, `ex2_binary_search`, `ex3_max_product` and spec IDs preserved. Strict integer, boolean, string and flat scalar-list schema/comparison rejects bool/int aliasing and coercion. Generic validated catalog counts: **173 curated, 64 transfer, 626 generated cases; 31 examples, 31 known-bug sources, 31 alternative sources**. These are local data/oracle counts, not accepted runtime executions for all 31 problems; original code-evaluation corpus remains separate.

Trusted oracle/schema cases are validated. Final source fixtures are AST-only inert strings. Earlier 120 ordinary-subprocess authored-fixture checks were stopped/removed: **not isolation proof or accepted behavioral evidence**. No host Python/ordinary-Docker/AST-filter/RestrictedPython learner fallback.

Public generic intro/test audio caches only server-owned public bytes, keyed by scope/version/language/voice/model; two-session/one-mocked-TTS behavior tested. Personalized cache scope/deletion remains separate. Durable HTTP speech idempotency replay rejects stale revisions before returning bytes (28 tests and narrow review); same key/body after code change cannot bypass freshness. Per-message Replay is keyed by artifact/full revision/hint, cached replay adds zero TTS calls, and late acknowledgements cannot advance older hints. **The final two replay-cache bounds/error-eviction fixes were still being finalized at this summary cutoff; final validation/rerun after any source change remains required.** Do not silently extend the recorded suite to unrecorded later edits.

## Actual browser/provider evidence versus final runtime

Observed compact UI includes search/filter/bookmark/resume/URL drafts, mobile tabs/theme/reduced motion and sticky confirmation/mic/stop controls. At 1366×768 page 768px/editor 432px; at 1440×900 page 900px. Before/light/dark/mobile artifacts are retained under workspace `evidence/workspace-expansion-20261114/`. Actual boolean challenge journey kept answers hidden until deliberate confirmation, then displayed EXECUTION_UNAVAILABLE / prediction NOT_EVALUATED / zero curated/generated counts / no success badge; restore retained evidence. Draft switch/resume retained dirty code without stale results. These are unavailable-execution observations, not accepted code runs.

**Final source runtime refresh is BLOCKED_TOOL.** Browser evidence predates the final cache/guard/replay/toolchain patches. Existing `http://127.0.0.1:5180/library` uses an earlier-loaded backend; layout/core UI evidence does not certify latest backend source. Browser classifier outage prevented stopping/restarting services or clearing the mobile viewport. User must stop only owned 8020/5180 previews, or wait for service recovery, then relaunch deliberately and validate the final runtime. See [ACCOUNT_HANDOFF.md](ACCOUNT_HANDOFF.md).

Provider aggregate: **11 authorized calls, 373 TTS characters, 27.76 STT seconds; plus 2 unintended dummy-key 401 tests = 13 total attempts**, corrected to MockTransport. Synthetic Tanglish had 7/7 exact raw programming tokens but Tamil imperfection. Browser Test Voice used one genuine synthesis; later replay zero calls, 3.84s actual WebAudio completion, timed-debug source.stop 1.1ms/ended 6.7ms after click. This is not NFR benchmark or physical audible latency/foreground guarantee. No human mic/speaker check or study. See [GNANI_CAPABILITIES.md](GNANI_CAPABILITIES.md).

## Mandatory external/user actions

No local Docker daemon, no saved SSH targets and no authorized Linux/runsc host. Execution remains disabled. Groq key/model missing; deliberate private `.env` requires `VCC_GROQ_API_KEY`, `VCC_LLM_MODEL`, `VCC_LLM_PROVIDER=groq` for standard local startup, not live-QA forced deterministic mode. Current deterministic fallback makes no Groq call. Human evaluation manifest has **24 slots/zero recordings, four speaker slots/zero consent**, with 6–8 classmates still needed. Physical hardware, full browser/WCAG/latency matrix, deployed capacity/evaluator arrangements, accepted host/TLS and final runtime refresh remain open.

Same-model independent subagent reviews fixed known security/code/React findings; no Codex/cross-model audit claim. No Drive publication, git commit/push, public publish, paid provisioning or submission. Parent owns source/browser/evidence/checkpoints. Expected future local checkpoint `evidence/workspace-expansion-20261114/checkpoint/CHECKPOINT_MANIFEST.json` is not claimed created by this docs pass. Historical imports/checkpoints/401-only reports retain provenance, not current identity. No secrets/live DB/audio in docs or source archives.
