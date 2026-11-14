# Gemini 4 Argon execution prompt — complete Phase 0 / T-01

Act as the lead implementation engineer for the selected Gnani voice coding coach. **Implement this phase now**, then test, review and report it. The product is approved; no new idea search or planning-only response. Use the user-selected Gemini 4 Argon as lead orchestrator and use real sub-agents for bounded implementation and independent review. Discover the actual runtime/model and sub-agent tools; do not assume a product label establishes capability. Use the selected model for sub-agents where supported. If the runtime does not expose its model identity, report it as unverified. If real sub-agents are unavailable, state that limitation, preserve the work boundaries, and continue sequentially without pretending role-play is delegation. Do not switch to Codex or a different model without my instruction.

## Updated execution authority and phase boundary

I have attached the working folder and the initial build handoff bundle produced in the previous ChatGPT chat. Explore those actual files and start implementation. The product and corrected plan are already approved: do not restart ideation, naming, broad research, or an approval loop for starting this phase.

Gemini is the implementation agent for the initial phases I assign. This does not mean changing the application's coaching-model provider to Gemini; builder model choice and application provider choice are separate decisions. Preserve the provider architecture in the approved plan.

This run is authorized to complete **Phase 0 / T-01 only**. Complete, test, review and document it, then stop at that phase boundary with the continuation packet below. I will decide which subsequent phases Gemini implements and when to switch to Codex. A future Codex session will audit Gemini's actual code and evidence, fix findings as needed, and continue implementation. Do not invoke Codex now, automatically implement all P1–P9, or treat a Gemini self-review as the future Codex audit. If inspection proves P0 is already complete, independently verify its acceptance gates and report the next dependency-ready phase for my assignment; do not rebuild P0 or start that next phase without it being assigned.

## Read first and preserve existing work

Find the real selected project root. The historical directory is `/Users/dhaanish/Documents/VIVA`; verify it, do not assume it is mounted or create a nested replacement. Read applicable AGENTS.md files and git status, inventory the entire folder recursively, and read all relevant source documents and existing code. Classify vendor/generated/binary files; do not print `.env` contents or private credentials. Prioritize latest user instructions and corrected `IMPLEMENTATION_PLAN.md` v2.0.0 over older plans. Read `PLAN_AUDIT_AND_BUILD_STATUS.md` and `NEW_CHAT_HANDOFF_PROMPT.md` for context. If attached filenames clash, use version header/content, not filename alone. Record missing/inaccessible documents instead of claiming full inspection.

The provided `phase0_foundations/` is a portable tested source patch, not an existing app or merged change. Diff it against current modules. Merge absent/reviewed functionality without overwriting existing code, tests, package initialization, dependencies or user changes. Follow the repository's actual package layout. If a deliverable is already implemented, verify and preserve it, then complete the next missing P0 deliverable. Follow the phase boundary above if all P0 gates already pass.

## Source precedence and current folder evidence

On inspection for this prompt, `/Users/dhaanish/Documents/VIVA` contained planning/research files and `GNANI_BUILD_HANDOFF_BUNDLE/phase0_foundations/`; it was not a git repository. This is an observation to recheck, not proof that the folder will remain unchanged.

Two different plans exist:

- `GNANI_BUILD_HANDOFF_BUNDLE/IMPLEMENTATION_PLAN.md` is **v2.0.0**, audited 12 November 2026, and is the authoritative corrected technical plan.
- The top-level `IMPLEMENTATION_PLAN.md` is **v1.0.0**, retained as historical context. Do not accidentally implement it in preference to v2.

Read the corrected plan in full, the bundle's audit/status, both historical prompts, the foundation README/VERIFICATION, all foundation source/tests/manifest, and relevant original blueprint/research documents. Inventory the entire tree and classify files before deciding which documents/code require detailed inspection. Record unreadable PDFs or missing attachments. Do not claim that filenames or summaries constitute inspection.

Latest user instructions in this prompt supersede the old Astra/Sol/Terra routing and Codex-first execution instructions wherever they occur, including inside v2.0.0. Other product, safety and acceptance requirements remain in force. Preserve the original bundle as provenance. If useful, create a clearly identified working plan that records this execution-method override without rewriting the historical source.

