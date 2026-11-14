# Gnani capabilities and observed evidence

**Last updated:**2026-11-14. Overall **IN_PROGRESS**. Protocol success, synthetic token checks, software playback and human/device acceptance are distinct.

## Language / transport / playback coverage

| Capability | Implemented/tested owner | Genuine evidence | Unverified boundary |
|---|---|---|---|
| English REST STT | `backend/app/speech/{gnani_adapter,service,audio_utils,ast_keyterms}.py`; prisma-v3.0 `/stt/v3` transcribe16kHz mono/context bias | Authorized English REST transcription | Human accuracy/all31 problems/devices/turn medians |
| Tanglish REST STT | Same modules plus transcript_normalizer; `ta-IN,en-IN`,codemix,raw+normalized editable confirmation | Actual Tamil-English synthetic batch,7/7 exact raw programming tokens | Tamil token imperfection; no human Tanglish benchmark |
| English/Tanglish WS STT | `ws_streamer.py`,`routes.py`,frontend speechStreaming/audioRecorder; bounded auth PCM/pacing/commit | Genuine WS handshake,PCM,commit,transcript; both languages selectable | All language×exercise×device combinations/endpointing matrix not observed; no full duplex |
| SSE TTS / streaming PCM | `gnani_adapter.py`,`pre_tts_normalizer.py`,`tts_cache.py`; timbre-v3.0 `/api/v1/tts/sse` | Genuine SSE PCM reconstructed into valid WAV; synthetic code-mix `language=auto`/Avinash | Pronunciation/comprehension/deployed first-audio medians |
| Complete WAV/cache playback | frontend audioPlayer; scoped authenticated fetch/ack | Test Voice200,3.84s actual WebAudio; subsequent replayzero new requests | Physical audible speaker/foreground latency not guaranteed |
| Capture/permission/RMS | frontend AudioWorklet/audioRecorder; REST/WS/resampling/typed fallback | Offline service tests and setup UI | No actual human microphone check; hardware/browser matrix pending |
| Per-message Replay | artifact/full revision/hint keyed browser cache/late-ack gates | Local tests: cache replayzero TTS,older hints cannot advance on late ack | Final2 bounds/error-eviction fixes pending validation; final patched-runtime refresh BLOCKED_TOOL |

Paths above speech-relative modules are under `implementation/backend/app/speech`; frontend services under `implementation/frontend/src/services`. Tests: backend speech foundation/takeover/configuration/cache/freshness/provider/tanglish/voice-introduction and frontend audio/streaming/Replay/lifecycle tests in [FEATURE_COVERAGE.md](FEATURE_COVERAGE.md).

## Final exact provider accounting

Evidence root `/Users/dhaanish/Desktop/VIVA/evidence/expanded-coach-20261114/`:

1. `gnani-provider-aggregate.json`: initial **8 authorized actual calls,189 TTS characters,19.36 STT seconds**,zero retries/uncertainty;3 TTS,4 REST STT,1 genuine WS STT,3 cache replays.
2. Separately disclosed **2 unintended dummy-key401 RED-test requests** reached provider before missing MockTransport was corrected. Stopped/fixed; not canonical-key acceptance. Initial total10 transport attempts. Earlier WS candidate counter included local rejection; aggregate preserves correction and WS-final genuine success. Never hide unintended requests.
3. Fresh user-approved second batch ceiling<=3 requests/300 chars/15 STT seconds: **3 actual requests** = synthetic Tanglish TTS+STT2 (`gnani-tanglish-synthetic-batch2.json`:122chars,8.4sSTT) + browserTestVoice1(**62chars**). Raw exact case-insensitive Latin programming tokens nums,sum,target,left,index,negative,answer7/7; imperfect Tamil recognition. `PASS_SYNTHETIC_CODEMIX`,not human accuracy. The synthetic STT960ms/TTS3123ms are single samples,not NFR medians.
4. Subsequent local browser replay made **zero additional speech/TTS calls**. Final cumulative authorized usage **11 calls,373 TTS chars,27.76 STT seconds**; including dummy tests **13 total attempts**. Provider work stopped; no further retries/prewarm/upload/calls authorized.

