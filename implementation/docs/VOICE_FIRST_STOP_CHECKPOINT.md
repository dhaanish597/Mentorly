# VIVA — safe stop checkpoint

**2026-11-14 · Stopped at the user's request. Implementation preserved; manual QA pending. This is not full Phase 1/2 release acceptance.**

## Source and recovery

- Horizon implementation: `/Users/dhaanish/Desktop/VIVA-Codex-next-phase/implementation`.
- Branch: `codex/viva-horizon-system-design`.
- Committed HEAD: `d43861e14df09731e1f277e0f4745fe41fa6bab6`.
- Codex Phase 2 and this continuation's changes remain **uncommitted**. No reset, stash, branch switch, merge, push, or promotion into the original application was performed.
- Before editing, 302 first-party files were preserved in `../coordination/recovery/voice-ui-20261114/source-before-ui.tar.gz`, with SHA-256 manifest; credentials, databases, and dependencies were excluded.
- All assigned writers finished. The final background check completed; no implementation or test work from this session remains running.

## Why localhost:5180 still shows the old UI

At stop, `lsof` verified Node PID 84179 on **5180**, working directory `/Users/dhaanish/Desktop/VIVA/implementation/frontend`. Its coordinator was running on **8020**. This is the independently maintained **original checkout**, not the Horizon checkout.

The redesigned checkout is configured for **5300** frontend and **8095** credential-free API. Neither port was listening; HTTP probes returned no response. Earlier Codex port 5290 was also offline. Refreshing 5180 cannot load edits from the separate folder. Original servers were not stopped.

## Implemented and preserved

- Original Horizon mentor PNG restored from the unchanged ZIP; locally hosted licensed Inter, Lora, and JetBrains Mono fonts.
- Illustrated landing, shared plum shell/navigation, real-data dashboard/library/paths/progress; no fake XP, testimonials, demo passwords, or heuristic judging.
- Coding arena: mentor left, tabbed problem/code workspace right, dark editor, contextual hints/transfer controls, prominent microphone, and existing confirmation/revision/session/execution-evidence safeguards.
- Studio: all 12 authored scenarios, one explanation composer, visible Gnani adapters, compact Help, synchronized graph/table, selected-entity properties, assumptions, undo/redo, revisions, proposals, timers, review, and deletion.
- Speech consent, 25-second capture boundary, editable drafts, cached replay, interruption/current-callback safety, fresh-epoch speech, and authenticated feedback/repository prompt events.
- Transcript correction/supersession, model recovery/purge, bounded speech admission/provider deadlines, evidence freshness, and corrected teach-back/transfer progression.
- Passive repository indexing with symbol-aligned citations; owner-scoped retry quotas; DNS/IP/TLS controls; actual bounded ZIP decoding; upload/download deadlines; JSON/YAML secret redaction; import cancellation and derived prompt-event deletion.
- Generated full OpenAPI definitions, legacy contract drift checks, patched Vite/Vitest tooling, and strict hook/accessibility lint.

Key frontend: `frontend/src/ProductApp.tsx`, `components/LandingPage.tsx`, `components/ProductShell.tsx`, `App.tsx`, `horizon.css`, `StudioApp.tsx`, `StudioVoice.tsx`, `StudioRepository.tsx`, and cohesive Studio helpers. Backend: `backend/app/studio/`, `backend/app/repo_learning/`, startup/lifecycle integration, and additive migrations 0007–0012.

## Completed checks and limits

- Final frozen backend/worker run: **916 passed, 9 skipped**, aggregate Python statement coverage **87%**. Skips require genuine Linux/Docker/runsc and cannot pass on this macOS host.
- Last frontend run: **338 passed in 23 files**. Coverage: statements **81.47%**, lines **89.76%**, functions **80.29%**, branches **77.31%**. Branch coverage remains below 80%; no modules were excluded to manufacture a pass.
- Last completed lint, typecheck, production build, OpenAPI equality, legacy drift/self-test, generated contracts, and secret hygiene checks passed. Final editor-font wiring was not subsequently browser-verified; no additional checks were started after the stop request.
- Saved full dependency audit: **zero vulnerabilities**. The scoped estree/minimatch override should be reassessed when upgrading the parser. ESLint 9's deprecation notice is a maintenance concern.
- Scoped independent reviews and offline tests closed the identified UI/lifecycle/ingestion defects; this is not comprehensive production-security certification.
- An earlier combined Python run overlapped a short repository refactor and imported an intermediate module; the fresh-process run after freezing source produced the 916-pass result.

**Still unverified:** current browser visuals/screenshots, complete responsive/device/screen-reader QA, real microphone/speakers, live Gnani/Groq quality, real gVisor learner execution, deployed smoke/capacity, representative cold performance, and full normative requirement acceptance. Previous Codex screenshots are historical—not proof of the current redesign. No new live provider calls or weaker execution fallback were introduced.

Browser startup hit the app's five-other-chat-server limit. The user indicated they would free a preview; this session did not stop unrelated servers, change permissions, or bypass that limit. The new ports were still offline at stop.

## Launch only when the user chooses to resume

The isolated root's `.claude/launch.json` has:

- `viva-codex-ui-coordinator` — API 8095, credential-free.
- `viva-codex-ui-workbench` — frontend 5300, API proxy 8095.

Equivalent commands in separate terminals:

```bash
cd /Users/dhaanish/Desktop/VIVA-Codex-next-phase/implementation && .venv311/bin/python scripts/start_local.py --preview --port 8095
```

```bash
VCC_PREVIEW_API_TARGET=http://127.0.0.1:8095 npm --prefix /Users/dhaanish/Desktop/VIVA-Codex-next-phase/implementation/frontend run dev -- --host 127.0.0.1 --port 5300 --strictPort
```

Then visit `http://127.0.0.1:5300/`. These instructions **do not mean the servers are running now**. Preview mode deliberately disables live provider credentials and public custom-code execution. Live speech requires deliberate private configuration and authorization; never copy keys into frontend variables or reports.

Migrations 0011/0012 are now frozen. If a disposable QA database used an earlier uncommitted 0012 checksum, use a fresh disposable database; do not rewrite recorded checksums or discard real user data. Browser drafts/capabilities from 5180 do not automatically transfer to the separate 5300 origin.

## Manual QA / continuation

1. Correct checkout: landing/dashboard/library/paths/progress/studio; desktop/mobile, keyboard focus, zoom, and overflow.
2. Coding: edit/save/resume, spec changes, transcript/prediction confirmation, hidden evidence, retry/trace, unavailable-runtime messaging.
3. Studio: graph/table, connect/select, attributes, undo/redo/restore, hints/constraints, correction after Help, teach-back/transfer, timer/review/export.
4. Repository: import/index/citations, Derive/Defense, bound-snapshot resume, requirement change, hidden-panel drafts, deletion.
5. Separately authorized live speech and Linux/runsc checks; remaining human/performance/deployment acceptance.

Do not begin future CS/aptitude/reasoning/verbal curriculum or automatically integrate into the original checkout.

## Combining work later

Read-only comparison: `../coordination/workstreams-voice-ui.json`. It is observational/non-atomic, not merge authorization. Overlaps were found in `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/App.tsx`, and `frontend/src/components/WorkbenchComponents.tsx`. Preserve original-only changes; integrate deliberately and regenerate dependencies instead of overwriting either folder wholesale.

**Next exact action, only on a new user request:** start the isolated API/frontend and inspect port 5300. Do not resume coding, testing, reviews, or integration automatically.
