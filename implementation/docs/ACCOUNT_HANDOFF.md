# Account handoff — local expanded candidate

**Last updated:** 2026-11-14. **Overall IN_PROGRESS**, not complete or promoted. Local only.

## Exact locations / provenance

- Workspace `/Users/dhaanish/Desktop/VIVA`; one active app `/Users/dhaanish/Desktop/VIVA/implementation`; branch `takeover/complete-coach`. Existing uncommitted/untracked work preserved. No git commit/push/remote creation authorized.
- Local authority `/Users/dhaanish/Desktop/VIVA/IMPLEMENTATION_PLAN.md` v2.0.0, all FR-01–22/NFR-01–07 plus explicit user expansion. Historical Drive plan `1EZkHCtkDyMNXw_i8-MoMPSHfZYFYnl4E`, recorded SHA256 `67046fe8c5caaee4a863d4e17a1fdfb5915d741fd2175877730f214ce74a7f74`.
- Historical canonical Drive root `1jWMkdgMfBaTanpQHekR_o9WlxC-lv97D`, implementation `1mmsMOQQ-mbRhmEUawG-AnQs_4NwQZYy5`; secondary root `180tEut_BJOupH4fFUdQMlQ07u1q6a_wq` was a future pointer only. No Drive activity now.
- Original Gemini manifest/bundle `1V1QbCveVYAbn6oVfmpmBsth3ZMWrCi_-` / `1mRQch2vyqGuNzgjaf1_imMFJKvAcHkJ0`; preserved imports `imports/drive-20261113`. Historical278 raw hash checks passed/five native handoffs empty. [SOURCE_INVENTORY.md](SOURCE_INVENTORY.md) retains provenance; parent added only its current local note.
- Final suite `/Users/dhaanish/Desktop/VIVA/evidence/workspace-expansion-20261114/final-checkpoint-checks/`; Python `verified-coverage.json`, frontend `frontend-coverage-verified/coverage-summary.json`, audit `npm-audit-final.json` at that evidence root.
- Expected parent-created local source checkpoint `/Users/dhaanish/Desktop/VIVA/evidence/workspace-expansion-20261114/checkpoint/CHECKPOINT_MANIFEST.json` after docs finish. **Not claimed created by this pass.** Older `local-completion-20261114/checkpoint/PROMOTION_MANIFEST.json` remains its historical identity, not current expanded hashes.

## Final local results / limits

**503 backend PASS,207 worker PASS,120 frontend PASS,9 genuine gVisor/trace/execution SKIPS;17 checks PASS,0 FAIL,4 omitted/external markers.** Typecheck/build/drift/secrets/archive pass. Offline credential-free/omitted-live markers are deliberate; genuine provider evidence separate. Real isolated code evaluation remains blocked.

Python aggregate statement coverage **81.4403149% (7034/8637)**. Frontend **81.05% statements (1703/2101),88.53% lines,77.29% branches,74.00% functions**: statement minimum met for both, not all metrics. Older under-80/mapper snapshots superseded, not averaged or rewritten. Node24.21,Vite6.4.6,Vitest/coverage4.1.12,React plugin4.7.0,DOMPurify3.4.17; React18/Monaco0.57 unchanged. Final npm audit zero all severities/empty vulnerabilities, snapshot only; no forced major transitive override or invented completed Python registry audit.

Wheel-final built and isolated installed-wheel HTTP catalog31 passed using explicit external branding configuration and no repository module-path fallback; provider calls0/learner execution0. Packaging acceptance is not deployed runtime/isolation acceptance.

31 distinct original problems/32 specs, original IDs/specs preserved. Strict int/bool/string/flat scalar-list predictions/results,173 curated64 transfer626 generated,31 examples31 known bugs31 alternatives locally validated by trusted oracle/schema. Final source fixtures AST-only. Earlier120 host-subprocess authored-fixture checks stopped/removed, not accepted behavioral/isolation proof. Actual accepted runtime behavior across all31 pending; original evaluation corpus remains separate.

Public server-owned generic intro/test audio cache has cross-session scope/version/language/voice/model keys; private personalized deletion unchanged. Stale durable HTTP speech replay blocked before audio bytes (28 tests/narrow review). Per-message Replay keyed to artifact/full revision/hint, zero-new-TTS cache playback/late-ack guards tested. **Last two replay-cache bounds/error-eviction fixes remained in finalization at summary cutoff; validate/rerun after source changes before claiming them final.**

## Runtime refresh is BLOCKED_TOOL

Existing URL **http://127.0.0.1:5180/library** is available but the backend loaded earlier source. Browser observations precede final cache/guard/replay/toolchain patches. Layout/core UI evidence is useful, not final-source genuine browser acceptance. Tool classifier outage prevented stop/restart or clearing mobile viewport. User should stop **only owned previews** on8020/5180, or wait for tool service recovery, then relaunch deliberately and validate latest source. No claim the running coordinator contains the latest fixes.

