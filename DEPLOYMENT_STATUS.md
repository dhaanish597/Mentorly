# Deployment status — 15 November 2026

The web frontend and request-driven API are live at **https://mentorly-coach.vercel.app**. Public custom-code execution remains disabled. This is a tested web/API deployment, not full product acceptance.

## Live release

Current deployment: `dpl_6vzeYLafysF5qAEfKveqbtccFYYu`.

The immutable upload is the sibling directory `release-web-api-speech-20261115`, with its external SHA-256 inventory `release-web-api-speech-20261115.manifest.json`. It retains the previously tested 226-file package and changes only the independently reviewed WebSocket capture revision route. The larger source worktree continues to change and is not this release artifact.

Vercel's root FastAPI function configuration was rejected by the actual build despite the project framework setting. The accepted configuration uses one file-based Python ASGI function at `api/index.py`, Python 3.12, Seoul `icn1`, 2 GB memory, a 300-second maximum, CDN frontend output from `public/`, and a guarded application fallback. Live tests confirmed original API paths survive the rewrite, CDN assets return HTTP 200/HIT, browser deep links load, and unknown API/assets/private-source paths return JSON 404.

## DSA mentor repair

The old fixed category replies ignored the learner's transcript. Replies now use the current transcript and private durable history; repeated follow-up questions are compared independently of introductory phrasing. Saved text is reused by speech. Detection is heuristic, not a guarantee against every semantic paraphrase.

The built-in browser verified three different live model responses: a contiguous-subarray definition, a space/state discussion, and an O(n) explanation that references the preceding constant-space discussion. The same conversation survived refresh. Before release, 51 focused backend and 78 conversation frontend tests passed, with independent scoped reviews. Evidence is in `evidence/dsa-local-fix-20261115/` and `evidence/deployment-candidate-20261115/production-mentor.png`.

## Database and authorization

Supabase project `tryalzyijwegfaowftbq` uses private schema `viva_app`, verified TLS with the official CA, and runtime migrations 0001–0006. The runtime probe passed. The live API created and saved a code version; an independent database query matched that saved source. Missing, invalid and another session's valid tokens returned 401. Deletion of a disposable test session returned 200, and its later read returned 410. Verification with execution disabled produced `EXECUTION_UNAVAILABLE` and zero executed cases. Two other disposable test sessions are left to normal expiration.

The production variables are protected secrets and live outside the repository/upload package. No credentials are recorded in release evidence.

## Voice and remaining execution work

The live fixed voice endpoint returned real 3.6-second Gnani audio at 22,050 Hz. A deployed WebSocket opened, but its first recognition test exposed a pre-allocation revision bug: creating an unchallenged turn advances its generation. The route now binds STT to the allocated revision and checks supersession before saving its result. A strengthened test reproduced the defect before repair; 37 focused speech tests and independent Python/general reviews passed. The repaired live English round trip passed: the 3.6-second clip was transcribed through the deployed WS_V3 route with an exact fixture match and the new capture revision. Total smoke duration was 25.8 seconds, with no STT retry. Human microphone accuracy is not accepted by this synthetic check.

Native Sandbox preparation passed 69 offline tests and independent review. The first public Ubuntu build failed under warning-as-error flags. The minimal repair was reviewed, committed as `8bfc1fb`, and build run `43704424706` passed. Binary, source, build and workflow hashes were independently verified, along with actual ELF dependencies and hardening. The binary is 39,184 bytes; guest loading remains unverified. Native budget/dependency repairs passed 88 focused offline tests. No native learner acceptance has passed. The finite acceptance suite is capped at 32 disposable VMs and remains unrun.

Private cleanup migration 0007 passed independent PostgreSQL/Python review. The local factory and ledger 0008 enforce one job/VM, owner fencing, durable cancellation and conservative 100/day and 500/month creation limits. Independent review prompted fixes for the cancellation route, creation retries and acceptance-harness admission. Final guarded CLI review/tests are pending. Neither migration is remotely applied. The live package keeps the compatible six-migration manifest until the final coordinated release.

## Cost and acceptance limits

Vercel Hobby and Supabase Free, no payment method/upgrade, were inspected in the built-in browser. GitHub's standard public runner is used without Actions artifacts, caches or package storage. No paid service was enabled. Remaining live account usage and provider credit balance need final inspection; historical dashboard observations are not a current billing total.

The earlier release candidate passed 1,390 backend/worker tests (nine genuine gVisor skips) and 880 frontend tests, plus lint, typecheck and build. Current OpenAPI, both TypeScript contracts, the six structural mutation probes and secret hygiene checks pass. The frontend asset hashes still match the live upload. Later native/factory changes require their final backend checks. Full Sandbox, execution/trace/repair, cancellation/recovery and broad speech acceptance remain outstanding.

Evidence: `evidence/deployment-candidate-20261115/production-release.json`, `production-routing.json`, `production-session.json`, `production-persistence.json`, `production-voice.json`, and the external package manifests.
