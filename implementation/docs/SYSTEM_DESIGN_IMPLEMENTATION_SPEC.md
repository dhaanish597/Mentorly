# System design and repository learning implementation specification

This is a planned contract to refine against actual code after the Phase 1 gate. The authoritative inputs are `coordination/plan-0.txt` and `plan-1.txt`; numbers and examples below are authored requirements, not measured results.

## Shared architecture and behavior

Extend the existing coordinator, locking/idempotency and voice/text lifecycle to six learning modes: `dsa_coding`, `dsa_to_system_bridge`, `guided_system_design`, `architecture_mock_interview`, `repo_exploration`, `project_defense`, with `teaching` and `assessment` posture. Non-DSA sessions must not create fake code versions. Persist scenario and revision IDs, constraints, assumptions, turn epochs, hints, decisions, graph and evidence atomically. Fence stale speech/LLM responses after cancellation or revision and make resume/retry idempotent. Use next unused migration after the existing 0006, with online backup and upgrade/restore verification.

Author versioned structured scenarios with learning objective, prerequisites, seed graph, constraints and reveal gates, capacity units, valid architecture families, predicate checks, failure modes, misconception/hint ladder, consolidation and transfer, assessment evidence and citations. Do not use LLM judgment as a deterministic oracle. Every graph supports an accessible structured table, keyboard editing, consistent round-trip, explicit AI diff confirmation, undo/redo and persisted versions. Calculations expose assumptions and dimensions for RPS, read/write, storage, bandwidth, concurrency, latency and availability; unknown inputs stay unknown. Deterministic checks must support multiple valid architectures and explain unmet or unverified conditions.

Coach progression: clarify requirements → propose and construct artifact → introduce constraints/failures → defend and revise → consolidate → transfer. Use short speech and visible persistent constraints. Teaching uses bounded derive/scaffold/consolidate hints; assessment/timed mock records clock, pause/resume policy, evidence and debrief without leaking instruction during assessment. Independent rubrics cover algorithm correctness (only when evidenced), architecture reasoning, codebase comprehension and technical communication; abstain on insufficient signal. Persist FSRS review cards with due dates, ratings, scheduler version and transfer links; test time-zone/restart behavior.

## Launch catalog (12)

The appendix names and fully describes six entries; proposed names below for the remaining six are explicit implementation proposals pending authored review, not quotations or completed scenarios. `REPO-DEF-01` occurs in an example and `REPO-EXP-02` is separately called a golden repository; their relationship needs explicit resolution without discarding either capability.

| ID | Title / scope | Source status |
|---|---|---|
| SD-BR-01 | Sliding window/token bucket → distributed API rate limiter | detailed: 100/min/key, four gateways, 5k RPS, 50k RPS failover, multi-region |
| SD-BR-02 | LRU/bounded cache → multi-tier read-through cache | detailed: 25k reads/s, 500 writes/s, 10k simultaneous misses, stale race |
| SD-BR-03 | Bounded queue → distributed worker queue and fair scheduling | proposed; author full constraints, alternatives and checks |
| SD-BR-04 | Heap/top-k → distributed leaderboard and aggregation | proposed; author full constraints, alternatives and checks |
| SD-CORE-01 | Collaborative voice/code session coordinator | detailed: 1k sessions, idempotent execution, isolation, 20k / 12 instances |
| SD-CORE-02 | Reliable outbound webhook and retry platform | detailed: 1,200 events/s, 500 tenants, seven-day retries, fairness and replay |
| SD-CORE-03 | URL shortener under read-heavy traffic and failures | proposed; complete specification required |
| SD-CORE-04 | Notification delivery and fan-out | proposed; complete specification required |
| SD-CORE-05 | Search/autocomplete with freshness and availability trade-offs | proposed; complete specification required |
| REPO-EXP-01 | Golden VIVA architecture and sandbox boundary | detailed; validate all paths and claims against snapshot |
| REPO-EXP-02 | Golden reference event-driven webhook/FastAPI service | named in plan; proposed full exploration map must be authored |
| REPO-DEF-02 | User-imported repository defense protocol | detailed; dynamic evidence-backed map |

The `REPO-DEF-01` VIVA defense example must be supported within the VIVA golden map or as a separately identified exercise; do not silently claim this ambiguity resolved. Both golden repositories must be bundled, sanitized, versioned, available offline and tested, with verified coverage/citations. Plan text varies between FastAPI reference service and event-driven webhook; choose a reviewed reference that satisfies both or document the actual distinction.

## Safe repository and evidence pipeline

Accept curated snapshot, bounded ZIP (plan maximum 50 MB) or constrained public HTTPS shallow clone. Treat all inputs as data: no code, hooks, package installation, submodules or untrusted prompts executed. Defend archive traversal, bombs, symlinks and resource exhaustion; constrain DNS, redirects, IP ranges and network egress against SSRF. Strip/exclude secrets and sensitive files before indexing or model submission; report coverage and exclusions. Build bounded AST and text index with verifiable paths, line ranges, symbols and relationships; do not pretend parsing supports languages it cannot cover. Produce evidence cards distinguishing observed code, explicit documentation, inferred rationale and learner alternative; absent author intent is unknown. Validate citations and do not promote untrusted repository text into instructions.

Export and delete by user/session/repository scope, including raw files, derived snapshots, indexes, evidence, review cards and temporary clones, with a documented backup/retention policy. Require explicit user understanding before external transmission; prevent cross-session/user exposure. Measure p95 latency budgets and repository limits using representative workloads and publish methodology; vendor performance/cost remains a projection until measured. No live provider calls absent fresh authorization.
