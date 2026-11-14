# Next-phase test and acceptance matrix

All rows are **not run for this phase** until linked to dated, reproducible evidence on the tested commit. Capture environment, command, result, artifacts and baseline differences. Provider and Linux checks require appropriate authorized environment; mocks cannot establish real provider or isolation acceptance.

| Gate | Evidence and cases |
|---|---|
| Baseline | Source/manifest and Git identity; installed versions, route/exercise/version inventory; frontend build and existing backend/frontend test outcomes; capture pre-existing failures. |
| Phase 1 functional | Every active route and state; 31 baseline problems/32 spec versions preserved; setup, editing correct session, genuine execution with supported sandbox, result evidence, retry, history/resume; API schema/typed client compatibility. |
| Phase 1 voice & UI | Text fallback, microphone permission and interruption states, transcript edit, stale results and error handling using local fixtures; responsive desktop/mobile, contrast, focus order, keyboard, screen reader, reduced motion; principal route screenshots against Horizon. |
| Migration | Fresh DB and populated current 0006 upgrade to next version; online backup, rollback/recovery and restore; old active DSA sessions, exercise versions and restart hydration intact. |
| Session kernel | Six modes x two postures; no dummy code rows; lock/idempotency, retry, concurrent sessions/users, cancellation and stale turn epochs, resume/restart. |
| Scenarios | All 12 IDs reviewed and tested; versioned constraints, progressive injection, hints and consolidation, multiple valid/invalid architectures, failure/recovery and transfer; no title-only scenario. |
| Canvas and capacity | Graph/table round-trip, keyboard operation, validation and schema constraints, preview accept/discard, undo/redo, persisted revisions, conflicts; unit conversions, arithmetic, boundary/overflow and missing assumptions. |
| Mocks and review | Timed mock expiry, pause/resume/restart, teaching-vs-assessment isolation, debrief and abstention; FSRS due ordering, rescheduling, clock/time zone, persistence and cross-user isolation. |
| Repository security | ZIP traversal/absolute paths, bombs, symlink/hardlink, oversized files, binary/encoding and secret redaction; clone URL validation, DNS/redirect/private networks, timeouts/resource bounds, no hooks/submodules/code execution; adversarial instructions treated as untrusted content. |
| Evidence/privacy | Golden and imported repo maps, real resolvable lines/symbols and coverage manifest, four layers, uncertainty and evidence-linked rubric; scoped export/deletion of sources, indexes, snapshots, derived evidence and documented backup handling; cross-user access. |
| Performance | Measure p95 graph <50ms, FTS/AST <120ms, provider coaching <2.2s and fallback <15ms, 500-file ingestion <8s; report sample sizes, hardware, corpus, warm/cold conditions and failures. Budgets are targets. |
| Final integration | End-to-end DSA → bridge; guided design and timed mock; curated and imported repo defense → review; backend/frontend/contracts/security/accessibility and DSA regressions; screenshots and honest external blockers. |

Phase 1 gate requires the master directive's 16 checks, including actual route behavior and recorded limitations. Phase 2 gate requires its 22 checks plus the normative assessment, retention, performance and scenario requirements. A failing or unavailable critical check is an explicit blocker, not a pass.
