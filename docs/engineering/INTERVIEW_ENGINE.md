# Interview engine

## Purpose and integration

This is a deterministic, text-first interview flow, not an LLM judge or a psychological assessment. It runs without a camera, speech credentials or model credentials.

- Backend export: `backend.app.interviews.routes.router`, prefix `/interviews`; include under `/api/v1` in the coordinator.
- Frontend export: `InterviewPage` from `implementation/frontend/src/features/interview/InterviewPage.tsx`.
- Required page prop: `workspace: { id, token }`. Optional props: `api`, `initialSessionId`, `onMessage`, `onRecommendation`, `renderVoice`.
- Default API helper: `createInterviewApi(workspace)` uses the existing Studio transport and `X-Workspace-Id` / `X-Workspace-Token` headers. There are no caller-selected user/owner IDs.
- The coordinator owns `/interviews` navigation, common speech integration, application request-size/security middleware, and learning integration. Recovery adds `/interviews?report=...` in `ProductApp.tsx`, using only an existing workspace and a read-only report API; no interactive initialization or media is mounted.

## HTTP contract

All endpoints require an existing, nonexpired, nondeleted Studio workspace capability. Unknown or cross-workspace session IDs return 404; invalid capabilities return 401. Invalid schemas/catalog topics return 422; stale epochs return 409.

| Endpoint | Input / result |
| --- | --- |
| GET `/api/v1/interviews/config` | Types, difficulty levels, durations, language preferences and honest camera/assessment policies |
| GET `/api/v1/interviews/catalog` | Topic identifiers and allowlisted exercise metadata, including input constraints; never source fixtures, model solutions, hints or private test pools |
| POST `/api/v1/interviews/sessions` | `{type,difficulty,topics,duration_minutes,language_mode}` -> active session and exactly one question |
| GET `/api/v1/interviews/sessions/{id}` | Interactive current epoch/state/question; may materialize an elapsed timeout and report |
| GET `/api/v1/interviews/reports/{id}` | Read-only validated persisted report for an owned already-completed session; active/expired-active sessions return 404 without lifecycle writes |
| POST `/api/v1/interviews/sessions/{id}/answers` | `{expected_epoch,answer,code?}` -> neutral acknowledgement and next question or completed session/report |
| POST `/api/v1/interviews/sessions/{id}/finish` | `{expected_epoch}` -> immutable report |

Types: `dsa`, `cs`, `system_design`, `codebase_defense`. Difficulty: `beginner`, `intermediate`, `advanced`. Duration: integer 5–60 minutes, default UI 15. Language preferences use the canonical backend `models.enums.LanguageMode` and frontend speech registry: `en-IN`, `hi-IN`, `ta-IN`, `te-IN`, `kn-IN`, `ml-IN`, `bn-IN`, `gu-IN`, `mr-IN`, `pa-IN`, plus approved `ta-IN,en-IN`, `hi-IN,en-IN`, `bn-IN,en-IN` code mixes. Unsupported locales and unapproved combinations are rejected. Topics must be unique catalog identifiers, at most eight. Answer length is limited to 12,000 characters; optional code to 24,000. A workspace may have three nonexpired active interviews and create at most 100 interviews per UTC day. Application-level request-size/rate limits should also cover this router.

Session creation is not idempotent: retrying creation may create another session. Answer writes are protected by durable epochs and unique question/answer constraints. Retrying finish with the finishing epoch returns the same report. A newly discovered timeout finalizes regardless of a stale expected epoch, without recording late input.

## Question policy

Each domain has a separate policy module under `app/interviews/policies/`:

- DSA uses trusted public exercise descriptions, exact default specification IDs and input constraints. Difficulty changes question depth and prefers matching exercise metadata. It does not relabel a beginner exercise as advanced when an advanced catalog item is unavailable.
- CS asks about operating systems, databases and networking mechanisms.
- System design asks about capacity assumptions, consistency and failure/recovery boundaries.
- Codebase defense asks for ownership, request flow and change-safety explanations. No repository is ingested by this module; file/line mentions are unverified claims.

