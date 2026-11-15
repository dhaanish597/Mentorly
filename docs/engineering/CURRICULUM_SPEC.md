# Versioned curriculum and persistent lesson practice

## Implemented scope

Catalog version `1.0.0` publishes **100 original, independently worked lessons in four tracks**:

| Track | Module | Lessons | Published scope |
| --- | --- | ---: | --- |
| DSA concepts and invariants | `dsa` | 31 | Programming foundations, core DSA, advanced graph/structure concepts and interview patterns |
| Computer science foundations | `cs` | 30 | OS, DBMS, CN, OOP, architecture and software engineering |
| Quantitative, logical, verbal and DI | `aptitude` | 24 | 12 quantitative, 4 logical, 4 verbal and 4 data-interpretation lessons |
| System design HLD/LLD cases | `system_design` | 15 | All eight requested HLD cases, three supporting HLD lessons and four focused LLD cases |

Every published lesson has at least two objectives, a substantive explanation, a worked example, three graduated hints, prerequisites, difficulty, estimated duration and one objective question with a reviewed answer and rationale. All questions currently use string options. Content is authored in English; `language_mode` stores the learner's preference and does not claim translated instruction.

This is comprehensive **topic-heading coverage at a bounded introductory/intermediate lesson depth**, not a complete textbook, problem bank or demonstrated mastery of every subtopic. Each lesson has one objective check; that evidence is inadequate to establish topic mastery. Advanced lessons explain selected mechanisms rather than claiming production implementations or exhaustive advanced algorithms.

## DSA heading coverage

| Requested heading | Published lesson IDs |
| --- | --- |
| Programming foundations | `dsa-programming` |
| Time/space complexity | `dsa-complexity`, `dsa-amortized` |
| Arrays | `dsa-arrays`, `dsa-prefix` |
| Strings | `dsa-strings` |
| Hashing | `dsa-hashing` |
| Two pointers | `dsa-two-pointers` |
| Sliding window | `dsa-window` |
| Sorting | `dsa-sort` |
| Binary search | `dsa-binary-search` |
| Linked lists | `dsa-linked-list` |
| Stacks/queues | `dsa-stack`, `dsa-queue` |
| Recursion | `dsa-recursion` |
| Backtracking | `dsa-backtracking` |
| Trees | `dsa-tree` |
| BST | `dsa-bst` |
| Heaps | `dsa-heap` |
| Tries | `dsa-trie` |
| Graphs | `dsa-graph` |
| Greedy | `dsa-greedy` |
| Dynamic programming | `dsa-dp` |
| Bit manipulation | `dsa-bits` |
| Math algorithms | `dsa-number-theory` |
| Advanced data structures | `dsa-union-find`, `dsa-segment-tree` |
| Advanced graph algorithms | `dsa-topological`, `dsa-dijkstra`, `dsa-mst` |
| Common interview patterns | `dsa-interview-patterns` |

Advanced graph coverage includes DAG ordering, nonnegative shortest paths and minimum spanning trees; it does not yet provide separate SCC, maximum-flow or negative-weight shortest-path lessons. Advanced structures cover DSU and segment trees rather than every balanced tree or persistent structure.

Executable hand-offs preserve the real published specifications:

- `/practice/ex1_shortest_subarray?spec=v1_positive_only`
- `/practice/ex1_shortest_subarray?spec=v2_negatives_allowed`
- `/practice/ex2_binary_search?spec=v1_sorted_with_duplicates`
- `/practice/ex3_max_product?spec=v1_bounded_ints`

Opening these links is not execution evidence and does not award lesson completion.

## CS and aptitude scope

| Domain | Published subtopics |
| --- | --- |
| OS (6) | Processes/threads, round-robin scheduling, paging/TLB, deadlock, mutex/condition predicates, LRU page replacement/working sets |
| DBMS (7) | ACID, composite indexes, dependencies/normalization, joins/NULL/aggregation, lost updates/isolation, WAL recovery, 2NF/3NF/BCNF |
| CN (7) | TCP/UDP/framing, subnet routes, HTTP idempotency, layering, DNS/TTL, TLS identity, flow/congestion windows |
| OOP (4) | Encapsulation/substitution, dependency inversion, polymorphism/composition, Strategy/Observer |
| Architecture (3) | Authoritative state/cache freshness, pipelines/CPI, replication/read-your-writes |
| SE (3) | Unit/integration/E2E scope, measurable requirements, lifecycle/additive migration discipline |
| Quantitative (12) | Percentages, ratios, work rates, average speed, probability, combinations, profit/discount, compound interest, mixtures, divisibility, algebra/ages, geometry scaling |
| Logical (4) | Entailment/countermodels, explicitly ruled sequences, ordering constraints, truth assignments |
| Verbal (4) | Evidence-limited inference, subject-verb agreement, necessary assumptions, vocabulary in context |
| DI (4) | Weighted pooled rates, table contribution, baseline growth, pie-sector quantities |

