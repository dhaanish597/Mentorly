# Voice integration

## Coordinator live evidence — 2026-11-15

`GNANI_PROVIDER_SMOKE.json` records a PASS using four physical provider calls, zero retries,63 TTS characters and12 seconds of STT upload: Timbre SSE/WAV synthesis, cache replay, Prisma English REST STT, Tamil-English codemix REST STT and WebSocket STT. The same synthesized English clip supplied all recognition inputs; this is genuine provider protocol evidence, not Tamil acoustic quality or human microphone validation. A subsequent real browser lesson request to `/module-voice/lesson/.../tts` returned200 and played through the shared frontend. The real DSA `/speech/introduction` request also returned200 with its correct conversation caption. Other language/voice-quality and natural-microphone checks remain unverified. Account tariff/credit balance remain unknown.

## Evidence and scope

This integration uses Gnani Prisma `prisma-v3.0` for STT and Timbre `timbre-v3.0` for TTS. Provider documentation is evidence of advertised capabilities, not evidence of this account's credit, entitlement, latency, accuracy, voice quality, or live connectivity. No billable provider probes were run by the speech implementation agent. A bounded live smoke, if authorized, belongs to the coordinator and must be reported separately.

Primary references:
- [Prisma v3 model and languages](https://docs.gnani.ai/api/STT/models/prisma-v3.md)
- [REST STT](https://docs.gnani.ai/api/STT/speech-to-text.md)
- [WebSocket STT](https://docs.gnani.ai/api/STT/stt-websocket.md)
- [Timbre voice catalog](https://docs.gnani.ai/api/TTS/available-voices.md)
- [SSE TTS](https://docs.gnani.ai/api/TTS/tts-sse.md)

See [LANGUAGE_SUPPORT_MATRIX.md](LANGUAGE_SUPPORT_MATRIX.md) for advertised versus tested support. A spoken-language preference does not translate authored English coach text or localize the interface.

## Public registry and request selection

The existing exported `backend.app.speech.routes.router`, mounted under `/api/v1`, adds `GET /speech/capabilities`. The response contains locale labels, model IDs, the compatible voice IDs, the three product-enabled code-mixing modes, defaults, and capture limits. `documented: true` and `config_tested: true` mean catalog/configuration tests, while `live_unverified: true` and `provider_verified: false` remain explicit. `configured` only reflects a non-placeholder backend credential. No credentials, balance, headers, private session data, or provider probes are returned.

Backend exports in `backend.app.speech.capabilities`:

- `resolve_tts_language(language_mode, spoken_language=None)` returns a declared locale; legacy mixed STT falls back to the documented TTS script detector `auto`.
- `resolve_tts_selection(language_mode='en-IN', *, spoken_language=None, voice=None, model='timbre-v3.0', default_voice='Avinash')` returns `{language, voice, model}` and rejects unsupported voices/models instead of substituting silently.
- `session_tts_selection(session, *, model='timbre-v3.0', default_voice='Avinash', language=None, voice=None)` understands optional persisted `voice`/`spoken_language` columns and old rows.
- `speech_capabilities(settings=None)` produces the public registry without I/O.

`CreateSessionRequest` and `CreateSessionResponse` add optional `voice` and `spoken_language`; old requests and English/Avinash defaults remain valid. Session persistence and snapshot wiring are coordinator-owned. `TTSRequest` validates the v3 model, thirteen v3 voices, and ten locales plus documented `auto`. Playback and fixed/conversation DTOs accept optional language/voice selectors. Studio `TTSBody` accepts optional declared `language` and `voice`; STT's locale remains independent.

All legacy `SpeechService` TTS paths—ordinary coaching, streaming, fixed introduction, fixed voice test, and conversation—resolve the session's spoken language and voice. Request overrides are validated before dispatch. Studio TTS uses the same resolver and only synthesizes stored, validated event text, never arbitrary client text.

## Frontend contracts and consent

`frontend/src/voice/languages.ts` exports:

- `SPEECH_LANGUAGES`, `TTS_VOICES`, `CODE_MIXING_LANGUAGES`;
- `SpeechLocale`, `ProductLanguageMode`, `TTSVoice`, `SpeechSelection`, `ResolvedSpeechSelection`, `SpeechCapabilities`;
- `isSpeechLocale`, `isTTSVoice`, `resolveLanguageMode`, `resolveSpeechSelection`, `fetchSpeechCapabilities`.

`resolveSpeechSelection` produces `language_mode`, `spoken_language`, `language`, `voice`, and `model`. `fetchSpeechCapabilities(apiBase='/api/v1', signal?)` fetches only the application's backend registry, validating the external response before use. The provider API key never enters browser state.

`preferences.ts` preserves all existing `AudioPreferences` exports and defaults. It adds independent `SpeechPreferences` for `interfaceLanguage`, `sttLanguage`, `spokenLanguage`, `codeMixing`, and `voice`, with `DEFAULT_SPEECH_PREFERENCES`, `loadSpeechPreferences`, `saveSpeechPreferences`, `updateSpeechPreferences`, and `subscribeSpeechPreferences`. `subscribeAudioPreferences` is also exported. Subscribers receive the current normalized value immediately, same-tab successful saves synchronously, and cross-tab storage changes; cleanup removes listeners. Malformed or denied storage uses safe defaults or a false persistence result. Only device preferences are persisted: no audio, code, transcript, or credential.

Existing `StudioVoice`—used by Studio and Codebase workflows—now subscribes to both preference groups, sends the resolved STT language, and sends nondefault spoken-language/voice TTS selectors. Default selectors are omitted to preserve the old optional-payload contract; the backend resolves the session defaults. Text-only prevents cloud speech and microphone capture; mute, zero volume, and disabled output prevent TTS. Volume/speed apply to the actual HTML audio element locally. Changed speech selection cancels pending capture/transcription/synthesis, fences late responses, and revokes incompatible cached audio.

Explicit microphone and coach-speech consent remain separate, scoped to a session capability, and are not inferred from saved preferences. ASR only updates the editable parent draft; it never confirms or submits reasoning. Capture still stops at 25 seconds. Studio replay URLs are capped at 12 entries and 8 MiB total; eviction and session/epoch/unmount cleanup revoke object URLs. Genuine media failures evict audio; browser `NotAllowedError` retains otherwise valid audio for an explicit cached replay gesture. `onPlaybackStateChange(playing)` becomes true only after `HTMLMediaElement.play()` starts playback, and false on end, stop, invalidation, or disabled preferences. StudioMentor drives Nexus's speaking portrait from that callback, not network busy state.

`POST /sessions/{sid}/conversation/text` returns the same authored contract question as conversation TTS, independently of provider availability. It returns `{text, turn_id, revision, source:'authored_public_contract'}`, checks the current learner turn/revision, and performs no execution, claim confirmation, hidden-case access, or provider call. Durable transcript/history persistence remains coordinator-owned.

## Quota, cancellation, framing, and parsing

All provider work shares the coordinator's single-slot bounded dispatcher. Studio and common modules reuse `backend.app.studio.speech.speech_slot`; there is no second independent provider semaphore. `accounted_speech_totals(connection)` aggregates legacy, studio, and common-module STT seconds/TTS characters. Admission and daily physical-call budgets include `usage_reservations`, `studio_speech_usage`, `module_speech_usage`, and deletion-retained daily request counts where applicable, inside SQLite `BEGIN IMMEDIATE` transactions. Anonymous `module_speech_deleted_totals` duration/character aggregates are added across all dates to preserve the existing lifetime audio budgets after deletion; daily request-count accounting remains separate and is not double-counted.

Successful TTS reserves and records one physical provider call per speakable segment. A 429 retry must re-admit its additional physical calls against the shared daily budget; known rejections retain their call count without asserting billed audio. Retries are bounded and cannot replay partially emitted audio. Cancellation, lost acknowledgements, and malformed post-dispatch results retain conservative uncertain upper bounds instead of refunding unknown work. The existing capacity DTO retains logical utterance counts for backward compatibility; physical counts live in `request_count` ledger/reservation fields. Cache hits require zero provider calls. Provider billing/tariff remains unverified; these are local budget counters, not currency accounting.

Studio provider awaits poll client disconnection, cancel and await the underlying adapter, retain uncertain dispatched usage, and release the shared slot only after cleanup. Epoch/revision fences protect late responses; browser AbortControllers suppress obsolete playback/draft updates.

REST STT requires a present string `transcript` or legacy declared `text` field (empty silence is valid); missing fields, generic `result`, wrong types, oversized text, or failure envelopes are rejected. WebSocket transcript events require text and an explicit boolean final flag; speech-start utterance IDs now join the pending set, preventing a delayed second utterance from being dropped after the first transcript.

Both frontend PCM framing and backend buffered/live relay enforce the physical 960,000-byte, 16-kHz mono PCM16 capture boundary. The last boundary frame is 512 bytes rather than padding to 960,512 bytes. Other frames retain 1,024-byte framing and paced upload. This exact final-short-frame behavior is covered by mocks, not validated against a live provider; vendor docs describe 1,024-byte frames. No full-duplex or word-timestamp capability is claimed.

## Test-first evidence

Journeys derived from the implementation request: independent language/voice selection; safe defaults and subscriptions; authenticated text without a provider; correct multisegment/retry budgets; strict transcript parsing; delayed WebSocket utterance retention; and Studio consent/preference/replay lifecycle.

RED evidence:
- `test_product_voice_capabilities.py` plus `test_product_voice_accounting.py`: 23 expected failures before implementation (new locales, voice/model validation, registry, required transcript fields, segment accounting, quota-safe retries).
- `productVoiceLanguages.test.ts`: intended missing `voice/languages` implementation import failure before implementation.
- `test_product_voice_propagation.py` and common-module accounting: 13 intended propagation/route/budget failures before implementation.
- `test_product_voice_websocket.py`: 5 expected failures showing 960,512-byte padding, dropped delayed utterances, and missing final flags.
- `productStudioVoicePreferences.test.tsx`: 5 expected failures before Studio integration; `productStudioVoicePortrait.test.tsx`: missing actual-playback portrait binding.
- Studio disconnect timing regression failed before its request-disconnect poll was added.

Final verified commands (working directory `implementation`, interpreter `.venv-takeover/bin/python`):

```sh
python -m pytest backend/tests/unit/test_product_voice*.py backend/tests/unit/test_speech*.py backend/tests/integration/test_speech_http_acceptance.py backend/tests/integration/test_studio_speech.py backend/tests/integration/test_voice_conversation.py backend/tests/integration/test_voice_introduction.py backend/tests/integration/test_generic_voice_cache.py --cov=backend.app.speech --cov=backend.app.studio.speech --cov-report=term-missing -q --tb=short
```

Result: 231 passed; aggregate speech + Studio speech coverage 88%. Capabilities 100%, service 99%, gatekeeper 93%, provider adapter 84%, WebSocket relay 83%, Studio speech 82%. The pre-existing disk-cache module is 79% in this focused target; aggregate exceeds 80%. Provider exceptions, cleanup, and partial protocol paths remain coverage gaps.

Frontend working directory `implementation/frontend`:

```sh
npm test -- src/__tests__/productStudioVoicePortrait.test.tsx src/__tests__/productStudioVoicePreferences.test.tsx src/__tests__/StudioVoice.test.tsx src/__tests__/productVoiceLanguages.test.ts src/__tests__/voicePreferences.test.ts src/__tests__/voiceStreamingPreferences.test.ts src/__tests__/speechStreaming.test.ts --coverage --coverage.include=src/StudioVoice.tsx --coverage.include=src/voice/preferences.ts --coverage.include=src/voice/languages.ts --coverage.reporter=text
npm run typecheck
```

Result: 113 passed; 95.82% aggregate statements, 91.69% branches, 100% lines; TypeScript clean. Tests include real middleware and mocked provider boundaries, not a live microphone/browser/device E2E or billable provider probe. Two existing fixtures were minimally corrected: Studio media-error replay now evicts bad audio and permits an explicitly requested fresh response; the HTTP streaming double no longer forwards language/voice request selectors into strict `AudioEvent` payloads. No commits, branches, generated-contract edits, or delegated work were made by this implementation agent.
