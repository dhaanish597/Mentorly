# Final build status — 2026-11-15 recovery

## A. Executive summary
The recurring **Not Found / Retry** symptom was traced to healthy-but-stale backend processes missing current routes and missing Vite preview proxy configuration. Local startup now reloads source; dev and built preview share one API proxy; missing-route errors are actionable without replaying writes.

Previous platform work was preserved and extended. Progress links completed interviews to a dedicated authenticated report endpoint that reads only persisted reports. It does not finalize expired active interviews, create sessions/workspaces, activate media, or overwrite another interview's resume reference. Normalized external-link and dot-identifier cases were repaired.

**This is a verified recovery checkpoint, not completion of the entire production-platform mission.**

## B. All 40 requirements
`TESTED` means the described subset passed automated checks, not full provider/browser acceptance. No entire speech module/language combination is newly LIVE_VERIFIED from fixtures or historical synthetic audio.

| ID | Requirement | Status | Evidence / limitation |
|---|---|---|---|
| F01 | Structured DSA curriculum | TESTED | 31 authored lessons, prerequisites and objective practice; not exhaustive depth. |
| F02 | Complete CS path | NOT_IMPLEMENTED | 30 functioning lessons cover the tracks; exhaustive depth/multiple assessments unfinished. |
| F03 | Structured aptitude curriculum | TESTED | 24 lessons and checked arithmetic; comprehensive timed banks unfinished. |
| F04 | Coherent HLD/LLD curriculum | TESTED | 15 lessons/eight HLD cases; existing 12 Studio scenarios, not a canvas for every lesson. |
| F05 | Persistent curriculum progress | TESTED | SQLite and real HTTP lesson/progress checks; no cross-device account recovery. |
| F06 | Shared DSA voice | TESTED | Lifecycle fixtures and historical introduction audio; natural mic exchange unverified. |
| F07 | Shared CS voice | TESTED | Shared lesson/module voice fixtures; no physical mic acceptance. |
| F08 | Shared design voice | TESTED | Studio transport/preferences tests; no new full live verbal design discussion. |
| F09 | Shared codebase voice | TESTED | Grounded Redrive message binding/common transport fixtures. |
| F10 | Aptitude voice workflows | TESTED | Common lesson adapter fixtures; no human acoustic-quality proof. |
| F11 | Configurable Gnani languages | TESTED | Ten documented locales, three English code-mixes, 13 voices; not all-language account/quality certification. |
| F12 | Languages affect actual speech | BLOCKED | Request/preference propagation tested; translated mentoring/all-language genuine audio acceptance unfinished. |
| F13 | Voice affects synthesis | TESTED | Preference/request compatibility fixtures; not 13 live samples. |
| F14 | Organized settings | TESTED | Six categories and component tests; profile/interview defaults incomplete. |
| F15 | Cross-module persisted settings | TESTED | Device stores/subscriptions and DSA/Studio/module tests. |
| F16 | Real homepage metrics | TESTED | Workspace events; local drafts separate; fake personalization retired. |
| F17 | Real recommendations | TESTED | Prerequisite/resume/mistake/interview rules; complete historical analytics absent. |
| F18 | Verified achievements | TESTED | Owned source-event awards, duplicate/deletion tests and HTTP completion flow. |
| F19 | Interactive design practice | TESTED | Editable existing graphs/requirements/modeled checks; no new visual certification. |
| F20 | Voice codebase learning | TESTED | Common transport/grounded-message fixtures; no new full live conversation. |
| F21 | Zero-knowledge Redrive | TESTED | Source-aware plans/checkpoints/revisits; bounded teaching depth. |
| F22 | Source-grounded answers | TESTED | Exact files/lines/hashes and missing-source/injection tests; static edges do not establish runtime intent. |
| F23 | Adaptive defense | TESTED | Grounded repository phases/followups; generic interview defense is not repository-grounded. |
| F24 | DSA interviews | BLOCKED | Flow/code snapshots tested; worker adapter and executable grading acceptance absent. |
| F25 | CS interviews | TESTED | Neutral followups/epochs/timer/reports; semantic correctness explicitly unassessed. |
| F26 | Design interviews | TESTED | Structured scenarios/followups/reports; templates do not prove architecture correctness. |
| F27 | Evidence-backed report rubrics | TESTED | Response excerpts/indicators/abstentions; immutable report lookup and recovery. |
| F28 | Camera nonblocking | TESTED | Camera-off/optional-preview fixtures; hardware permission behavior unverified. |
| F29 | DSA conversation panel | TESTED | Existing active conversation/editor/secondary evidence regressions. |
| F30 | Active speaker focus | TESTED | Speaker-transition fixtures; no new browser playback demonstration. |
| F31 | Progressive responsive transcript | TESTED | Reveal/reduced-motion fixtures and historical layouts. |
| F32 | Transcript follows playback | TESTED | Playback-clock tests; estimated timing, not provider word alignment. |
| F33 | Cancellation/interruption | TESTED | Epoch/late-result/capture/playback cleanup fixtures; physical-device acceptance missing. |
| F34 | Coding verification preserved | BLOCKED | Offline deterministic regression passes; Linux/Docker/runsc live acceptance unavailable, public arbitrary code disabled. |
| F35 | All primary routes tested | BLOCKED | Component/API tests and HTTP delivery pass; fresh full browser/cross-browser journeys unavailable. |
| F36 | No fabricated success anywhere | NOT_IMPLEMENTED | Active fakes retired/README corrected; no exhaustive guarantee over every legacy/reference surface. |
| F37 | Backend/frontend builds | TESTED | Backend suite/compileall; frontend typecheck/production build pass. |
| F38 | Safe migrations | TESTED | SQLite additive/repeatability/ownership/deletion tests; no wipe. PostgreSQL separately blocked. |
| F39 | No critical unresolved regressions | BLOCKED | Combined suites/scoped reviews pass; old 8020/8026 processes remain stale until restarted, release gates open. |
| F40 | Accurate documentation | TESTED | Audit/tracker/report/matrix distinguish source, fixtures, HTTP, prior provider evidence and blockers. |