The primary question is followed by at most one deterministic follow-up. The follow-up depends on missing lexical evidence in the actual answer (reasoning marker, example marker, complexity notation, boundary term, tradeoff, failure/recovery or file/line mention). If those markers are present, a domain-specific depth probe is used instead. Different wording does not prove semantically different understanding, and keyword presence does not prove validity. The question plan is bounded (two to eight primary questions where the selected catalog supplies them), pinned into the durable session, and ends when exhausted or timed out. No correct/incorrect verdict, score, model answer, hint ladder or rubric observation is shown during the session.

## Persistence, deadlines and privacy

Migration `0015_interviews.sql` introduces capability-owned sessions, asked questions, answers/code, immutable reports and event records. Operations revalidate the retained request-scoped capability with the existing Studio `auth_workspace_row` after acquiring `BEGIN IMMEDIATE`; pre-admission authentication alone is not ownership proof. Session/source reads join a live, nondeleted workspace, creation independently requires a live workspace, and the sweeper excludes revoked owners. This closes the tested tombstone/expiry-after-admission race that could otherwise recreate private data. Each accepted answer consumes exactly the current epoch and exactly one asked question. Concurrent same-epoch submissions allow one winner. Reports are insert-once; an SQL trigger rejects updates.

Manual finish, question exhaustion and timeout write the completed state, incremented epoch, immutable report and one `interview.completed` event atomically. Deadline checks occur on interactive session GET, answer and finish, not on the dedicated report GET. A coordinator can also call `service.sweep_expired(database_path, hook)` periodically; without that job, an unattended timeout is materialized on the next request. The browser polls active sessions every 15 seconds; its displayed timer is informational, while the backend owns admission.

Migration `0020_interview_privacy.sql` was added separately after the privacy regression demonstrated that Studio soft deletion does not invoke hard-delete FK cascades. It deletes all interview sessions when `studio_workspaces.deleted_at` becomes non-null, cascading to private questions, transcripts/code, reports and events. It also purges interviews owned by workspaces already tombstoned before upgrade. Immutable does not mean immune to authorized privacy deletion. Workspace expiry alone prevents access; deletion/retention orchestration remains responsible for tombstoning expired workspaces. The original migration was not rewritten for this correction.

The page stores only its server-assigned interview ID in workspace-scoped tab storage to resume; it does not store interview credentials or answer transcripts there. Server reports survive process restart. Optional camera preview calls `getUserMedia({video:true,audio:false})` only after an explicit click. Tracks are stopped on toggle-off, completion/unmount and cancellation of an outstanding permission request. There is no image upload, recorder or visual inference path.

## Evidence limits and reports

Every textual indicator is bounded to 0/1 with a maximum of 1. These are observations, not grades. Positive observations contain exact answer excerpts with Unicode-codepoint start/end offsets; the frontend validates their anchors, including emoji-containing answers. Report statuses explicitly name:

- `semantic_validity: unassessed`: reasoning, claims, complexity, examples and citations are not semantically graded.
- `technical_correctness: unassessed_no_execution_evidence`: submitted code is never executed by this module. No secure-worker execution adapter is integrated, so all technical correctness claims abstain. Client-supplied execution verdicts are rejected as unknown request fields.
- `psychology: not_assessed`: no camera, affect, confidence, personality or cognitive inference.

There is no LLM proof. English lexical cues have incomplete coverage for non-English and mixed-language answers. Language mode is a voice preference, not translated question generation or multilingual semantic grading.

Reports contain domain-specific `practice_topics` derived from the pinned question plan and observed/missing textual indicators. DSA catalog-backed recommendations include exact exercise/specification IDs; `lesson_id` remains null until a coordinator-validated lesson mapping exists. Non-DSA policy topics are not silently treated as exercise or lesson identifiers. Recommendations and interview completion are not correctness or mastery evidence.

## Learning and speech seams

The optional `app.state.interview_completion_hook(conn, workspace_id, event)` runs inside the completion transaction. It must be synchronous, fast and DB-local: no external network effects. Exceptions propagate and roll back interview completion. The durable completion event is the authoritative outbox; external asynchronous processing needs its own idempotency and delivery strategy.