The verbal corpus is not a full grammar/vocabulary syllabus. DI lessons teach interpretation with worked numeric data; they do not claim a visual-chart exercise generator. OS/DBMS/CN cover the named mechanisms, not every university syllabus chapter.

## System design case studies

The requested cases are `sd-url-shortener`, `sd-chat`, `sd-notification`, `sd-rate-limiter`, `sd-file-storage`, `sd-news-feed`, `sd-video-streaming` and `sd-ticket-booking`. Each supplies a real design prompt, a concrete worked mechanism, evolving requirements, explicit trade-offs and its own **unassessed** explanation rubric.

Additional HLD lessons are `sd-capacity`, `sd-webhook` and `sd-autocomplete`. LLD lessons are `sd-lru`, `sd-parking`, `sd-observer` and `sd-elevator`; rate-limiter and ticket-booking cases also specify guarded low-level transitions.

Studio hand-offs use existing verified scenarios only: `SD-CORE-02` webhook, `SD-CORE-03` URL shortener, `SD-CORE-04` notification and `SD-CORE-05` autocomplete. Cases without a matching Studio scenario link to their persistent lesson practice instead of advertising nonexistent diagrams. No existing Studio scenario or DSA executor is modified.

## API contract

Mount `backend.app.learning.routes.router` under `/api/v1`; the router owns `/learning`. Except `/catalog`, endpoints require `X-Workspace-Id` and `X-Workspace-Token`, verified using existing Studio capability authentication. Write transactions recheck capability expiry/deletion after acquiring the SQLite write lock.

### Public catalog

`GET /api/v1/learning/catalog` returns:

```json
{"version":"1.0.0","tracks":[{"id":"...","module":"dsa","title":"...","description":"...","lessons":[{"id":"...","title":"...","prerequisites":[],"difficulty":"beginner","estimated_minutes":15,"objectives":["...","..."],"explanation":"...","example":"...","hints":["...","...","..."],"practice_url":"...","question":{"id":"...-q1","prompt":"...","options":["...","..."]}}]}]}
```

Private `correct_answer`, rationale and internal lesson metadata are excluded. Worked examples and graduated hints intentionally teach the method; the catalog is practice content, not a secret examination. The validator rejects duplicate lesson/question IDs, dangling prerequisites, cycles, invalid answers and nonexistent executable specification/Studio targets.

### Sessions

- `POST /sessions`: `{lesson_id, mode:"practice", language_mode:string}`. Required prerequisite lessons must have owned verified objective completions; otherwise HTTP 409 without session/event writes.
- `GET /sessions/{id}`: resume the persisted current snapshot. Other workspaces receive 404.
- `POST /sessions/{id}/answers`: `{expected_epoch, question_id, answer:string}`. Strings are trimmed and bounded to 1–2000 characters; numeric/bool coercions, unexpected fields, stale epochs and wrong questions are rejected. Only exact case-folded option equality passes, not a paragraph containing the key.
- `POST /sessions/{id}/hints`: `{expected_epoch}`. At most three hints per run, no completion award.
- `POST /sessions/{id}/restart`: `{expected_epoch}`. Keeps the same session ID and pinned content, increments epoch/run, resets current-run counts/messages, and retains historical answers/events. Prerequisites are rechecked.

Snapshots include `{id,lesson_id,epoch,mode,state,language_mode,catalog_version,content_hash,question,coach_messages,answer_count,hint_count,deadline:null,feedback,report}`. Saved coach messages have `{id,role:"assistant",kind,text}` and stable UUIDs for voice resolution. A hint response also includes `hint`.

Feedback contains `{correct,message,answer_key_revealed}`. Reports contain `{lesson_completed,mastery_awarded:false,summary,explanation_rubric:{status:"unassessed",criteria,reason}}`. Correct answers complete a run; five wrong attempts exhaust it. No natural-language explanation is graded. Explanation drafts are outside this answer contract.

### Progress

