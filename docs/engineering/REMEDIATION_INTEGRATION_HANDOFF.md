# Audit and Astra integration handoff

15 November 2026. Source: `codex/viva-audit-remediation` at `/Users/dhaanish/.codex/worktrees/viva-audit-remediation/VIVA`. The audit fixes and Astra redesign are implemented in this isolated workstream. Final evidence is listed in `SECTIONS_2_3_4_REMEDIATION_STATUS.md`.

## Integrate only the requested delta

The Git HEAD is `54c0a1100f5894ce70460d68ee21e32a857ba993`, but this checkout inherited 662 source files containing unrelated uncommitted work. A normal Git diff against HEAD includes that inherited work. It is not the task delta and must not be committed or applied wholesale.

The handoff bundle is `/Users/dhaanish/.codex/worktrees/viva-audit-remediation/remediation-handoff`. It contains `task.patch`, `manifest.json`, `base-files/`, `current-files/`, `modified-files.md`, a read-only `verify_target.py`, and test/browser evidence. The exact baseline is the sibling `remediation-baseline/files`, with its original manifest and source status. Each changed path has baseline and final SHA-256 hashes. The bundle contains only changed files and the corresponding originals, not the whole source snapshot.

The deployment checkout is `/Users/dhaanish/.codex/worktrees/viva-zero-cost-deploy/VIVA`. It remains independently owned by the deployment chat. No files, branches, sessions or ports in that checkout were changed by this remediation.

1. Inspect deployment Git status and current sources before integration. Run `python3 /absolute/path/to/remediation-handoff/verify_target.py /absolute/path/to/destination` for a read-only classification of unchanged baseline files, already applied files and conflicts.
2. Review `task.patch` and the modified-file manifest. In an isolated integration copy, `git apply --check /absolute/path/to/task.patch` checks clean applicability without writing files. Apply only after reconciling current edits. A hash conflict may be non-overlapping text; it still requires comparison. Do not overwrite newer files from `current-files/`.
3. For conflicting files use `base-files/<path>` as the exact common source, `current-files/<path>` as this task's version, and the destination file as the deployment version. Preserve independent deployment changes, staging and ownership. Never use HEAD as a substitute for this uncommitted baseline.
4. Regenerate the two frontend type systems from current backend source and rerun the backend/worker, actual disposable PostgreSQL, frontend, schema, secret and build checks after integration. This worktree's test results do not attest to the combined deployment candidate.
5. Follow `POSTGRES_RUNTIME_OPERATIONS.md` for private reconciliation, migration, backup, cutover and rollback. Never point test DSNs or transfer tests at a production database.

No merge, push, commit, production migration or deployment was performed by this task. No future deployment time was scheduled. The user deferred deployment while the separate deployment workstream runs; this is its reviewable source handoff.

## Astra changes and verified root cause

`audioRecorder.pushFloat32Frame` previously treated every frame with RMS >= 0.02 as speech. `App` passed that activity to `stopAudioPlayback` while processing or speaking. Draining audio left the microphone graph live, so fan noise, spikes and mentor speaker echo could abort playback. The combined Cancel / Stop Audio control also cancelled the complete turn.

Capture now closes before provider submission/playback. Browser-supported echo cancellation, noise suppression and gain control are requested and actual track results are displayed honestly. A conservative 20-ms detector uses frequency-band/envelope variation, adaptive ambient estimation and sustained activity rather than volume alone. Speech detection, the 10-second quiet timer and explicit mentor interruption are separate. Unsupported or ambiguous conditions retain manual Send Voice. Automatic full-duplex barge-in is not claimed; users interrupt through Stop Audio. Cancelling a turn remains an explicit separate action.

A right-side `ActiveConversation` renders actual learner and mentor messages, full text during TTS, timestamps, stable IDs, draft status and independent scrolling. The left panel contains Astra and voice controls. The result pane appears as Transcript initially; genuine execution requests enable Evidence/Session. Current session, code hash and code-version IDs prevent old evidence representing newer code. Unavailable execution is explicitly labelled and never described as a successful run. Transcript history survives view switching and session restoration.

## Check the local application

From the isolated `implementation` directory start the backend with `python scripts/start_local.py --preview --port 8137 --frontend-port 5273 --no-reload`; from `implementation/frontend` run `VCC_BACKEND_PORT=8137 VCC_FRONTEND_PORT=5273 npm run dev -- --host 127.0.0.1`. Use these independent ports only if still free. Open `http://127.0.0.1:5273/library`, choose a problem, and send a text explanation from the right-side text controls. Check that real response text appears, Evidence is absent, and identical new drafts remain labelled unsent. Submit code, inspect the actual result or unavailable state, and return to Transcript. Verify mobile Coach and Results navigation and independent scroll.

Preview intentionally has no provider credentials or execution worker. For a separately authorized real microphone/Gnani acceptance, select a supported microphone and language, speak a response with fan noise, allow ten seconds of quiet, and verify one submission. During mentor audio test fan/keyboard/echo without a false stop, then use Stop Audio and start a new response. Repeat on Chrome and Safari. Record real device/browser, supported constraints, provider quota and measured outcomes. Do not treat synthetic fixtures as that acceptance.

## Remaining external acceptance

Real microphone accuracy, live STT/TTS and model semantics, supported language quality, verified account capacity, genuine Linux/gVisor custom execution, deployment worker lifetimes and production cutover remain unverified. Custom learner execution remains disabled; Gnani effective concurrency remains one unless entitlement is explicitly verified. The cache is disposable; authoritative progress and recovery use database durability. PostgreSQL retains serialized write semantics and is not a throughput or serverless guarantee.
