# Shared product architecture

## Source and identity
Actual repository: `/Users/dhaanish/Desktop/VIVA`; the requested Documents path was unavailable. Active app remains `implementation/frontend` (React18/Vite6), `implementation/backend` (FastAPI/Pydantic) and `implementation/exec_worker`. `horizon` is a separate reference UI, not the tested application.

Branding is configuration-driven. Baseline was VIVA; another writer changed shared branding/README to Mentorly during this task. Those changes were preserved, not attributed to this implementation. Root restructuring and commits `3604fd8`/`54c0a11` were likewise observed outside this task's tool history. Final engineering integration branch is `engineering/full-product-integration-20261115`.

## Frontend composition
`ProductApp.tsx` routes landing/dashboard/library/collections, curriculum (`/learn`, `/learn/:id`), `/settings`, `/progress`, `/interviews`, and Studio. DSA `App.tsx` preserves its existing versioned code/explanation/verification lifecycle. Studio remains the shared editable design/source workspace; Redrive is embedded in its repository tab.

`state/workspaceSession.ts` adopts or creates the existing Studio workspace capability, keeping learning/interview/progress identity consistent. Capability tokens remain tab-scoped, not URLs. Device audio and speech settings are separate validated stores with same-tab and cross-tab subscriptions. Source changes and opt-out cancel pending capture/playback.

## Persistence and security
SQLite uses WAL, foreign keys, busy timeout, ordered checksummed transactional migrations and existing pre-upgrade backups. Additions are 0014 learning,0015 interviews,0016 Redrive,0017 DSA voice preferences,0018 shared-module speech usage,0019 learning privacy/verified evidence badges,0020 interview privacy,0022 module privacy,0023/0024 anonymous speech budget retention. Version0021 is unused; migration discovery is ordered, not a contiguous-count assumption. No database was wiped or applied migration rewritten after its verified checkpoint.

The learner boundary is the existing expiring workspace capability, not a login/account system. Learning/interview/voice writes reauthenticate after `BEGIN IMMEDIATE`, scope child resources to the owner, and enforce current epochs. DSA still has independent 24-hour session capabilities/revision references; no ownership is inferred from historic seeded profiles. Full account identity and long-term cross-device recovery are not implemented.

Private lesson/interview/Redrive records are deleted with their owning workspace/snapshot using hard-delete cascades and explicit soft-delete/upgrade cleanup. Anonymous paid-use counts/seconds/characters survive cleanup, including uncertain dispatches. Raw microphone/camera recordings are not persisted by default. New API bodies are bounded before parsing; existing admission/rate limits remain active.

## Curriculum and evidence
`app/learning` provides a version1.0.0 catalog of100 authored lessons, pinned session content/hash, prerequisite gates, exact objective answer checks, bounded hints/restarts, durable events and awards. Practice completion is not mastery. Oral/natural-language explanation rubrics remain explicitly unassessed; topic mastery is reported as0 rather than invented.

`learning/progress.py` derives actual attempts, lesson completion, time intervals and study streaks; recommends resume/revision/prerequisite-aware foundations and mapped interview practice. Achievement records have owned source events and uniqueness/guard rules. The unsafe legacy personalized gamification APIs return410; seeded peers/XP are not used by the active dashboard. Existing DSA drafts remain separately labeled drafts, not completed lessons. DSA/Studio/source practice histories are not yet one complete account-wide analytics aggregate.

## Conversations, voice and assessment
`SpeechService`/Gnani adapter/gatekeeper retain Prisma v3 STT and Timbre v3 TTS. DSA, Studio and ModuleVoice use a shared bounded provider slot/accounting boundary; module-specific ownership/revision/epoch checks are retained. `learning_voice` resolves persisted lesson messages/interview questions/Redrive explanations rather than arbitrary client TTS text.

DSA mentor text has a provider-independent endpoint. ActiveConversation focuses one speaker, retains selectable/copyable history, and reveals text against actual WAV/stream playback clocks. Word alignment is estimated, not provider timestamps. Open microphone state does not override audible mentor identity; stop, stale responses, opt-out and deletion are tested.

`app/interviews` has separate deterministic DSA/CS/system-design/defense policies, one current question, bounded answer-dependent follow-ups, server deadlines, neutral acknowledgements and immutable end reports. Recovery links Progress to `/interviews?report=...` and a dedicated authenticated `/api/v1/interviews/reports/{id}` lookup: existing workspace only, consistent read transaction, persisted completed report only, no expiry/completion writes or media/resume changes. Interactive session GET retains its separate timeout behavior. Reports cite exact response evidence and distinguish lexical observations from semantic/code correctness. The generic defense interview does not ingest a repository; source-grounded defense is the existing repository/Redrive workflow. Code snapshots in the new interview runtime are not connected to live worker verification.

`repo_learning` keeps passive sanitized ingestion, parsing/FTS and exact source hashes. Redrive builds a bounded dependency-aware beginner plan and stores observable attempts/checkpoints/revisits. Static name edges are approximate; author intent and runtime behavior are never inferred as fact.

## External release gates
Public learner code execution remains disabled until the existing authenticated Linux/Docker/runsc worker and real acceptance evidence are available. No unsafe host fallback was added. New teaching/interview policies are deterministic; a new fully generative multilingual mentor was not implemented. Interface localization and translated teaching content remain incomplete. Current Gnani live evidence is recorded separately in VOICE_INTEGRATION and TEST_REPORT, not conflated with fixtures.