## C. Architecture changes
- `scripts/start_local.py`: reload default, explicit `--no-reload`, same environment/database and loopback binding.
- `frontend/vite.config.ts`: one dev/preview API proxy; default host validation restored. Not a production reverse-proxy deployment.
- `services/apiErrors.ts`: safe error envelopes, explicit missing routes, no mutation replay.
- `interviews/routes.py`: authenticated `GET /api/v1/interviews/reports/{session_id}`, read transaction and stored validated Report, no expiry/completion hook.
- `InterviewReportRoute.tsx`: existing-workspace-only read view, stale-result fencing, no media or resume changes.
- `learningApi.ts`/`ProgressPage.tsx`: bounded report references, encoded internal links, normalized URL validation and standalone-dot rejection.
- OpenAPI/TypeScript contracts regenerated. No recovery database migration required.

## D. Test results and commands
**Backend/worker: 1276 passed, 14 skipped, 5 warnings; 88% app coverage; 67.59 seconds.**
**Frontend: 734 passed in 47 suites; 88.80% statements, 83.47% branches, 87.68% functions, 95.24% lines.**
Typecheck/build/contracts/canonical lint and additional explicit-parser lint pass. Secret scan: zero violations. Schema self-test detected six mutations, zero drift over 27 enums/61 interfaces/one union. Startup/API scripts: 23 tests, 94.44% scoped coverage. Dedicated report route: 100% statement/branch coverage.

Skips: five PostgreSQL integrations lack a dedicated DSN; eight genuine gVisor tests need Linux/Docker/runsc; one live acceptance requires supported-host opt-in. No skip counts as a pass.

HTTP via Vite: 17 initial integration checks plus 12 final read-only report checks. Three newly created QA workspaces were deleted. This is not browser/media/provider acceptance.

Evidence: [frontend](../../evidence/backend-regression-20261115/final-frontend-verified.log), [backend](../../evidence/backend-regression-20261115/final-security-repaired-pytest.log), [final report HTTP](../../evidence/backend-regression-20261115/http-readonly-report-endpoint.json), [initial HTTP](../../evidence/backend-regression-20261115/http-report-recovery.json).

