# Speech language support matrix

## Reading the evidence

- **Documented**: the provider publishes this locale/model/voice combination.
- **Config-tested**: local schema, registry, resolver, and request-building tests accept and propagate it. These use mocked provider calls, not acoustic-quality evaluation.
- **Live-unverified**: no live request was made by the speech implementation agent. Availability, model entitlement, accuracy, voice quality, latency, and quota/credit remain unknown.
- **Interface/content**: a stored interface-language selection does not establish translated UI coverage. Selecting a TTS language does not translate authored English text.

The runtime capability endpoint preserves `documented`, `config_tested`, `live_unverified`, and `provider_verified` distinctions rather than labeling configured credentials as live-ready.

## Single-language STT and TTS

| Language | STT locale | Prisma v3 documented | REST/WS config-tested | Timbre v3 documented | Compatible voices | Live evidence |
|---|---|---|---|---|---|---|
| English | en-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Hindi | hi-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Tamil | ta-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Telugu | te-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Kannada | kn-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Malayalam | ml-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Bengali | bn-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Gujarati | gu-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Marathi | mr-IN | Yes | Yes | Yes | All 13 below | Unverified |
| Punjabi | pa-IN | Yes | Yes | Yes | All 13 below | Unverified |

`prisma-v3.0` is explicitly selected. The URL `/stt/v3` alone does not select Prisma v3. Single-locale requests use the existing `transcribe` format. Provider language codes are expectation hints, not guarantees of the output language; the provider may transcribe another spoken language and report it in `detected_language_code`.

## Product-enabled code mixing

| Selected STT languages | Exact wire code | Format | Product config-tested | TTS fallback without explicit spoken locale | Live evidence |
|---|---|---|---|---|---|
| Tamil + English | ta-IN,en-IN | codemix | Yes; original alias preserved | auto | Unverified |
| Hindi + English | hi-IN,en-IN | codemix | Yes | auto | Unverified |
| Bengali + English | bn-IN,en-IN | codemix | Yes | auto | Unverified |

An explicit spoken-language locale overrides the TTS fallback independently of STT selection. Code mixing is disabled in local preference normalization for other selected STT locales; the resolver rejects unsupported product combinations rather than inventing codes. This is a product allowlist, not a claim that the provider rejects every other multilingual combination: vendor docs support one to four declared language codes. Vendor `indic-auto` STT detection is documented but not exposed in this product's `LanguageMode`. TTS `auto` is documented script detection, not a locale or a translation mode. No `hi-en` TTS code is introduced for v3; that voice catalog entry belongs to the older v2.5 model.

## Timbre v3 voices

Every listed voice is provider-documented for all ten locales. All are schema/config-tested; none are live-quality-verified by this agent.

| Voice ID | Vendor gender | Vendor persona |
|---|---|---|
| Avinash | Male | Professional |
| Shivani | Female | Warm, empathetic |
| Lakshmi | Female | Expressive, energetic |
| Kalpana | Female | Warm, empathetic |
| Shubham | Male | Expressive, energetic |
| Prakash | Male | Professional |
| Devansh | Male | Conversational |
| Yashraj | Male | Warm, empathetic |
| Chetana | Female | Warm, empathetic |
| Vasudha | Female | Expressive, energetic |
| Riyaa | Female | Confident, authoritative |
| Tarika | Female | Warm, empathetic |
| Harshad | Male | Professional |

Defaults remain English `en-IN`, no code mixing, and `Avinash`. Voice IDs are case-sensitive. Only `timbre-v3.0` is enabled here. Older Timbre v2.5 voices, such as `Nalini`, are not interchangeable with v3 and are rejected by product request validation. A persona label is vendor metadata, not an evaluation of coaching suitability or naturalness.

## Coverage of user surfaces

| Surface | STT selection | Spoken language / voice | Local audio preferences | Evidence |
|---|---|---|---|---|
| Legacy DSA coach/fixed/test/conversation TTS | Session LanguageMode | Session defaults; validated optional override | Caller/controller-owned; helper exports available | Backend request and existing integration tests |
| Legacy DSA streaming TTS | Session LanguageMode | Same shared resolver as assembled TTS | Caller/controller-owned | Mocked streaming compatibility tests |
| Studio and Codebase main voice (`StudioVoice`) | Local independent STT/codemix preferences | Nondefault local language/voice selectors; default session resolver | Text-only, mute/output gate, volume, local speed, same-/cross-tab updates | Component tests with actual HTML media boundary mocked |
| Lesson/interview/redrive common voice | Shared registry/resolver contracts provided | Common implementer owns adapters/call sites | Common implementer owns playback | Not independently verified by this speech agent |
| UI language and authored lesson/coach content | Not a speech capability | TTS selection is not translation | Independent interface preference stored | No comprehensive translated-interface/content audit |

A bounded live smoke, if subsequently authorized and performed by the coordinator, must record the exact model, locale, voice, transport, and outcome. One passing English sample must not be generalized to all locales/voices or production latency/accuracy.

## Sources

- [Prisma v3 languages, detection, and multilingual configuration](https://docs.gnani.ai/api/STT/models/prisma-v3.md)
- [REST speech-to-text](https://docs.gnani.ai/api/STT/speech-to-text.md)
- [WebSocket configuration and framing](https://docs.gnani.ai/api/STT/stt-websocket.md)
- [Timbre v3 voice catalog and all-ten-language compatibility](https://docs.gnani.ai/api/TTS/available-voices.md)
- [SSE TTS](https://docs.gnani.ai/api/TTS/tts-sse.md)

For test commands, RED/GREEN evidence, remaining protocol/live gaps, and integration exports, see [VOICE_INTEGRATION.md](VOICE_INTEGRATION.md).
