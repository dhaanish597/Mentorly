# Local evaluation preparation

Requirements come from the original `GNANI_BUILD_HANDOFF_BUNDLE/IMPLEMENTATION_PLAN.md` §§3.4, 11.2–11.3 and the exact §§14.1–14.2. Templates, mocks, expected outputs and offline normalization tests are not live acceptance evidence.

## Repeatable, data-only checks

From `/Users/dhaanish/Desktop/VIVA/implementation`, using the already available environment (no tool installation):

```sh
/Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python -m pytest backend/tests/unit/test_evaluation_readiness.py -q
/Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python -I evaluation/validate_readiness.py
/Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python -I evaluation/run_code_eval.py
```

Validator exit codes: `0` frozen local metadata ready, `1` invalid metadata or local write error, `2` human data/freeze still pending. Code-evaluator exit codes: `0` accepted observed results, `1` not accepted, `2` accepted sandbox unavailable. Run commands independently; pending gates intentionally return nonzero.

The validator only reads JSON. It never reads audio, contacts providers, verifies real identities/consent authenticity, or executes fixture source. `READY_LOCAL` is metadata readiness, not speech accuracy or verified consent. Review actual local consent and recording evidence separately.

## Exactly what participants and the operator must do

The manifest has **24 planned slots, not 24 recordings**. `spk_01` through `spk_04` are anonymous unfilled recruitment slots, not claims that builders or peers participated. There are six clips per slot, three English (`en-IN`) and three Tanglish (`ta-IN,en-IN`), covering the three original exercises in each language. The original six authored sample texts are prompt material only; human reference fields are empty.

1. Recruit **four distinct consenting humans** comfortable with both language modes. Obtain separate evaluation consent covering purpose, local storage, access, withdrawal/deletion and explicit retention expiry. Do not invent identities, signatures or consent. Keep identity mappings and consent records outside the repository in private local storage.
2. Keep `spk_01`/`spk_02` in development and `spk_03`/`spk_04` in held-out testing: **two speakers and 12 clips per split**. Do not use held-out speakers/clips for prompt tuning. The prepared `split_sha256` fixes slot assignments; filling consent and recording fields does not change it. If a slot cannot be filled, leave the gate blocked rather than silently moving a speaker across splits.
3. Each recruited participant supplies six actual recordings: **three English and three Tanglish** using their slot's prompts. All 24 recordings are still required. Store audio privately outside the repository. No synthetic voices or another STT service can substitute for human ground truth.
4. An authorized human listens to each actual recording and writes the verbatim `reference_text` and exact expected programming `reference_tokens`, preserving numbers, signs, comparators, identifiers, self-corrections and code-mix. Prompt text is not automatically the spoken reference. Set `reference_status` to `HUMAN_REVIEWED` only after review.
5. Work on a **private local copy** of the manifest. For each enrolled slot, enter `participant_status=ENROLLED`, `consent_status=GRANTED`, a relative opaque `consent_ref` within private storage, and timezone-qualified `retention_expires_at`. For each completed clip enter `status=READY`, relative opaque `local_audio_ref`, and SHA-256 of the actual audio bytes. An operator must verify these bytes locally; the JSON validator checks only hash syntax. Never include absolute identity-bearing paths, URLs or participant names.
6. Validate the local manifest, then freeze it **before any held-out measurement**. The freeze writes a new file exclusively, preserves the speaker split and hashes all consent/reference/audio metadata; later edits fail validation. Example, replacing paths with private local locations:

   ```sh
   /Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python -I evaluation/validate_readiness.py /private/local/manifest.json --freeze-output /private/local/frozen-manifest.json
   /Users/dhaanish/Desktop/VIVA/.venv-takeover/bin/python -I evaluation/validate_readiness.py /private/local/frozen-manifest.json
   ```

   Hashes are integrity checks, not proof of authentic humans or consent. Review withdrawal and retention status before each use; delete private recordings/identity mappings as agreed. Re-recording or annotation corrections require a new version/freeze and invalidate the previous measurement basis; never tune on held-out results.

**No upload is part of this workflow.** Neither validator nor code evaluator transmits recordings. Do not upload audio to Gnani or any other service, Drive, Git, artifacts or logs. Provider-backed measurement is a separate explicitly authorized activity with reviewed consent and capacity policy, not triggered here. Public packages contain pending templates and public-safe aggregated reports only, never private audio, transcripts, consent records or identity mappings.

Future authorized speech evaluation must report raw extraction separately from human-assisted post-confirmation accuracy and correction count/time, retain failed/timeout turns in observed denominators, and compare identical clips/model/languages for context ablations. `speech_ablation/run_speech_ablation.py` is an offline authored-text/normalization check, not a human ASR benchmark; it cannot satisfy the 24-clip gate.

## Code evaluation boundary and reporting

`corpora/buggy_implementations.json` contains exactly the 12 original required bug families with exact source hashes, legal trigger cases, expected reference/student outcomes and expected trace predicates. `replay_outcome=PENDING_ACCEPTED_RUNSC` means no actual sandbox replay has been claimed. `corpora/extra_buggy_implementations.json` preserves six displaced useful variants outside the required denominator. The six correct alternatives retain different control flow and code hashes.

All source fields remain strings. **Never execute learner source on the host**, including through `exec`, `eval`, imports, subprocess Python or a fallback runner. The evaluator retains `GVisorSandboxRunner.check_preflight()` and additionally requires `acceptance_verified`; it never bypasses the accepted Linux/runsc trust boundary.

A bug detection requires a confirmed replayed output mismatch or learner exception. Generic `EXECUTION_ERROR`, `INVALID_RESULT`, resource failures, unavailability, timeouts and unconfirmed replay never count as success. The required non-progressing `left=mid` fixture intentionally expects a timeout: this is reported separately and cannot turn the suite green under this policy, even when reproducible. Do not claim 12/12 recall from it. Localization remains `NOT_MEASURED_ABSTAIN` until real accepted-runtime traces are reviewed.

A correct alternative passes only with `NO_FAILURE_FOUND`, no counterexample/error observation, a nonempty completed curated suite, exactly 40/40 generated cases, and both completed-stage markers. Reports distinguish planned totals (12 bugs, at least six alternatives), reports actually observed, executed-case counts, detected/passed counts, false counterexamples, runtime, seed and run timestamp. Evaluator failures preserve zero observations rather than fabricating reports. On the current Darwin host, missing accepted Linux/runsc is a `BLOCKED_EXTERNAL` gate with zero learner executions; do not substitute mock passes for acceptance.

When accepted-runtime evaluation is eventually authorized, save only public-safe actual reports in `evaluation/results/`, with the full invocation, runtime/config/fixture provenance and limitations. No report is fabricated by this preparation workflow.