Verify the selected working root rather than creating the example `voice-coding-coach/` tree as a second nested project. If no git repository exists and no applicable instruction prevents it, initialize local version control in the actual selected project root, with appropriate ignore rules before staging anything. Do not create a remote or push. Inspect status before and after changes; preserve user work.

## Nonnegotiable scope

Two human teammates; final name undecided; placeholder branding in one config. Build all selected features across phases. No time-driven feature deletion, permanent disabling or untracked “later.” REST/WS, real Gnani voice, model-assisted/deterministic coaching, all3 exercises/4specs, full UI, validation, privacy, operations and evaluation remain tracked. Fallbacks never satisfy omitted live features. This phase completes foundations only; do not mark the entire application complete.

Discover and read applicable repository instructions and genuinely installed skills/workflows. The old prompts name Codex-specific skills and connectors; those names do not prove they exist in Gemini. Use their underlying practices with the available tools: scoped execution, meaningful behavior tests, isolated edits, independent review, systematic debugging and verification before claiming completion. Use official documentation or Context7 if available for exact dependency contracts; local git/GitHub capabilities for repository inspection; available filesystem/PDF tools for source materials; and browser automation where available for the shell. Do not install plugins solely to imitate the previous agent's setup or claim unavailable tools were used. Latest user authorization permits implementation and subagents now; do not stop for redundant permission. Do not publish, post, provision paid resources or submit the competition entry.

## Phase0 deliverables

1. **Ground truth and tracking:** Create/update `docs/SOURCE_INVENTORY.md`, `docs/DECISIONS.md`, `docs/FEATURE_COVERAGE.md`, `docs/IMPLEMENTATION_STATUS.md`. Cover FR01–22, NFR01–07,13 UI states,3 exercises/4specs,2 recognition modes,2 STT transports and model/deterministic paths. Status vocabulary: NOT_STARTED, IN_PROGRESS, IMPLEMENTED_UNVERIFIED, VERIFIED, BLOCKED_EXTERNAL. Record exact evidence and all remaining work.
2. **Reproducible foundation:** Preserve compatible existing stack. Otherwise establish Python/FastAPI/Pydantic backend and TypeScript/Vite/React frontend structure, compatible runtime versions, dependency locks, lint/type/test commands, `.gitignore`, secret-free `.env.example`, minimal CI and README. Add only dependencies needed for implemented phase interfaces. Keep broker/runner directory boundary explicit; don't pretend the sandbox is implemented.
3. **Brand config:** Add `config/branding.json` and tested backend/frontend consumption. ProductName `Voice Coding Coach`, status UNDECIDED_PLACEHOLDER. Keep environment/database/storage identifiers stable and brand-independent.
4. **Trusted exercises:** Integrate the provided validators/oracles/comparator/case manifest and independent tests. Canonical IDs: `ex1_shortest_subarray`, `ex2_binary_search`, `ex3_max_product`. Retain exact legal domains and strict integers rejecting booleans. Validate immutable spec mapping and trusted input copies. Keep static curriculum/holdout partitions disjoint; dynamic session exclusion belongs to the coordinator phase and stays explicitly pending. The package must include its JSON manifest when installed.
5. **Frozen contracts:** Implement strict Pydantic request/result/domain schemas and enums from plan§6, including RevisionRef, Challenge, ClaimInterpretation discriminated union, ExecutionObservation, VerificationReport, EvidenceArtifact, TraceStep, SpeechJob and ApiError. Define the request DTOs used by module interfaces. Distinguish NO_FAILURE_FOUND from incomplete/timeouts/unavailable/replay-unconfirmed; prediction MATCH/MISMATCH/NOT_EVALUATED is independent. Generate TS types/contracts from the same source. No second handwritten incompatible schema. Test representative valid and invalid payloads.
6. **Database contracts:** Create versioned migration/schema for sessions, code versions, turns, challenges, case history, jobs, artifacts/traces, coaching/speech jobs, idempotency, usage ledger/reservations and events. Include ownership FKs, unique session/revision and challenge identities, expiry/tombstone and indexes. Add repository interfaces and migration initialization/rollback or tested forward-recovery policy. Implement only claimed working persistence methods; no success-shaped stubs.
7. **Runnable minimal shell:** Backend app factory with public-safe health/branding/exercise metadata; frontend shell displaying actual branding and exercise metadata with loading/error states. Generate or otherwise validate OpenAPI contracts for implemented routes and keep remaining route DTOs defined without exposing fake success endpoints. Default custom-code execution to disabled; any execution request cannot reach Python eval/exec in the coordinator.
8. **External capability record:** Create `docs/GNANI_CAPABILITIES.md` as NOT_TESTED/BLOCKED_EXTERNAL until tested. Inspect official Gnani docs for §8 wire contract and capture redacted offline contract fixtures. If usable credentials and a bounded smoke mechanism already exist, perform an authorized small live check without exposing secrets, using the same account dispatcher policy. If no credentials/dispatcher/runtime, do not invent request IDs or fabricate PASS. Continue all independent work. Full live adapter and sandbox are P2/P1, not prerequisites for safe contracts.

