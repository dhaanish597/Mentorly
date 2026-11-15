# Engineering verification report — 2026-11-15

## Evidence rules
Unit/integration fixtures are not live provider or sandbox proofs. Objective completion is not mastery. Browser observations are actual app interactions but not a full cross-browser/accessibility/performance certification. This report is updated with final counts after all repair work settles.

## Baseline
Backend/worker:976 passed,9 skipped,89% statement coverage. Frontend:417 passed; typecheck,lint,build passed. Secret scan zero violations. Historical source restriction documents were not treated as current acceptance.

## Final recovery verification — 2026-11-15
- **Frontend: 734 passed across 47 suites**, 88.80% statements, 83.47% branches, 87.68% functions, 95.24% lines. Typecheck, lint, build and contract checks passed. Evidence: `evidence/backend-regression-20261115/final-frontend-verified.log` and corresponding final `*-verified.log` files.
- **Backend/worker: 1276 passed, 14 skipped, 5 warnings**, 88% app statement coverage; 67.59 seconds. Evidence: `evidence/backend-regression-20261115/final-security-repaired-pytest.log`.
- Skips: 5 PostgreSQL integrations lack a dedicated test DSN; 8 genuine gVisor tests require Linux/Docker/runsc; 1 live sandbox acceptance requires supported-host opt-in. No skipped test is treated as a pass.
- Local startup/route diagnostics: **23 passed; 94.44% scoped coverage**. API error/routing and report identifier tests observed RED failures before GREEN repairs. Final report route coverage: 100% of 67 statements and 6 branches.
- Report recovery: 210 scoped frontend cases passed three consecutive runs before the last six dot-identifier regressions; backend report lookup and immutable recovery tests pass. Final combined suites include all corrections.
- Actual HTTP through Vite 5187: **17 original integration checks + 12 dedicated read-only report checks**. Lesson completion, progress, report replay, second active interview, foreign/anonymous denial and cleanup verified. Three self-created QA workspaces deleted; no existing learner identity was used.
- Public JSON routes on 5186/5187 return 200; protected interview routes return expected unauthenticated 401, not missing-route 404. Direct stale 8020 correctly fails the new diagnostic despite health 200. Its process was not restarted.
- A config-protection hook refused persisting expanded lint patterns. It was not bypassed; canonical lint configuration remains unchanged. Additional read-only coverage passed with `npm --prefix implementation/frontend run lint -- --ext .ts,.tsx --parser @typescript-eslint/parser dev vite.config.ts`.
- Scoped general/security/React/Python/TypeScript reviews identified and repaired host validation, normalized external links, report-read expiry side effects and standalone dot identifiers. Reviews are scoped, not production certification.
- No new browser interaction or provider call in this recovery. Browser attachment reports disabled installation; server start was blocked by other-chat slots and later classifier availability. Prior browser/provider observations below are historical evidence only.

## Historical expansion checks (counts superseded by final recovery)
The following feature-level counts describe earlier checkpoints, not additional tests to sum into the final totals.
- Learning:100 authored lessons;41 runtime/catalog tests;45 additional independent arithmetic/trace tests;95% scoped coverage. Computed values use problem operands, fractions/combinatorics and independent traces, not answer-key self-comparison.
- Interviews:31 backend tests and45 frontend tests;99% backend/98% frontend line coverage. Workspace expiry/deletion-after-admission and late resume/reload races repaired.
- Repository learning:101 related backend tests,23 new Redrive tests,94% combined engine/router coverage;49 related frontend tests. Exact path/identifier and AST/tree-sitter call-citation regressions repaired. No imported repository execution.
- Common module voice:42 backend tests/93% coverage,15 frontend tests/98.48% lines. Provider cleanup and per-attempt recorder isolation tested; anonymous billed-use bounds survive deletion.
- Speech:231 backend tests/88% scoped coverage;113 related frontend tests. Locale/model/voice validation, physical-call accounting, retry/epoch/permission/cancel/WS framing and Studio preferences covered.
- Independent general/security/Python/React reviews found concrete defects; all confirmed findings are assigned repairs and re-verification. Final no-blocker verdict recorded only after the last App checks settle.

