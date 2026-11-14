# Requirement traceability

Status key: **open** means planned and unaccepted, regardless of existing partial code. Evidence must link exact commit, commands, outcomes and artifacts. Source hierarchy: master directive > Nov 14 main plan and normative appendix > research proposals, reconciled against current code. No row below is complete.

| ID | Requirement and accountable implementation | Acceptance evidence | Status |
|---|---|---|---|
| P0-01 | Isolated snapshot, manifest, route/capability/inventory and reproducible baseline | clean baseline identity, commands, blockers | open |
| P1-01 | Horizon-derived cohesive visual system, all surfaces and routes, no demo identity/auth | route inventory, responsive screenshots, manual visual review | open |
| P1-02 | Preserve catalog IDs, 31 problems / 32 versions observed at baseline, specifications, session and genuine execution | catalog comparison; DSA edit/run/resume; backend/frontend regressions | open |
| P1-03 | Existing real voice integration, editable transcript, interruption and text fallback | UI state and mock/integration evidence; provider authorization respected | open |
| P1-04 | Keyboard, screen-reader, focus, contrast, responsive and reduced motion | accessibility and manual keyboard checks | open |
| P1-GATE | Build, tests, schema/client compatibility, routes, screenshots and limitations | recorded gate report | open |
| FR-MODE-01 | Six modes and teaching/assessment posture; non-DSA sessions do not require dummy code | migration/restore, DSA and non-DSA lifecycle tests | open |
| FR-DESIGN-01 | Four Bridge and five Core authored versioned scenarios, progressive constraints, multiple valid families | all nine reviewed specs, deterministic predicates and end-to-end sessions | open |
| FR-DESIGN-02 | Synchronized canvas and structured table, accessible editing, revision history, diff preview/confirm, undo/redo | equivalence, persistence, concurrency and keyboard tests | open |
| FR-DESIGN-03 | Unit-bearing capacity calculator, scenario-bound assumptions and deterministic topology/invariants with uncertainty | dimension/math boundary and diverse topology fixtures | open |
| FR-COACH-01 | Derive, bounded scaffold, consolidate, transfer; hints, direct explanation, real state and interrupted-turn fencing | branching pedagogy and stale epoch tests | open |
| FR-MOCK-01 | Timed architecture mock with assessment posture, clock/pause/resume, no teaching leaks, evidence-linked debrief | timer, restart, boundary and assessment tests | open |
| FR-REPO-01 | Golden snapshots, public HTTPS shallow clone and ZIP, zero execution, bounded ingestion | malicious archives, SSRF/redirect/DNS, symlink, resource and secret tests | open |
| FR-REPO-02 | Traceable four-layer evidence: observed code, explicit docs, inference and learner alternative; distinguish missing intent | verified citation resolution, adversarial prompt-injection and abstention tests | open |
| FR-REPO-03 | Repo map, guided exploration/defense and actual evidence-backed transfer | three catalog maps and BYO end-to-end, coverage manifest | open |
| FR-ASSESS-01 | Four independent evidence-linked dimensions, abstention; no job-readiness claims | rubric/evidence and insufficient-signal tests | open |
| FR-REVIEW-01 | Persistent FSRS due scheduling and cross-domain transfer cards | scheduler, time zone, restart, isolation and due queue tests | open |
| FR-PRIV-01 | Local-first explicit upload/provider boundaries; export and complete scoped deletion including derived data, files, indexes and backups policy | data-flow, deletion and isolation tests, documented retention | open |
| NFR-01 | p95 targets: graph <50ms, retrieval <120ms, coaching <2.2s provider / <15ms fallback, 500-file ingestion <8s | measured distributions, environment, sample sizes; targets not claims | open |
| NFR-02 | bounded resources, session lock/idempotency, concurrency, stale turn handling, safe failure | race, timeout, restart and security suite | open |
| P2-GATE | All requirements plus real credentials permitted, no critical placeholder | complete gate report with blocked external checks | open |

The six detailed and six additional scenario IDs and content decisions are in the implementation spec. Scenario count is twelve (4 bridge + 5 core + 3 repository), not three. Exact existing exercise count must be re-inventoried at the Phase 1 gate; 31/32 is the isolated baseline, not a new hard-coded product limit.
