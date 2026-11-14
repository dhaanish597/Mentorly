# Plan audit and actual build status

Reviewed 12 November 2026. Product name remains undecided; team size is two human members.

The original Gemini plan was read in full and reviewed across API/state contracts, exercises, speech integration, execution isolation, evaluation and delivery. The corrected `IMPLEMENTATION_PLAN.md` is v2.0.0. It retains the selected feature scope and replaces deadline-driven reductions with ten dependency-ordered phases, P0–P9.

## Material corrections

| Area | Original problem | Revised decision |
|---|---|---|
| Delivery | Fixed overnight schedule and automatic feature cuts | Full-scope ledger; no dropped-for-time status; dependencies and acceptance gates |
| Name | Final name described as a publishing/build blocker | Configurable placeholder; stable technical IDs; naming remains nonblocking |
| Provenance | Claimed complete Mac-folder inspection | Historical Gemini claim distinguished from files actually accessible here |
| Competition | Unsupported weighted judging rubric and wrong required hashtags | Current official rules and correct hashtags; shortlist/awards distinguished |
| Competitors | Blanket statement that existing platforms only check output | No unsupported claims about Chakra or universal novelty |
| STT wire contract | Wrong format/header/control assumptions | Transport-specific documented names; WebSocket commit and explicit closure |
| TTS wire contract | Wrong language field, audio payload and event names | `language`, nested `audio_config`, `start/chunk/complete/error`, correct audio reassembly |
| Context/confidence | Coach question misused as previous transcript; assumed confidence | Prior audio transcript semantics; nullable provider confidence and user confirmation |
| Concurrency | Process semaphore called globally account-safe; one probe defines tier | One account dispatcher initially; shared coordination required before scaling |
| Costs | Request counts equated with credits, unverified free pricing | Separate volume caps, verified tariff conversion or explicit unknown balance |
| Isolation | Student child shares long-lived worker network/files/process trust | Trusted broker launches per-invocation no-network gVisor sandbox; oracle outside |
| Output trust | Child stdout implicitly trusted | Bounded separate diagnostics/protocol; strict validation; tampering limits disclosed |
| Prediction | No immutable case identity | Server-owned Challenge bound to revision/generation/input |
| Reveal | UI-only answer hiding | Enforced across API, trace, diagnostics, restore, event and export paths |
| Code saves | Older delayed save could become current | Atomic compare-and-swap, serialized saves and dirty-buffer suppression |
| Turns | Same-code newer turn not protected server-side | Active generation checks before persistence, queue, speech and publication |
| Typed fallback | Promised without a creation endpoint | Real text-turn contract and common confirmation flow |
| Domain switch | UI acknowledgement without backend enforcement | Persisted acknowledgement; invalidate old challenges and completion |
| State paths | No initially-correct-code or incomplete/replay handling | Explicit transition table and typed independent outcomes |
| Fresh cases | Diagnostic inputs reused as held-out transfer | Disjoint pools, generated-case exclusion and per-session history |
| Pedagogy | Passing a case called concept verification/mastery | Practice checkpoint; code status separate from prediction evidence |
| Counterexamples | Unsupported exact-minimality claim | Small reproducible examples with shrinking provenance, no global claim |
| Budget | Whole job and individual code shared two-second limit | Separate invocation, startup, job, search/shrink and replay/trace budgets |
| Trace | Fixed lines and generic deepcopy; cap confused with timeout | Dynamic frame/source events, safe serializer, separate storage/work/runtime limits |
| Coaching | Matching numbers treated as semantic validation | Approved evidence templates, constrained model slots and abstention |
| Injection | XML tags/comment stripping treated as defense | Untrusted data boundaries, no tool authority, schema and evidence gates |
| Evaluation | Four speakers ×6 clips incompatible with8/16 split | Twelve development and twelve held-out clips, speaker-disjoint |
| Timing | Cross-device monotonic timestamps subtracted | Local-clock durations correlated by IDs; measured p50/p95 |
| Privacy | Retention called legal compliance; deletion incomplete | Data minimization, consent, scoped cache/ownership, tombstone/cancellation and explicit limitations |
| Demo | Invented line numbers and live-only claims | Actual recorded behavior, honest live/cached/edit labels and real metrics |

The official page was checked at [gnani.ai/internship](https://www.gnani.ai/internship): cutoff15 November2026,18:00 IST; required hashtags `#GnaniAI` and `#GreatIndianAIInternshipChallenge`; verified engagement informs eligible-project shortlist, with individual interviews for offers. This is not a guaranteed-selection formula. Full development scope does not extend the external deadline.

Official contracts checked: [REST STT](https://docs.gnani.ai/api/STT/speech-to-text), [WebSocket STT](https://docs.gnani.ai/api/STT/stt-websocket), [SSE TTS](https://docs.gnani.ai/api/TTS/tts-sse). Account entitlement, quota, cost and live behavior remain untested here. The speech-plan corrections derive from documentation, not successful API calls.

## Implementation started: trusted exercise foundation

The build bundle contains `phase0_foundations/` with:

- Trusted direct-scan oracles for shortest qualifying subarray, first-at-least binary-search output and maximum-product subarray.
- Four legal specification records, strict input validators, exact-integer output comparator and canonical case hashes.
- Independent copied inputs and deterministic disjoint curriculum/holdout manifests.
- Six tests, including6,402 independent tiny-domain comparisons against deque, bisect and dynamic-programming alternatives; boundary/type/nonmutation/partition checks.
- An integration README describing safe merge into the actual repository.

Observed checks after final manifest updates, run from the package root:

```text
Python 3.12.14
python -m unittest discover -v
Ran 6 tests in 0.087s — OK
python -m compileall -q backend tests
Exit code 0
```

These tests validate trusted exercise behavior only. They do not validate the future student-code runner, Gnani integration, teaching efficacy or a complete Phase0. Finite exhaustive small-domain checks are not a universal proof. Deployment Python3.11 still needs its own run if selected.

## What is not done

The Mac directory `/Users/dhaanish/Documents/VIVA` was not accessible in this workspace, and no changes were made to it. The corrected document replaces the supplied plan; download/sync it into your actual VIVA folder before local implementation. No repo merge, real API/UI, live Gnani/model call, execution sandbox, deployment, audio dataset or user study has been completed here. The portable foundation is not a second app repository: integrate it only after inspecting existing files.

Phase0/T-01 is **partially started**, not complete. Its schema, generated contracts, persistence foundation, app shell, tooling and repository integration remain. P1–P9 are planned, not implemented. All features stay tracked.

## Next actions

1. Put corrected `IMPLEMENTATION_PLAN.md`, this audit, the two prompts and the extracted foundation beside the actual project documents. Preserve existing code.
2. Start the new ChatGPT chat, attach the build bundle (plus original research if it is not already accessible), and paste `NEW_CHAT_HANDOFF_PROMPT.md`.
3. That chat should read/reconcile the materials and return the local Codex phase implementation prompt. `CODEX_PHASE_0_IMPLEMENTATION_PROMPT.md` is also ready to use directly.
4. Local Codex inspects VIVA, completes the first incomplete phase with Astra/Sol/Terra if available, and returns actual test results plus continuation state. Bring those results back before generating the next phase prompt.

Skills/plugins are described inside both prompts as capability-discovery instructions, not claims that every local Codex installation has them. No public posts, repository visibility changes, paid infrastructure or competition submission were performed.