Launch entries: `vcc-expanded-coordinator` (credential-free) and `vcc-expanded-live-coordinator`; workbench5180. Preview storage `data/credential-free-preview`; live browser QA isolated at `data/live-browser-qa`. Live-QA forced deterministic settings are not standard model-enabled startup.

## Exact stable startup alternatives

One coordinator only; stop the old owned instance before switching. Credential-free default/preview strips secrets, uses deterministic coaching/isolated storage and keeps custom execution false:

```bash
/Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python /Users/dhaanish/Desktop/VIVA/implementation/scripts/start_local.py --preview --port 8020
```

Deliberately selected private server configuration (startup itself issues no provider calls):

```bash
VCC_CORS_ORIGINS=http://localhost:5180,http://127.0.0.1:5180 /Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python /Users/dhaanish/Desktop/VIVA/implementation/scripts/start_local.py --env-file /Users/dhaanish/Desktop/VIVA/.env --port 8020
```

Explicit proxy target is required because Vite otherwise defaults to8000:

```bash
VCC_PREVIEW_API_TARGET=http://127.0.0.1:8020 npm --prefix /Users/dhaanish/Desktop/VIVA/implementation/frontend run dev -- --host 127.0.0.1 --port 5180 --strictPort
```

For standard model-enabled startup, user must privately configure **`VCC_GROQ_API_KEY`, `VCC_LLM_MODEL`, `VCC_LLM_PROVIDER=groq`** in selected `.env`; key/model currently missing. Missing configuration gives honest deterministic fallback/no Groq call. Do not confuse live-QA forced deterministic mode with model acceptance.

Explicit file credentials override ambient wrong-account credentials; canonical VCC names beat legacy aliases, placeholders/blank canonical values block fallback. Existing `.env` bytes and0600 preserved. Do not print/source/copy it, pass key values on CLI, expose frontend secrets or publish interpolated Compose output.

Read-only contract checks (do not regenerate expected schemas first):

```bash
PYTHONPATH=/Users/dhaanish/Desktop/VIVA/implementation/backend:/Users/dhaanish/Desktop/VIVA/implementation /Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python /Users/dhaanish/Desktop/VIVA/implementation/backend/scripts/export_openapi.py --check
PYTHONPATH=/Users/dhaanish/Desktop/VIVA/implementation/backend:/Users/dhaanish/Desktop/VIVA/implementation /Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python /Users/dhaanish/Desktop/VIVA/implementation/scripts/check_schema_drift.py --check --self-test
```

Parent owns fresh reruns/checkpoints; never overwrite existing evidence or reassemble imports over local work.

## Genuine browser/provider evidence

Before/light/dark/mobile screenshots and geometry saved under workspace-expansion evidence. Page768/editor432 at1366×768, page900 at1440×900; sticky confirmation/mic/stop,44px footer, themes/reduced motion/mobile tabs retained. Boolean challenge stayed HIDDEN until explicit proposal focus/confirmation; then EXECUTION_UNAVAILABLE,prediction NOT_EVALUATED,zero case counts/no success badge; restore and draft resume retained appropriate evidence/dirty code without stale results. Observations predate final runtime patches.

`browser-voice.json`: Test Voice200/169688 transferred bytes/3.84s WAV,AudioContext553.04→556.88,ended3.873s. Local replay zero speech requests; automated stop~201.7ms after replay start,source.stop1.1ms/ended6.7ms afterclick. Debug software timing, not NFR performance benchmark/physical audible latency/foreground guarantee.

Final provider usage **11 authorized calls,373 TTS chars,27.76 STT seconds +2 unintended dummy-key401 tests =13 total attempts**. Initial8calls189chars19.36s; approved new3calls=syntheticTanglish2(122chars8.4s,7/7 programming tokens/Tamil imperfection)+browserTestVoice1(62chars). Tests corrected MockTransport; work stopped. No further consumption authorized. See [GNANI_CAPABILITIES.md](GNANI_CAPABILITIES.md).

## Required external/user gates / boundaries

No local Docker daemon/no saved SSH targets/no authorized Linux/runsc host: keep custom execution false, no host/ordinary-Docker/AST fallback. Need dedicated accepted host and actual adversarial/cleanup/code/trace/repair/transfer acceptance. Groq key/model missing. No physical human mic/speaker check or study. Evaluation preparation:24 clip slots0 recordings,4 speaker slots0 consent;6–8 classmates still needed. See existing `implementation/evaluation/README.md`; private consent/freeze required, no synthetic replacement.

Full browser/WCAG/hardware/latency/deployed capacity/reserved evaluator/TLS/rollback and final runtime refresh remain open. Same-model independent reviews are not a Codex/cross-model audit. Source checkpoints/docs exclude secrets,DB/backup/sidecars,audio/cache,consent/transcripts. No Drive publication,git commit/push,public publish,sharing change,paid provisioning or submission. No new continuation prompt or planning file.