## Critical contracts and tests

- Exercise legal-domain checks: Ex1 no empty input/target≤0, positive vs negative domains; Ex2 sortedness/duplicates/empty; Ex3 nonempty/bounded product; bool/float rejection; trusted-oracle nonmutation.
- `[1,-1,5],5` reference1; `[-3,-3,-3]` reference9. Don't execute arbitrary learner strings in Phase0 to demonstrate bugs. Exact reviewed fixture execution later uses real isolation.
- Challenge input is immutable and bound to session/spec/code hash/version/generation. DTOs cannot allow a client to relabel an input after prediction.
- Code update requests carry expected_code_version_id and client_edit_sequence. Domain acknowledgement and new-turn generation are explicit. Persistence shapes support atomic CAS, idempotency digest conflicts and deletion races.
- Audio, text fallback, confirm, verify, fresh-case, hint, playback, cancel, restore/export/delete, events/jobs and capacity have coherent DTOs and endpoint definitions. Full implementation follows dependency phases; don't label DTOs completed API behavior.
- Result variants distinguish exception/timeout from integer output. Nullable confidence and source/trace attribution are explicit. Hidden-artifact view schemas omit answers until authorized; access checks remain tracked for their implementation phase.
- No provider credentials in frontend/env exports, public health, logs, fixtures or commits. No unsafe sandbox fallback or Docker socket exposed to learner code.

## Additional invariants carried forward from the handoff

- The user flow remains explain → predict this program on this immutable input → correct/confirm interpretation → execute in isolation → inspect real output/trace → graduated hints → repair → bounded verification → genuinely fresh transfer. Prediction correctness and code correctness are independent.
- Preserve the corrected logical-turn lifecycle in plan §6.2: creating a challenge allocates its turn and generation; audio/text answers and re-recordings for that current challenge reuse them. Each capture has its own monotonic attempt ID. Only the latest attempt can populate/confirm claim chips. An unrelated new turn or replacement challenge increments generation even when code is unchanged. Freeze these DTOs and persistence shapes now; enforce runtime behavior in the assigned later phase.
- Server-owned reveal authorization must cover restore, export, trace, diagnostics, events and job results. Domain selection requires persisted acknowledgement. Dirty editor buffers suppress stale feedback; serialized saves and atomic CAS remain required. P0 contracts are not proof these runtime paths exist.
- Keep all 13 UI states, EN and Tamil-English/Tanglish recognition, genuine Gnani REST/WS STT, SSE TTS/playback/cache, typed fallback, microphone setup, cancellation/barge-in, model-assisted and deterministic coaching, Monaco, all exercises/specs, privacy, operations, evaluations and deployment tracked. Baseline coach speech is Indian English; do not claim validated Tamil TTS.
- Per-invocation no-network gVisor isolation is required later. A subprocess in a long-lived worker, RestrictedPython, AST filtering or an internal container bridge is not an equivalent fallback. Treat learner-controlled traces/protocol output as untrusted even inside isolation; require bounded serialization and independent replay. Do not execute learner strings during P0.
- Keep trusted oracles and holdout answers off public metadata endpoints and client payloads. Fresh-case selection later must exclude every executed/revealed session input and all diagnostic/search pools. Initially correct code must be supported without inventing a prior failure. Say “practice checkpoint completed,” not proven mastery.
- Preserve separate execution, verification and trace budgets; incomplete search is not a pass, replay disagreement is not a confirmed counterexample, and shrinking does not prove global minimality. Trace attribution comes from real source/frame evidence; uncertain causal explanations require abstention.
- Follow corrected Gnani wire contracts in plan §8 and current official docs. TTS uses `language` and nested `audio_config`; SSE uses `start/chunk/complete/error` with `audio` and `chunk_index`. WS STT uses underscore configuration names and `commit`. REST `previous_text` is preceding audio transcript. Confidence may be absent. Documentation fixtures do not prove live capability.
- A process-local semaphore does not establish account-wide multi-replica admission. Smoke/prewarm/evaluation must share the dispatcher policy. Two successful concurrent calls do not prove the exact provider tier; calls are not credits.
- Use real metrics only. Preserve the 24-clip, four-speaker, speaker-disjoint 12-development/12-test study design for its later phase; separate human-assisted confirmation. Never subtract browser and server monotonic clocks. Do not invent study results, human contributions, competitor limitations or guaranteed selection claims.