Commands from repository root:
```bash
PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python -m pytest implementation/backend/tests implementation/exec_worker/tests -q -rs --cov=implementation/backend/app --cov-report=term
```
```bash
npm --prefix implementation/frontend test -- --coverage
```
```bash
npm --prefix implementation/frontend run typecheck
```
```bash
npm --prefix implementation/frontend run lint -- --ext .ts,.tsx --parser @typescript-eslint/parser dev vite.config.ts
```
```bash
npm --prefix implementation/frontend run build
```
```bash
PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python implementation/backend/scripts/export_openapi.py --check
```
```bash
npm --prefix implementation/frontend run contracts:check
```
```bash
PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python implementation/scripts/check_schema_drift.py --check --self-test
```
```bash
.venv-takeover/bin/python implementation/scripts/check_secrets.py
```

RED failures were observed before repairs. Initial script coverage of 79% was raised with CLI/boundary tests, not a lowered threshold. Scoped code/security/React/Python/TypeScript review findings were fixed, not waived. Existing React act/dependency/deprecation warnings and large Monaco bundle remain documented.

## E. Gnani verification
No new provider calls in recovery. [Prior smoke](GNANI_PROVIDER_SMOKE.json): Prisma v3 REST English/codemix/WS, Timbre v3 SSE/WAV/cache; four physical calls, zero retries, 63 TTS characters/12 STT seconds using synthesized English. Native-language quality, physical microphone behavior and credit balance remain unverified. Historical lesson/DSA audio does not prove all modules/languages live.

## F. UI verification
Progress/report component tests cover query/history navigation, retries, invalid/missing/foreign references, stale results and no mutations/media. Both active URLs passed HTTP page delivery. Fresh visual QA was blocked by other-chat server-slot ownership and disabled Browser attachment; a later attempt hit classifier timeout. No manual user check was substituted or claimed complete.

## G. Important changed files
Local startup/API checker/tests; API-error helper/client/workspace transport; Vite/dev tests; report route/API and progress/parser; interview router/integration tests; dev-only Node typings/String library types; generated contracts; README and audit/tracker/test/final documents. Existing expansion/deployment changes preserved.

## H. Git
Branch `engineering/full-product-integration-20261115`; existing checkpoints `5b48f30`, `3604fd8`, HEAD `54c0a11`. No new commit/push/history rewrite/publication/submission in recovery. Working tree holds previous work and these uncommitted repairs; no reset or clean.

## I. Remaining limitations
- Old direct 8020/8026 backends need controlled restart. Active web URLs 5186/5187 pass route diagnostics; do not switch primary workspace databases to hide missing sessions.
- Browser and physical microphone/camera acceptance unavailable; no Safari/Firefox/Lighthouse certification.
- Live worker acceptance needs authorized Linux/Docker/runsc; PostgreSQL needs a dedicated test DSN.
- Full native UI/content translation, multilingual generative teaching/native-speaker evaluation unfinished.
- Exhaustive/timed/multi-question curricula, semantic mastery, full account/history analytics, voice/device previews and interview defaults unfinished.
- Generic defense differs from grounded repository defense; DSA interview snapshots lack worker evidence.
- Lazy Monaco approximately 721 KB gzip causes a nonblocking bundle warning.
- Config protection denied persisting broader lint patterns. No bypass: unchanged canonical lint plus read-only explicit-parser full-scope lint passed.

## J. Run this checkout
From `/Users/dhaanish/Desktop/VIVA`, using the installed environment and existing private backend `.env`:
```bash
.venv-takeover/bin/python implementation/scripts/start_local.py --env-file .env --port 8000
```
In another terminal:
```bash
npm --prefix implementation/frontend run dev
```
Open `http://localhost:5173`; reload is enabled. Fresh dependency setup is in README. Read-only diagnosis of the active app:
```bash
.venv-takeover/bin/python implementation/scripts/check_local_api.py --base-url http://127.0.0.1:5187
```
`--preview` intentionally uses credential-free isolated data, not genuine Gnani. Never put private keys in VITE variables.

## K. Required next work
Resolve environmental release gates and continue the unfinished original features. Preserve stable source and database identity; do not publish/deploy/submit this partial expansion as fully accepted. No infrastructure, permissions or publication were silently provisioned.