The historical one-TTS401/no-STT `../../evidence/claude-takeover-20261113/gnani-live.json` remains historical; later success supersedes current entitlement status without rewriting old reports.

## Genuine browser software evidence — not hardware acceptance

Verified parent artifact `../../evidence/workspace-expansion-20261114/browser-voice.json`: server-owned Test Voice receivedHTTP200,169688 transferred bytes,valid3.84s audio. AudioContext advanced553.04→556.88,ended3.873s. Local replayzero requests. Automated stop clicked~201.7ms after replay start; source.stop1.1ms afterclick,ended6.7ms afterclick.

These are instrumented browser scheduling/completion/cancellation observations, **not NFR performance benchmark, physical audible interruption or guaranteed foreground/device timing**. No human mic/speaker check or human study. The fixed test message does not establish the revealed-artifact coaching branch; that still requires accepted isolated execution.

**Runtime refresh BLOCKED_TOOL:** browser observations predate final backend cache/HTTP guard/browserReplay/toolchain patches. Existing5180/library preview uses earlier-loaded backend; no claim final-source genuine browser acceptance. Tool classifier outage prevents service stop/restart/viewport reset. User must stop only owned8020/5180 previews or wait for recovery,then use exact startup in [ACCOUNT_HANDOFF.md](ACCOUNT_HANDOFF.md).

## Cache / freshness / privacy / credentials

Server-owned public generic intro/test bytes may be cached across sessions only with explicit public scope/version/language/voice/model keys; two sessions/one mocked synthesis tested. Personalized payloads remain session-scoped, and private session deletion preserves only public bytes. Durable HTTP speech-idempotency replay checks current revision before audio bytes; old same-key/body after code change returns409/zero synthesis (28 tests/narrow review). Per-message browser Replay keys artifact/full revision/hint,zero extra TTS/late-ack isolation; final2 bounds/error-eviction fixes were still being finalized at cutoff and require validation/rerun before final claims.

One coordinator/single dispatcher/durable reservations; cache replay incurs no new call budget. Unknown post-dispatch failures retain uncertain upper bounds; HTTP rejection and post-upgrade WS schema failure remain distinct. Tariff/remaining credit/provider retention/production capacity/full duplex remain UNKNOWN/UNVERIFIED.

Only deliberate `--env-file` selects server secrets. File credentials override ambient wrong-account credentials; canonical `VCC_GNANI_API_KEY` beats alias `GNANI_API_KEY`; blanks/placeholders do not fall through. `.env` bytes0600 preserved,never displayed/copied into docs/source/archives. Previewcredential-free. Standard Groq path requires private `VCC_GROQ_API_KEY`,`VCC_LLM_MODEL`,`VCC_LLM_PROVIDER=groq`; key/model missing,deterministic fallback/no Groqcall. Live-QA forced deterministic mode is not model-enabled standard startup.

STT response IDs may echo client correlation: not independently provider-generated IDs. TTS provider ID absent/null,confidence nullable/not calibrated. No fabricated identities/confidence/tariff conversion.

## Human evaluation remains pending

Manifest preparation is **24 clip slots/zero recordings;4 speaker slots/zero consent**, not actual participants. Four consenting English/Tanglish speakers and6–8 classmates needed. Existing `implementation/evaluation/README.md` provides private validator/freeze and speaker-disjoint procedure. Actual consent/human reference annotations/retention are separate; synthetic speech is not ground truth. Raw/post-confirmation accuracy,pronunciation/device/browser medians and user study remain unverified.

No audio,personal transcripts,live DB/cache,consent/identity records or secrets in these docs/source snapshots. Local only:no Drive/public publication,git commit/push,paid provisioning or submission.
