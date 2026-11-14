# Full product audit — 2026-11-15

## Source and measured baseline
Requested `/Users/dhaanish/Documents/VIVA` could not be resolved; attached actual repository is `/Users/dhaanish/Desktop/VIVA`. Branding remains VIVA. Branch `takeover/complete-coach` initially has no commits and all implementation files untracked. Existing changes preserved. Historical implementation/docs audits are architectural context only; this audit is referenced by IMPLEMENTATION_TRACKER and FINAL_BUILD_STATUS.

Stack: React 18/Vite 6/TypeScript, FastAPI/Pydantic, SQLite WAL/foreign keys/checksummed transactional migrations 0001–0013. Authentication is expiring workspace/session capabilities, not an account system.

Measured baseline: `PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python -m pytest implementation/backend/tests implementation/exec_worker/tests -q --cov=implementation/backend/app --cov-report=term`: **976 passed, 9 skipped, 89% backend coverage**. Frontend typecheck/test/lint/build: **417 tests passed, all commands passed**. Build warns about lazy Monaco bundle size. Secret scanner passes (zero violations). Skipped execution tests require Linux Docker/runsc; offline tests are not live isolation proof.

| Feature | Existing implementation | Working behavior | Defects | Missing components | Planned changes | Verification |
|---|---|---|---|---|---|---|
| DSA | 31 exercises/32 specs, revision/CAS, worker readiness gate, traces | Offline regression passes | Conversation coupled to audio; evidence dominates UI | Structured prerequisite lessons/interview | Retain deterministic evidence; add curriculum/conversation | Baseline tested; browser pending |
| CS fundamentals | Static path descriptions | No dedicated lesson runtime | Unresolved challenge IDs | Authored OS/DBMS/CN/OOP/architecture/SE tracks | Shared versioned lesson engine | NOT_STARTED |
| Aptitude/verbal/DI | Daily quiz/static paths | Quiz API exists | Arbitrary user IDs; non-atomic awards | Topic lessons/timed practice/verified arithmetic | Objective evaluation/persisted attempts | NOT_STARTED |
| System Design | 12 Studio scenarios, editable graph, modeled checks, FSRS | Scenario/CAS tests pass | Four-stage assumptions; narrow HLD breadth | HLD/LLD lessons/neutral reports | Reuse Studio and common curriculum | Baseline tested |
| Curriculum | DSA collections and five static paths | Collection routes | Wrong shortest-subarray link; generic destinations | Objectives/prerequisites/progress/runtime | Shared catalog | NOT_STARTED |
| Voice | Prisma v3/Timbre v3 WAV/WS/SSE, bounded quotas | Mock transport/lifecycle tests pass | Split Studio playback, English default, padded WS boundary/accounting | Shared policy/capabilities/module integration | Preserve shared gate; repair propagation/cancel | Current live NOT_RUN |
| Language | English/Tamil-English enums | Request tests; historical probes | Nine other locales hidden; TTS language drift | Capability and voice registry/localization | Ten documented locales; separate evidence levels | Docs fetched 2026-11-15 |
| Settings | Device stores/modal | Persistence/focus tests pass | Mount overwrites preferences; Studio ignores | Organized route and common policy | Categories/persistence/shared resolver | Pending |
| Dashboard/badges | Gamification router/migration 0013 | Renders API | Fabricated XP/streak/activity/progress/peers; unauthenticated | Owned event ledger/recommendations | Remove fake defaults, evidence aggregates | Security review requested |
| Interviews | Studio timed assessment/withholding | Timer/FSRS tests pass | No DSA/CS product; report gaps | Neutral adaptive interviewer/evidence report | Shared policies/persisted sessions | Pending |
| Codebase/Redrive | Passive bounded archives, AST/tree-sitter, FTS/citations, defense phases | Ingestion/security tests pass | No zero-knowledge plan, draft-only voice | Beginner checkpoints/adaptive tutor | Extend existing repository workspace | Pending |
| Deployment | Docker coordinator/worker/frontend, readiness | Packaging tests pass | Linux isolation external | Integrated release evidence | No deployment/submission | BLOCKED live isolation |

## Actual routes/APIs
Frontend: `/`, `/dashboard`, `/library`, `/practice/:exercise?spec=...`, `/paths`, `/paths/:collection`, `/progress`, `/studio`, `/studio?area=repository`. Parent and DSA routing are separate; query-only navigation and handled links need repair.
Backend: `/api/v1/meta`, `/sessions`, `/studio`, `/repos`, `/gamification`, `/ops/readiness`. New APIs must use workspace capabilities; no inferred ownership of historical demo profiles.

## Gnani documented capabilities
Official Prisma v3 STT and Timbre v3 TTS list English/Hindi/Tamil/Telugu/Kannada/Malayalam/Bengali/Gujarati/Marathi/Punjabi. Code mixing uses language hints plus codemix, not invented locales. V3 voices: Avinash, Shivani, Lakshmi, Kalpana, Shubham, Prakash, Devansh, Yashraj, Chetana, Vasudha, Riyaa, Tarika, Harshad.
Sources: https://docs.gnani.ai/api/STT/models/prisma-v3.md ; https://docs.gnani.ai/api/TTS/available-voices.md ; https://docs.gnani.ai/api/TTS/tts-sse.md . Current account quota/entitlements and human-language quality are unverified.

## Safety and evidence boundaries
New local runtime uses `data/full-product-engineering`, no database wipe. Raw microphone/camera data not retained by default. Imported repositories remain passive sanitized data, never instructions or executable projects. Models cannot establish executed outputs/mastery. Deterministic fallback must be labeled. No remote push, publication, deployment or submission.