`GET /progress` returns `{lessons_completed,attempts,topics_mastered,practice_sessions,interviews_completed,study_seconds,streak,completed_lesson_ids,achievements,recommendations,recent_activity}` from durable owned evidence:

- `lessons_completed`: distinct lesson IDs with correct-answer-backed completion events, not completed UI panels.
- `attempts`: persisted answer-evaluated events across all runs; restarts do not erase attempts.
- `topics_mastered`: always 0 because one objective question is inadequate mastery evidence.
- `practice_sessions`: actual session-started events; restart does not manufacture another session.
- `interviews_completed`: owned completed interview sessions with a durable report and `interview.completed` source outbox; correctness is not inferred.
- `study_seconds`: server-observed intervals between accepted lesson actions, capped at 300 seconds per gap. No client duration claim, background idle time or viewing time is trusted. This is bounded observed activity, not a full study-time measurement.
- `streak`: consecutive UTC dates with answer/hint events or verified interview completion, allowing yesterday as the latest day; views/session creation alone do not count.
- Recommendations prioritize newest resumable sessions, repeated unverified attempts needing revision, explicitly mapped interview practice suggestions, then eligible foundations. Interview lexical gaps are labeled unassessed rather than presented as correctness/mastery findings. Locked suggestions name missing prerequisites.
- Recent activity returns at most 25 actual source events, not seeded history.

## Evidence and achievement rules

| ID | Trigger | Source |
| --- | --- | --- |
| `first_lesson` | First correct objective completion | Owned `lesson.completed` event backed by a correct answer |
| `five_lessons` | Five distinct verified lesson completions | Completion event reaching that threshold |
| `first_interview` | First completed interview with immutable report and outbox | Verified derived `interview.completed` source event |
| `three_study_days` | Accepted answer/hint actions on three consecutive UTC dates | Current owned answer/hint event; SQL independently checks the three-day threshold |

Awards are unique per workspace and ID. Completion and award inserts occur inside the same transaction as their evidence. SQL guards reject caller-source completion, wrong-owner evidence and unbacked awards. Immutable answer/event/award records cannot be updated. Repeated completions cannot inflate distinct lesson totals or duplicate awards.

`record_interview_completion(conn,workspace_id,event)` is an internal coordinator hook. It requires an already persisted owned completed interview, report and completion outbox, and is not exposed as an HTTP endpoint. Coordinator wiring is `app.state.interview_completion_hook = record_interview_completion`. Progress reads the authoritative interview source even when the hook is not installed; first-interview awards require the hook.

## Persistence, versioning and privacy

Migration `0014_learning.sql` creates learning sessions, answers, events, deduplicated lesson achievements and the verified external-event bridge. Sessions pin private lesson JSON, catalog version and a SHA-256 content hash; resume/restart do not consult later answer keys. New published curriculum releases must bump the catalog version.

Additive migration `0019_learning_privacy.sql` leaves 0014 unchanged, adds evidence achievements, purges existing soft-deleted workspace learning data, and installs deletion triggers. Hard workspace deletion cascades learning sessions, answers, events and awards. Studio soft deletion also purges those rows and external evidence. Deleting an interview removes its derived learning event/award. The existing migration runner computes and verifies checksums; no checksum records are manually edited.

Daily protection limits are 100 session creations and 2000 learning event writes per workspace, alongside five answers and three hints per run. SQLite connections are opened and closed within one route worker thread; dependency injection passes a database path rather than moving thread-bound connections between worker threads.

## Verification evidence

Initial tests executed RED with the missing learning package. Expanded-topic tests then exposed missing headings, while privacy/prerequisite/priority/badge tests executed RED against the earlier implementation before their fixes.

Latest narrow validation command:

```sh
PYTHONPATH=implementation/backend:implementation .venv-takeover/bin/python -m pytest implementation/backend/tests/unit/test_product_learning_catalog.py implementation/backend/tests/integration/test_product_learning_api.py -q --cov=backend.app.learning --cov-report=term-missing
```

Result: **41 passed; 95% learning-module statement coverage**. Tests verify every published objective key against all distractors, no pre-evaluation key projection, catalog graph/target validation, capability isolation, strict bounds, concurrent CAS, atomic rollback, durable resume/restart, evidence-derived progress, server prerequisites, soft/hard deletion, interview-source guards, activity timing, and deduplicated badges.

These are unit and real SQLite/API integration journeys. Full browser wiring, executor ownership linking and voice-provider behavior are coordinator-owned verification, not claims made by this suite.
