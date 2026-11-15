# Full product audit — 2026-11-15 recovery checkpoint

## Actual repository and evidence
The active repository is `/Users/dhaanish/Desktop/VIVA`, not the historical Documents path. Current branding is **Mentorly**, retained. Branch: `engineering/full-product-integration-20261115`. Existing commits and extensive uncommitted expansion/deployment work were preserved; no reset, clean, secret commit, remote push, deployment, or submission was performed.

Stack: React 18 / TypeScript / Vite 6, FastAPI / Pydantic, SQLite with additive transactional migrations. Workspace/session capabilities provide authorization; this is not an account/cross-device identity system. PostgreSQL work exists separately but its dedicated integration environment is unavailable.

Historical pre-expansion baseline: 976 backend/worker tests and 417 frontend tests. Those numbers and the original feature matrix are historical, not the current build status. Current exact test results and acceptance limits are in TEST_REPORT and FINAL_BUILD_STATUS.

## Recurring Not Found / Retry diagnosis
- Running backends **8020 and 8026** passed `/api/v1/meta/health` but lacked **21 current OpenAPI paths**, including learning, interviews, Redrive, conversation, and shared module voice.
- `start_local.py` had launched without reload, so editing source did not update those processes' route tables. Local startup now enables reload, with explicit `--no-reload` support.
- An existing explicit development mapping already recovered **8026 → 8028**, with the same configured `data/full-product-engineering/vcc.db`. There is deliberately no automatic switch from the primary database on 8020 to an isolated database.
- Vite's built-app preview had no configured API proxy. Development and preview now share the same proxy configuration.
- Generic FastAPI `{detail: "Not Found"}` was passed straight into the UI. Shared error handling now explains a missing backend endpoint, preserves distinct deleted-session/provider errors, and does not replay mutations.
- `allowedHosts: true` was removed; Vite's loopback host checks are restored.

Actual HTTP checks on **5186 and 5187** returned JSON 200 for health, exercises, curriculum, and speech capabilities. Protected interview routes returned the expected unauthenticated 401 rather than 404. An authenticated QA journey through 5187 passed 17 requests, including lesson completion, report persistence/recovery, second-interview continuity, ownership rejection, and scoped cleanup. The dedicated no-expiry report lookup is separately covered by regression tests.

The old 8020/8026 processes themselves remain stale until restarted. The app refused new server starts because five slots belong to other chats; attachment also reported that the in-app Browser is disabled on this install. No tool controls were bypassed. HTTP checks are not browser interaction or visual proof.

## Current feature matrix
| Feature | Existing implementation / working behavior | Defects or missing components | Changes / verification |
|---|---|---|---|
| DSA | Authored curriculum, practice editor, revisions/CAS, deterministic evidence and traces | Live arbitrary learner-code isolation not accepted on macOS; new interview code not linked to worker evidence | Existing regression suite retained; stale conversation routes diagnosed; active speaker UI already implemented |
| CS fundamentals | 30 authored lessons, prerequisite-aware practice and objective feedback | Bounded depth, not exhaustive teaching or semantic oral assessment | Shared lesson/API tests; existing speech fixture integration |
| Aptitude | 24 authored lessons and checked numerical exercises | No comprehensive timed/multi-question bank | Arithmetic/catalog regressions retained |
| System Design | 15 HLD/LLD lessons and 12 editable Studio scenarios, requirements and modeled checks | Not every curriculum case has a distinct canvas scenario; architectural correctness is context-dependent | Source and existing integration tests; no new browser claim |
| Curriculum | 100 versioned lessons across four modules, prerequisites, persisted attempts/completion | One objective per lesson; no proven mastery from a single answer | Real HTTP completion/progress; previously authored catalog remains bounded |
| Shared voice | Prisma v3 REST/WS and Timbre v3 SSE/WAV; shared quota/cancellation services and module adapter | Physical microphones and all-language natural conversations unverified | Provider fixtures retained; prior synthetic Gnani smoke explicitly separated |
| Languages | Ten provider-documented locales, three documented English code-mixes, 13 voices, common preferences | Full native UI/content translation and generative multilingual teaching unfinished | Request/configuration tests, not native-speaker certification |
| Settings | Six coherent categories; persisted audio/language/appearance controls | Profile/interview defaults, study goals/reminders, standalone voice preview and device selection unfinished | Existing settings tests retained; no decorative success controls added |
| Dashboard/progress | Workspace events drive lessons, interviews, recommendations and earned badges | All historic DSA/Studio/repository events are not unified; no paginated report archive | Completed interview references now become report links; QA progress matched persisted events |
| Interviews | DSA/CS/design/defense policies, neutral responses, epochs/timer and persisted abstaining reports | DSA executable grading absent; generic defense not repository-grounded | Read-only historical-report route added; report survives new interview and foreign access is denied |
| Codebase/Redrive | Passive ingestion, source hashes/citations, beginner plan/checkpoints and grounded defense | Full adaptive teaching depth and analytics integration remain incomplete | Existing source/ingestion/injection regression tests retained |
| Release/tooling | Backend suites, frontend build/typecheck/lint, OpenAPI/schema checks | Linux/runsc and PostgreSQL acceptance, fresh browser/cross-browser QA unavailable | Startup reload + preview proxy repaired; read-only local route diagnostic with 94% scoped coverage |

## Routes audited
Frontend: `/`, `/dashboard`, `/library`, `/practice/:exercise?spec=...`, `/paths`, `/paths/:collection`, `/learn`, `/learn/:lesson`, `/progress`, `/settings?category=...`, `/interviews`, `/interviews?report=...`, `/studio`, `/studio?area=repository`.

Backend mounted families: `/api/v1/meta`, `/sessions`, `/speech`, `/studio`, `/repos`, `/learning`, `/interviews`, `/module-voice`, `/ops`. Retired fake-personalization gamification routes respond 410; do not advertise a live leaderboard or fabricated XP/streaks.

## Safety and verification boundaries
No existing database was wiped or redirected to a different identity to hide failures. Two HTTP QA workspaces were created and deleted through their own capabilities; no existing learner records were used. No new provider calls or raw audio/camera retention occurred during this recovery. Imported repository text remains untrusted data. Unit coverage, source presence, HTTP route delivery, historical browser observations, and genuine provider evidence are distinct verification levels.
