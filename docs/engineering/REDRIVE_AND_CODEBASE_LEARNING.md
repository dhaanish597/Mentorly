# Redrive and source-grounded codebase learning

## Implemented scope

The repository workspace now offers **Teach me from the beginning** beside the existing defense workflow. Redrive creates or resumes one persisted beginner plan per authorized workspace/snapshot. It reads the existing passive index; it does not import again, execute source, access a repository filesystem, or create uploads.

The lesson sequence is fundamentals → entrypoint candidates → individual definitions/components → visible call expressions → testing/error-handling tradeoffs. A strict pedagogical prerequisite chain exposes one concept at a time. Component file ordering uses the existing repository map’s approximate import-name matching strategy. Cycles have stable traversal ordering; even a long chain does not depend on Python recursion.

Missing topics are omitted. Entry markers currently recognize Python’s `__name__ == '__main__'` guard, JavaScript/TypeScript `createRoot`/`ReactDOM.render`, and Go/Java/main-like declarations in the existing supported source languages. These are candidates, not assertions about deployed startup. Tests require an actual indexed assertion/expectation span; error handling requires an actual `except`/`catch` span. Modules classified as plain text by the existing index do not receive invented code lessons.

## Persistence and API

Export: `backend.app.repo_learning.rederive_routes.router`. Its prefix is **/api/v1/repos**. Mount it without another `/api/v1` prefix.