Completion payload: `{session_id,type,completion_reason,answered_count,report_available:true,correctness_assessed:false}`. Count completion only; never award correctness/mastery from these observations. No public endpoint accepts client-authored completion events.

The setup language selection initializes from shared speech recognition/code-mixing preferences and exposes native locale labels. Changing it synchronizes shared recognition language, spoken-response language and code mixing while preserving the chosen voice and interface preference, so common ModuleVoice reads the same selection. Persistence failures are surfaced rather than implying voice has switched. Authored question text stays English; selecting a speech language does not claim translated questions or multilingual semantic grading.

`renderVoice({sessionId,epoch,messageId,onTranscript})` receives the current persisted question UUID. The coordinator can mount its common voice UI there; transcripts append to the answer draft and do not auto-submit. `onMessage` supplies neutral text/source-reference messages with ID/session/epoch/kind for introduction, acknowledgement, current question and ending. Intro/ack/end UI IDs are synthetic, not persisted speech-source IDs; only the asked question UUID is currently suitable for a server-owned question-text speech lookup. Private rubric keys in `interview_questions.question_json` must never be serialized as speech context.

## Recovery verification — 2026-11-15
Progress links use validated/encoded session references. Report routing reads the existing workspace without creating another, fences stale responses and preserves a separate active interview's resume ID. The dedicated backend report read validates stored evidence inside a consistent read transaction and never calls expiry/completion hooks. Tests compare before/after rows for expired-active sessions, completed-report replay, ownership denial and invalid reports; normalized external URLs and standalone dot identifiers are rejected.

Final totals and real HTTP evidence are in [TEST_REPORT](TEST_REPORT.md) and [FINAL_BUILD_STATUS](FINAL_BUILD_STATUS.md): 1276 backend/worker tests passed (14 environmental skips), 734 frontend tests passed, typecheck/build/contracts and lint passed. No new browser or provider acceptance is implied.

## Historical module tests and evidence (counts superseded)

Tests were written before implementation. Initial RED runs failed because the interview module/page did not exist. Additional executed RED regressions covered stale-epoch timeout completion, soft-delete privacy, missing DSA input constraints, absent module practice topics, tab resume/recovery, fabricated correctness/psychology verdicts and unanchored excerpts; the corresponding narrow runs turned GREEN. A later browser finding prompted additional RED/GREEN regressions for all 13 canonical speech modes, Hindi/Bengali/code-mix session requests, unsupported locale rejection, response validation, and shared STT/TTS preference propagation preserving the selected voice.

Commands run from `implementation/backend`:

```sh
/Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python -m pytest tests/integration/test_product_interview_api.py --cov=backend.app.interviews --cov-report=term-missing -q
```

Result: **31 passing integration tests; 99% backend coverage** (396/399 statements). Tests use a real migrated SQLite database and mounted FastAPI router, verify capability isolation, CAS concurrency, neutral answer behavior, bounded excerpt evidence, timeout/finish replay, immutable SQL reports, natural exhaustion, transactional optional hooks, deletion cleanup, revoked/expired ownership after pre-admission, and process/app reopening. They do not run a model provider, speech provider or secure execution worker.

Commands run from `implementation/frontend`:

```sh
npm test -- src/__tests__/productInterview.test.tsx src/__tests__/productInterviewBoundary.test.tsx --coverage --coverage.include='src/features/interview/**/*.{ts,tsx}' --coverage.reporter=text
npx eslint src/features/interview --max-warnings 0
npm run typecheck
```

Result: **43 passing tests; 97.29% lines, 91.66% statements, 80.67% branches, 94.33% functions** for the reported interview source coverage. Owned ESLint and full frontend TypeScript checking passed. Coverage is not a claim about the entire application. Frontend tests are JSDOM component/transport tests; camera devices and network responses are doubles. Real-browser layout, screen-reader walkthroughs, hardware-camera behavior, provider speech and end-to-end coordinator journeys were not independently validated by this module task. No commits, branches or delegated agents were created.