## Exact commands
From repository root:
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
npm --prefix implementation/frontend run lint
```
```bash
npm --prefix implementation/frontend run build
```
```bash
PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python implementation/backend/scripts/export_openapi.py --check
```
```bash
PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python implementation/scripts/check_schema_drift.py --check --self-test
```
```bash
npm --prefix implementation/frontend run contracts:check
```
```bash
.venv-takeover/bin/python implementation/scripts/check_secrets.py
```
Ruff and Black were installed in the project's existing virtual environment. Safe lint/import modernization and formatting were limited to new learning/interview/module-voice/Redrive modules; their final checks are recorded separately. Runtime dependencies were not broadly upgraded. Production `npm audit --omit=dev --json` reported zero advisories.

## Genuine Gnani protocol evidence
`GNANI_PROVIDER_SMOKE.json`: PASS; Prisma v3/Timbre v3;4 physical calls,zero retries,63 TTS chars,12seconds total STT uploads. Operations: SSE/WAV TTS, cache replay, English REST STT, Tamil-English codemix REST STT, WS STT. The same synthesized English clip supplied STT. No human Tamil/Tanglish or other-language quality test is implied.

Actual integrated browser lesson `/module-voice/lesson/.../tts` and DSA `/speech/introduction` returned200 with genuine provider audio and real playback/caption state. These do not prove acoustic accuracy, native microphone behavior, all voice/language quality, or provider credit balance. Exact final short WS boundary frame is mock-tested, not live provider-tested.

## Browser observations
Preview: frontend5187/backend8027, isolated development database. Actual browser actions:
- Loaded curriculum, opened DSA complexity lesson, started persisted practice, submitted wrong O(1) answer then correct O(n), received real feedback, refreshed and retained completion.
- Progress showed1 lesson,1 practice,2 answers,1 earned source-event badge, no mastery claim; next prerequisite-aware lessons linked correctly.
- Shared lesson voice returned200; DSA binary-search opening produced real introduction and correct active caption. Code/editor/evidence and mobile Coach/Results tabs remain distinct.
- Settings category navigation and native-language selectors rendered;375px and768px layouts and1440px desktop had no observed horizontal overflow.
- Studio selected a real rate-limiter scenario, created session, rendered editable graph, constraint progression and voice consent. Codebase imported a explicitly labeled curated source snapshot and generated a16-step beginner plan with exact source/line/hash references.
- Interview configuration exposed13 allowed language modes with camera absent/off; CS question received a typed answer, neutral acknowledgement and relevant follow-up without score/model-answer leakage. Explicit Finish persisted an end report.
- Browser screenshots captured curriculum, Studio and mobile DSA. Console inspection showed no errors in checked flows; aborted old catalog fetches during StrictMode/HMR were distinguished from HTTP failures.

Some page actions needed retries because controls were off-screen or a source refresh changed view state. No failed interaction was reported as successful. Natural microphone and camera permission hardware checks were not live verified; fixture tests cover them.

## Known release limitations
- Live arbitrary learner-code acceptance requires configured Linux/Docker/runsc; current public execution remains disabled. No unsafe fallback.
- Full native UI/content localization, generative multilingual tutoring, deep explanation correctness/mastery assessment and exhaustive curricula remain unfinished.
- New DSA interview snapshots are not wired to worker execution evidence; reports abstain from code correctness.
- Generic interview defense is not repository-grounded; grounded defense is the repository/Redrive path.
- Aggregate learning analytics do not yet unify every historic DSA/Studio/repository activity under an authenticated cross-device account.
- Test coverage percentages are coverage, not pedagogical quality or production security certification. Safari/Firefox, physical-device microphone/camera, calibrated native-speaker evaluation and Lighthouse were not completed.
- Lazy Monaco remains~720KB gzip, causing a build warning. Billing/tariff and external service quota balance remain unknown.
- Source branding/README changes from another writer were preserved and recorded; metadata tests use isolated branding fixtures.