Every endpoint requires `X-Workspace-Id` and `X-Workspace-Token`, reusing the existing capability authenticator. Live workspace ownership and READY snapshot status are also checked inside the database transaction.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/{snapshot_id}/learning-plan` | No request body; create or resume the workspace/snapshot plan. |
| GET | `/{snapshot_id}/learning-plan` | Resume a previously created plan; 404 when none exists. |
| GET | `/learning-plans/{plan_id}` | Retrieve a workspace-owned checkpoint. |
| POST | `/learning-plans/{plan_id}/answers` | Persist a reviewed comprehension attempt under epoch CAS. |

Answer request:

```json
{"expected_epoch": 1, "answer": "My reviewed explanation"}
```

The epoch must be a strict positive integer; answers must be nonblank strings of at most 4,000 characters. Extra request fields are rejected. A stale epoch or changed source yields 409; invalid/missing capabilities yield 401; foreign plans/snapshots yield 404. Not-ready source yields 409; no available code concepts yields 422. Write/storage limits yield 429.

Response fields are `plan_id`, `snapshot_id`, `snapshot_hash`, `epoch`, `status`, `current_step`, `steps`, `checkpoint`, `revisit_step_ids`, `attempts`, `evidence_events`, and `limitations`. Status is `learning`, `review`, or `complete`; a completed plan has `current_step: null`.

Each step has `step_id`, `phase`, `concept`, `title`, `explanation`, `question`, `prerequisites`, `citations`, `facts`, and `mastery: 'not_established'`. The facts contain identifiable source paths/names, not a mastery answer key. Citations contain exact `path`, `symbol`, `start_line`, `end_line`, and SHA-256 `chunk_hash` fields. The plan also retains its snapshot hash.

`0016_redrive.sql` adds `repo_learning_plans`, `repo_learning_attempts`, and `repo_learning_evidence_events`. Plan creation is naturally idempotent because `(workspace_id, snapshot_id)` is unique. Answer retries deliberately require the current epoch: they do not replay a stale answer into a new lesson. There are at most 500 attempts per plan and 30 answer writes per workspace per minute. Plans contain at most 32 steps, including at most eight component files.

The plan epoch is independent of the existing studio defense epoch. Every accepted attempt increments the learning epoch, including attempts that remain on the same concept. Checkpoints, attempts, revisit queues and evidence events survive server restart in the configured database.

## Grounding, feedback and privacy

Every returned step citation is checked against its indexed span, chunk-text digest, whole-file digest, line range and exact file-text slice. The snapshot hash is rechecked. Changed references fail closed; no answer/event is committed when validation fails. Definitions without an exact indexed symbol span are skipped rather than inventing a span, including equal-line nested component declarations.

Feedback distinguishes:

- `supported_observation`: the requested source identifier/path appears as an exact bounded token in the response, without recognized negation/unsupported certainty. Substrings such as `wrong_app.py` for `app.py`, or `foobar` for `foo`, cannot advance the checkpoint. This advances the teaching checkpoint, not a mastery score.
- `contradicted_by_source`: a narrowly detectable mismatch, such as naming a different real indexed path when the question asks for this citation’s path.
- `unsupported_claim`: recognized claims about author intention/guaranteed runtime behavior that these source facts do not establish. Unsupported is not equivalent to wrong.
- `needs_support`: an attempt that does not provide the requested source fact; it is recorded, not declared incorrect.

Unsupported/unclear/mismatched attempts keep the current lesson active and add the concept to the persisted revisit queue. After the first pass, queued concepts are revisited before completion. All steps/events retain `mastery: 'not_established'`. These are deterministic, conservative lexical checks, not semantic grading, a resolved call graph, or evidence of durable comprehension. Arbitrary wrong claims can remain undetected; correct paraphrases can need another attempt. Advanced runtime, deployment and author-intent conclusions must remain unknown without further evidence.

Imported comments/string contents are not teaching instructions. Detection ignores comment/string syntax; authored explanations/questions do not repeat imported prose. Learner answers are passed through the existing heuristic secret sanitizer before persistence. Secret filtering is not guaranteed to catch every sensitive value. Returned/exported records include source identifiers and sanitized learner prose, never capability tokens.

Foreign/deleted/expired workspaces cannot read plans. Snapshot deletion cascades to all plan/attempt/event rows. The existing authorized workspace-delete API soft-deletes the workspace and hard-deletes its snapshots in the same transaction, which also cascades these private records. Redrive does not add a separate expiration cleanup scheduler; expiry denies access, while physical retention follows the existing workspace/snapshot lifecycle.

## Frontend and voice integration

`features/redrive/RedrivePanel.tsx` validates incoming plan/checkpoint/reference shapes, preserves a draft after a conflict, and offers checkpoint reload. It displays one lesson, a short question, exact line/hash references, recorded attempts and limitations. Citation buttons reuse the existing source browser, highlighting the requested lines. Switching back leaves the existing repository defense state intact. Capability/snapshot changes abort stale work and destroy the old draft/voice instance.

Per the coordinator’s voice seam refinement, the panel uses the shared `ModuleVoice` rather than modifying `StudioVoice`. It passes `module: 'redrive'`, `sessionId: plan.plan_id`, the independent `plan.epoch`, workspace headers, and `messageId: current_step.step_id + ':explanation'`. Recording/transcription only fills the editable draft. Manual **Save comprehension answer** is still required. Voice unmounts during checkpoint mutation/reload, source/capability replacement, conflicts or hidden-panel state. The shared voice layer owns provider availability/preferences, server source-epoch checks and authored-message resolution; expected facts and raw imported content are not coach speech.

A separate `DefenseFollowup` component is integrated with actual recorded defense-phase history and validated citations. Its short prompt varies with the learner’s recorded response; it does not invent a correctness assessment or modify the original four-phase backend defense protocol.

**Export beginner learning record** downloads `redrive-learning-record.json`: `{version: 'redrive-v1', plan, basis}`. It contains the validated plan, citations/checkpoints/events/attempts and the explicit non-mastery basis, without workspace/session capabilities.

## Actual verification and limitations

Tests were written before implementation. Initial backend/frontend RED runs failed on the deliberately missing `rederive` and `RedrivePanel` imports. Additional runtime RED tests reproduced equal-line component-span failure, recursion in a 1,100-file dependency chain, inappropriate advancement on a negated identifier, misplaced test/import citations, and misleading source-name substrings. Those reproductions now pass.

Final verification on the scoped implementation:

- `test_product_redrive.py` plus existing `test_repo_learning.py` and `test_repo_learning_corrections.py`: **97 passed** (19 new Redrive tests). Engine/router coverage: **95% combined**, **94% engine**, **98% router**.
- `productRedrive.test.tsx` plus existing `StudioRepository.test.tsx`: **49 passed**. Redrive feature coverage: **91.24% statements**, **90.33% branches**, **95.74% functions**, **96.96% lines**.
- Full frontend `tsc --noEmit`: passed. Focused ESLint for the new Redrive feature and `StudioRepository.tsx`: passed.

The API tests prove capability isolation, persistence, stale-answer rejection, validation/secret filtering, actual workspace-deletion privacy cascade, revisit/completion behavior, real source anchoring and conservative feedback distinctions. Frontend tests prove reviewed-answer submission, capability/snapshot fencing, conflict draft preservation, source navigation, export token exclusion, and the plan-epoch ModuleVoice props/draft contract.

The Redrive frontend tests mock the shared ModuleVoice boundary; they are not live provider/audio or browser E2E tests. No screen-reader walkthrough, responsive visual audit, real microphone/provider test, deployed-network test, or full runtime source execution was performed in this scoped work. Coverage figures apply to the new Redrive engine/router/feature, not the whole product or the separately owned shared voice implementation. Nothing was committed or branched for this task.