## Agent ownership

Gemini lead first freezes canonical IDs, schema ownership, repo paths and test commands; integrates work and maintains the full feature ledger. Define bounded assignments with inputs, exact editable paths, interfaces, expected outputs and acceptance commands. Use a short task plan, then execute it in this run. Respect actual concurrency limits and use parallel execution only for independent tasks.

- **Implementation sub-agent A:** trusted exercises, manifest/package integration, database schema/migration foundation and associated tests. Edit only assigned backend exercise/database/test paths.
- **Implementation sub-agent B:** branding, frontend shell/client generation plumbing, minimal backend metadata shell and related frontend/metadata tests in assigned nonoverlapping files.
- **Gemini lead:** central DTO/enums/OpenAPI decisions and shared dependency/build configuration. Subagents consume those interfaces; they propose changes to shared files rather than racing edits.

After implementations, assign independent reviews of correctness/security/spec coverage, with reviewers explicitly checking code and test output rather than accepting reports. Use isolated worktrees if appropriate; preserve user work. Merge/integrate dependencies sequentially and rerun affected checks once. Do not fabricate use of a named model or automated human contributions.

## Verification and completion

First reproduce the portable package tests from its own directory: `python -m unittest discover -v` and `python -m compileall -q backend tests`. It previously passed6 tests with6,402 independent tiny-domain comparisons on Python3.12.14; rerun after integration and on the actual target runtime. Then run the repo's configured backend test/lint/type checks, frontend test/type/build checks, migration tests, generated-contract drift check and secret hygiene checks. Discover exact commands from actual configuration; never report commands you did not run as passing. Test new behaviors test-first where meaningful.

Before claiming T-01 complete, inspect every Phase0 deliverable against code. Mark DTO-only behavior and unavailable external capabilities accurately. Fix review findings within scope; do not solve them by deleting requirements. Checkpoint reviewed changes in the actual repo only after inspecting staged contents; no automatic push. Do not package a duplicate unrelated project.

Return:

1. Actual repo root, branch/worktree, model routing and skills/tools used.
2. Implemented behavior and changed files, including how the portable foundation was merged.
3. Exact test/build commands, observed results and failures/blocks.
4. Phase0 acceptance checklist, remaining full-scope feature status and any justified design decisions.
5. Whether live Gnani/sandbox/browser checks were actually performed or remain pending. Include actual browser evidence for the shell if tested; otherwise mark the browser gate unverified.
6. Current commit/status, any user work intentionally preserved, and a ready continuation packet identifying P1 safe execution and P2 voice foundation once dependencies permit. Recommend the next phase without starting it.
7. Create `docs/GEMINI_PHASE_0_REPORT.md` and `docs/CODEX_AUDIT_HANDOFF.md`. The report records task/sub-agent ownership, changed paths, review findings and fixes, exact commands and observed outcomes, acceptance matrix, design decisions, deviations, unresolved risks and actual external-test status. Include reproducible check commands and evidence locations, not raw credentials or private provider bodies.
8. The future Codex handoff identifies the authoritative v2 plan and this execution override, baseline and resulting commit IDs (or explicitly uncommitted state), current branch/worktree, clean reproduction/startup commands, generated artifacts and drift checks, remaining feature ledger, pending gates and next assigned-phase options. Ask the future auditor to inspect code and rerun checks rather than accepting the Gemini report as proof. Do not require a Codex audit to complete this P0 run; prepare the packet for when I choose the switch.

Start by inspecting the actual folder and implementing the first missing deliverable now.
