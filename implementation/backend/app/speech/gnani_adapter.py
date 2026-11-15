"""Gnani Vachana Speech Adapter (`gnani_adapter.py`).

Implements Plan §8.1 / §8.4 / Phase 2 Prompt §B.2 & §B.5 and Repairs P2-05 & P2-08:
- REST STT (`POST https://api.vachana.ai/stt/v3`):
  - Header: `X-API-Key-ID` (loaded exclusively from `VCC_GNANI_API_KEY` env var), `X-API-Request-ID`.
  - Distinguishes `client_request_id` (sent in `X-API-Request-ID`) from `provider_request_id`
    (returned in `body.get("request_id")`), setting `request_id = provider_request_id or client_request_id`.
  - Marks only transient statuses (`408, 429, 502, 503, 504`) as `retryable=True`; client/auth/schema
    errors (`400, 401, 403, 422`) are strictly `retryable=False`.
- WebSocket STT Wire Contract (`wss://api.vachana.ai/stt/v3/stream`):
  - Defines `build_ws_stt_init_frame()` (including `sample_rate: 16000`, `x-sample-rate: "16000"`,
    and `x-api-request-id` alongside `model`, `language_code`, `format`, `keyterms`, `topic`,
    `previous_text`) and `build_ws_stt_commit_frame()` (`{"type": "commit"}`, never `{"type": "end"}`).
- SSE TTS (`POST https://api.vachana.ai/api/v1/tts/sse`):
  - Fix P2-05 (`parse_gnani_sse_stream`):
    - Accepts either `0`-based (`0, 1, 2, ...`) or `1`-based (`1, 2, ...` with `complete` carrying
      `chunk_index: 3, audio: "", is_final: true`) contiguous `chunk_index` sequences while
      rejecting any gap, duplicate, negative index, or initial index not in `{0, 1}`.
    - Handles `complete` events with either empty `audio: ""` (`is_final: true`) or final base64 `audio`.
    - Uses `codecs.getincrementaldecoder("utf-8")(errors="strict")` across byte chunks so multi-byte
      UTF-8 sequences split across TCP chunks never corrupt into replacement characters, and normalizes
      `\r\n`, `\r`, and `\n` line endings cleanly across chunk boundaries.
    - Enforces cumulative stream bounds (`max_sse_bytes=8 MiB`, `max_pcm_bytes=4 MiB`, `max_events=2000`).
  - Fix P2-08 (`synthesize_tts`):
    - Never rejoins `speakable_chunks` and slices `[:1000]`.
    - Iterates through all bounded `speakable_chunks = to_speakable(req.text)` in order
      (`segment_index = 0, 1, ...`), synthesizing each chunk via SSE, checking cancellation before
      and during each stream, concatenating decoded PCM bytes across all chunks in order, wrapping
      once into a single canonical WAV, and billing `sum(len(c) for c in speakable_chunks)`.
"""

from __future__ import annotations

import asyncio
import base64
import codecs
import io
import json
import time
import uuid
import wave
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.core.config import Settings, validated_credential
from backend.app.models.api_schemas import (
    AudioEvent,
    STTRequest,
    STTResult,
    TTSRequest,
)
from backend.app.models.enums import LanguageMode
from backend.app.speech.ast_keyterms import (
    build_stt_topic_string,
    extract_bias_keyterms,
)
from backend.app.speech.audio_utils import (
    inspect_and_validate_stt_wav,
    is_riff_wav,
    wrap_raw_pcm_as_wav,
)
from backend.app.speech.pre_tts_normalizer import NORMALIZER_VERSION, to_speakable
from backend.app.speech.transcript_normalizer import normalize_learner_transcript
from backend.app.speech.tts_cache import TTSDiskCache

GNANI_STT_REST_URL = "https://api.vachana.ai/stt/v3"
GNANI_STT_WS_URL = "wss://api.vachana.ai/stt/v3/stream"
GNANI_TTS_SSE_URL = "https://api.vachana.ai/api/v1/tts/sse"

_RETRYABLE_HTTP_STATUS_CODES: frozenset[int] = frozenset({408, 429, 502, 503, 504})


class GnaniTransportError(RuntimeError):
    """Raised on Gnani HTTP/SSE transport, authentication, or protocol errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.dispatched_chars = 0
        self.completed_chars = 0
        self.dispatched_calls: int | None = None
        self.audio_emitted = False


@dataclass(frozen=True)
class AssembledTTSSynthesis:
    """Complete WAV synthesis result produced by `GnaniSpeechAdapter.synthesize_tts`."""

    request_id: str
    cache_key: str
    cache_hit: bool
    wav_bytes: bytes
    events: list[AudioEvent]
    speakable_chunks: list[str]
    total_chars_billed: int
    latency_ms: int
    provider_calls: int = 0


def select_gnani_stt_format(language_mode: LanguageMode) -> str:
    """Return `'transcribe'` for `en-IN` and `'codemix'` for `ta-IN,en-IN` (never `'formatted'`)."""
    if "," in LanguageMode(language_mode).value:
        return "codemix"
    return "transcribe"


def build_ws_stt_init_frame(req: STTRequest) -> dict[str, Any]:
    """Build the initial JSON configuration frame for `wss://api.vachana.ai/stt/v3/stream`."""
    keyterms = extract_bias_keyterms(req.source_code, req.exercise_id)
    topic = build_stt_topic_string(req.exercise_id, keyterms, req.topic_override)
    client_req_id = req.request_id or f"stt_ws_{uuid.uuid4().hex[:16]}"
    frame: dict[str, Any] = {
        "model": "prisma-v3.0",
        # The deployed WS endpoint rejects the mixed language list before connected.
        # Single Tamil + codemix accepted and preserved both languages in a synthetic
        # roundtrip. Keep the learner mode and REST language list unchanged.
        "language_code": (
            LanguageMode.TA_IN.value
            if req.language_mode == LanguageMode.TA_IN_EN_IN
            else req.language_mode.value
        ),
        "format": select_gnani_stt_format(req.language_mode),
        "sample_rate": 16000,
        "x-sample-rate": "16000",
        "x-api-request-id": client_req_id,
        "keyterms": keyterms,
        "topic": topic,
    }
    if req.previous_audio_transcript and req.previous_audio_transcript.strip():
        frame["previous_text"] = req.previous_audio_transcript.strip()[:600]
    return frame


def build_ws_stt_commit_frame() -> dict[str, str]:
    """Build the utterance-end commit message (`{"type": "commit"}`, never `{"type": "end"}`)."""
    return {"type": "commit"}


def _parse_int_chunk_index(raw_val: Any) -> int:
    if isinstance(raw_val, bool) or not isinstance(raw_val, (int, str)):
        raise GnaniTransportError(f"Invalid SSE TTS chunk_index value: {raw_val!r}")
    try:
        return int(raw_val)
    except ValueError as exc:
        raise GnaniTransportError(
            f"Invalid SSE TTS chunk_index value: {raw_val!r}"
        ) from exc


class GnaniSSEStreamParser:
    """Bounded incremental decoder shared by file synthesis and streaming playback."""

    def __init__(
        self,
        *,
        request_id: str,
        client_request_id: str | None = None,
        playback_id: str | None = None,
        segment_index: int = 0,
        sample_rate: int = 22050,
        max_sse_bytes: int = 8 * 1024 * 1024,
        max_pcm_bytes: int = 4 * 1024 * 1024,
        max_events: int = 2000,
    ):
        self.request_id = request_id
        self.client_id = client_request_id or request_id
        self.playback_id = playback_id
        self.segment_index = segment_index
        self.sample_rate = sample_rate
        self.max_sse_bytes = max_sse_bytes
        self.max_pcm_bytes = max_pcm_bytes
        self.max_events = max_events
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self.buffer = ""
        self.pending_cr = False
        self.provider_id = None
        self.events = []
        self.pcm_parts = []
        self.first_index = None
        self.seen = 0
        self.complete = False
        self.sse_bytes = 0
        self.pcm_bytes = 0
        self.event_count = 0

    def _event(self, block: str) -> AudioEvent | None:
        event_name = None
        lines = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                lines.append(line[5:].strip())
        if not event_name and not lines:
            return None
        if self.complete:
            raise GnaniTransportError("SSE data arrived after terminal complete.")
        self.event_count += 1
        if self.event_count > self.max_events:
            raise GnaniTransportError("Gnani SSE stream exceeded max_events.")
        try:
            payload = json.loads("\n".join(lines)) if lines else {}
        except json.JSONDecodeError as exc:
            raise GnaniTransportError("Malformed JSON in Gnani SSE event.") from exc
        if not isinstance(payload, dict):
            raise GnaniTransportError("Gnani SSE event payload must be a JSON object.")
        provider = payload.get("request_id") or payload.get("provider_request_id")
        if isinstance(provider, str) and provider.strip():
            self.provider_id = provider.strip()[:128]
        kind = str(
            event_name
            or payload.get("type")
            or payload.get("event")
            or ("complete" if payload.get("is_final") is True else "")
        ).lower()
        if kind not in ("start", "chunk", "complete", "error"):
            raise GnaniTransportError("Unknown Gnani SSE event type.")
        index = None
        audio = payload.get("audio") or payload.get("audio_b64") or ""
        if kind in ("chunk", "complete"):
            value = payload.get("chunk_index")
            index = (
                _parse_int_chunk_index(value)
                if value is not None
                else ((self.first_index or 0) + self.seen)
            )
            if self.first_index is None:
                if index not in (0, 1):
                    raise GnaniTransportError(
                        "SSE TTS chunk_index gap/reorder on initial chunk."
                    )
                self.first_index = index
            if index != self.first_index + self.seen:
                raise GnaniTransportError("SSE TTS chunk_index gap/reorder.")
            if kind == "chunk" and not audio:
                raise GnaniTransportError("Empty audio payload in SSE chunk.")
            if audio:
                try:
                    pcm = base64.b64decode(audio, validate=True)
                except Exception as exc:
                    raise GnaniTransportError(
                        "Invalid base64 audio in SSE chunk."
                    ) from exc
                if not pcm:
                    raise GnaniTransportError("Decoded zero PCM bytes in SSE chunk.")
                self.pcm_bytes += len(pcm)
                if self.pcm_bytes > self.max_pcm_bytes:
                    raise GnaniTransportError(
                        "Gnani SSE stream exceeded max_pcm_bytes."
                    )
                self.pcm_parts.append(pcm)
                self.seen += 1
            if kind == "complete":
                self.complete = True
        if kind == "error":
            raise GnaniTransportError(
                f"Gnani SSE returned a provider error: {payload}",
                retryable=True,
            )
        return AudioEvent(
            event_type=kind,
            request_id=self.provider_id or self.request_id,
            client_request_id=self.client_id,
            provider_request_id=self.provider_id,
            playback_id=self.playback_id,
            segment_index=self.segment_index,
            chunk_index=index,
            audio_b64=audio or None,
            sample_rate=self.sample_rate,
            duration_ms=payload.get("duration_ms") if kind == "complete" else None,
        )

    def _append(self, text: str, final: bool = False) -> list[AudioEvent]:
        if self.pending_cr:
            text = "\r" + text
            self.pending_cr = False
        if not final and text.endswith("\r"):
            text = text[:-1]
            self.pending_cr = True
        self.buffer += text.replace("\r\n", "\n").replace("\r", "\n")
        emitted = []
        while "\n\n" in self.buffer:
            block, self.buffer = self.buffer.split("\n\n", 1)
            event = self._event(block)
            if event:
                emitted.append(event)
                self.events.append(event)
        if final and self.buffer.strip():
            event = self._event(self.buffer)
            self.buffer = ""
            if event:
                emitted.append(event)
                self.events.append(event)
        return emitted

    def feed(self, chunk: bytes | str) -> list[AudioEvent]:
        self.sse_bytes += (
            len(chunk) if isinstance(chunk, bytes) else len(chunk.encode("utf-8"))
        )
        if self.sse_bytes > self.max_sse_bytes:
            raise GnaniTransportError("Gnani SSE stream exceeded max_sse_bytes.")
        try:
            text = (
                self.decoder.decode(chunk, final=False)
                if isinstance(chunk, bytes)
                else chunk
            )
        except UnicodeDecodeError as exc:
            raise GnaniTransportError("Invalid UTF-8 in Gnani SSE stream.") from exc
        return self._append(text)

    def finish(self) -> bytes:
        try:
            tail = self.decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise GnaniTransportError(
                "Truncated multi-byte UTF-8 in Gnani SSE stream."
            ) from exc
        self._append(tail, final=True)
        if not self.complete:
            raise GnaniTransportError(
                "Truncated Gnani SSE TTS stream: missing terminal 'complete' event."
            )
        if not self.pcm_parts:
            raise GnaniTransportError(
                "Gnani SSE TTS stream completed with zero audio chunks."
            )
        return b"".join(self.pcm_parts)


def parse_gnani_sse_stream(
    raw_byte_chunks: Iterable[bytes | str], **kwargs
) -> tuple[list[AudioEvent], bytes]:
    parser = GnaniSSEStreamParser(**kwargs)
    for chunk in raw_byte_chunks:
        parser.feed(chunk)
    pcm = parser.finish()
    return parser.events, pcm


def _extract_raw_pcm_if_wav(audio_bytes: bytes) -> bytes:
    """If `audio_bytes` is a RIFF/WAVE container, extract its raw PCM frames for multi-segment join."""
    if not is_riff_wav(audio_bytes):
        return audio_bytes
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        return wf.readframes(wf.getnframes())


class GnaniSpeechAdapter:
    """Production & Mockable Adapter for Gnani Vachana REST STT and SSE TTS."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        tts_cache: TTSDiskCache | None = None,
        http_client: httpx.AsyncClient | None = None,
        stt_endpoint: str = GNANI_STT_REST_URL,
        tts_endpoint: str = GNANI_TTS_SSE_URL,
    ) -> None:
        self._explicit_api_key = api_key
        self.tts_cache = tts_cache
        self._http_client = http_client
        self.stt_endpoint = stt_endpoint
        self.tts_endpoint = tts_endpoint

    def _resolve_api_key(self) -> str:
        # Explicit empty values disable speech; never fall back to an ambient key.
        if self._explicit_api_key is not None:
            key = validated_credential(self._explicit_api_key)
        else:
            configured = Settings(_env_file=None).gnani_api_key
            key = validated_credential(configured)
        if not key:
            raise GnaniTransportError(
                "Missing VCC_GNANI_API_KEY in environment; live Gnani speech calls are blocked.",
                status_code=401,
                retryable=False,
            )
        return key

    def build_rest_stt_form_fields(
        self, req: STTRequest
    ) -> tuple[dict[str, str], list[str]]:
        """Construct the validated form fields and AST bias keyterms for `POST /stt/v3`."""
        keyterms = extract_bias_keyterms(req.source_code, req.exercise_id)
        topic = build_stt_topic_string(req.exercise_id, keyterms, req.topic_override)
        fmt = select_gnani_stt_format(req.language_mode)

        fields: dict[str, str] = {
            "model": "prisma-v3.0",
            "language_code": req.language_mode.value,
            "format": fmt,
            "keyterms": json.dumps(keyterms),
            "topic": topic[:1600],
        }
        if req.previous_audio_transcript and req.previous_audio_transcript.strip():
            fields["previous_text"] = req.previous_audio_transcript.strip()[:600]
        return fields, keyterms

    async def transcribe_rest(
        self,
        req: STTRequest,
        wav_bytes: bytes,
    ) -> STTResult:
        """Validate 16 kHz PCM WAV and execute a REST STT call (`POST /stt/v3`)."""
        inspection = inspect_and_validate_stt_wav(wav_bytes)
        api_key = self._resolve_api_key()
        client_req_id = req.request_id or f"stt_{uuid.uuid4().hex[:16]}"
        form_fields, keyterms = self.build_rest_stt_form_fields(req)
        fmt: Any = form_fields["format"]

        headers = {
            "X-API-Key-ID": api_key,
            "X-API-Request-ID": client_req_id,
        }
        files = {
            "audio_file": ("utterance.wav", wav_bytes, "audio/wav"),
        }

        t0 = time.perf_counter()
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                self.stt_endpoint,
                headers=headers,
                data=form_fields,
                files=files,
            )
        except httpx.HTTPError as exc:
            raise GnaniTransportError(
                "Gnani STT network request did not complete.",
                status_code=None,
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        latency_ms = max(0, int((time.perf_counter() - t0) * 1000))
        if resp.status_code == 429:
            raise GnaniTransportError(
                "Gnani STT HTTP 429 rate limit / single-concurrency exceeded.",
                status_code=429,
                retryable=True,
            )
        if resp.status_code >= 400:
            raise GnaniTransportError(
                f"Gnani STT failed with HTTP {resp.status_code}.",
                status_code=resp.status_code,
                retryable=resp.status_code in _RETRYABLE_HTTP_STATUS_CODES,
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise GnaniTransportError(
                "Gnani STT returned malformed JSON; usage is unconfirmed."
            ) from exc
        if not isinstance(body, dict) or body.get("success") is False:
            raise GnaniTransportError(
                "Gnani STT returned an invalid success envelope; usage is unconfirmed."
            )
        raw_prov_id = body.get("request_id")
        provider_req_id = (
            str(raw_prov_id).strip()[:128]
            if isinstance(raw_prov_id, str) and raw_prov_id.strip()
            else None
        )
        effective_req_id = provider_req_id or client_req_id

        if 'transcript' not in body and 'text' not in body:
            raise GnaniTransportError(
                "Gnani STT omitted its transcript field; usage is unconfirmed."
            )
        raw_transcript = body.get('transcript') if 'transcript' in body else body['text']
        if not isinstance(raw_transcript, str) or len(raw_transcript) > 4000:
            raise GnaniTransportError(
                "Gnani STT returned an invalid or oversized transcript; usage is unconfirmed."
            )
        raw_conf = body.get("confidence")
        provider_conf = (
            float(raw_conf)
            if isinstance(raw_conf, (int, float))
            and not isinstance(raw_conf, bool)
            and 0.0 <= float(raw_conf) <= 1.0
            else None
        )
        raw_detected_lang = body.get("detected_language_code") or body.get(
            "language_code"
        )
        detected_lang = (
            str(raw_detected_lang).strip()[:32]
            if isinstance(raw_detected_lang, str) and raw_detected_lang.strip()
            else None
        )

        proposal = normalize_learner_transcript(
            raw_transcript, known_identifiers=keyterms
        )
        return STTResult(
            request_id=effective_req_id,
            client_request_id=client_req_id,
            provider_request_id=provider_req_id,
            transport="REST_V3",
            configured_model="prisma-v3.0",
            provider_model=body.get("model")
            if isinstance(body.get("model"), str)
            else None,
            truncated=body.get("truncated") is True,
            language_mode=req.language_mode,
            observed_format=fmt,
            raw_transcript=proposal.raw_transcript,
            normalized_transcript=proposal.normalized_transcript,
            normalization_notes=proposal.normalization_notes,
            contains_self_correction=proposal.contains_self_correction,
            requires_confirmation=proposal.requires_confirmation,
            provider_confidence=provider_conf,
            detected_language_code=detected_lang,
            audio_duration_sec=inspection.duration_sec,
            low_energy_warning=inspection.low_energy_warning,
            latency_ms=latency_ms,
        )

    def get_cached_tts(self, req: TTSRequest) -> AssembledTTSSynthesis | None:
        """Resolve a session-authorized immutable replay before provider admission."""
        if self.tts_cache is None:
            return None
        chunks = to_speakable(req.text)
        key = TTSDiskCache.compute_cache_key(
            normalized_text="\n".join(chunks), model=req.model, voice=req.voice,
            language=req.language, speed=req.speed, audio_config=req.audio_config,
            normalizer_version=NORMALIZER_VERSION,
        )
        wav = self.tts_cache.get_wav(key, scope=req.cache_scope, session_id=req.session_id,
                                     expected_sample_rate_hz=req.audio_config.sample_rate)
        if wav is None:
            return None
        client_id = req.request_id or f"tts_{uuid.uuid4().hex[:16]}"
        event = AudioEvent(event_type="complete", request_id=client_id,
                           client_request_id=client_id, playback_id=req.playback_id,
                           wav_bytes_b64=base64.b64encode(wav).decode("ascii"),
                           sample_rate=req.audio_config.sample_rate, cache_hit=True)
        return AssembledTTSSynthesis(request_id=client_id, cache_key=key, cache_hit=True,
                                     wav_bytes=wav, events=[event], speakable_chunks=chunks,
                                     total_chars_billed=0, latency_ms=0)

    async def synthesize_tts(
        self,
        req: TTSRequest,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        on_event: Callable[[AudioEvent], Awaitable[None]] | None = None,
    ) -> AssembledTTSSynthesis:
        """Synthesize coach response via Gnani SSE TTS (`POST /api/v1/tts/sse`) across all bounded chunks (Fix P2-08)."""
        if not 0.85 <= req.speed <= 1.15:
            raise ValueError("Gnani synthesis speed must be between 0.85 and 1.15; use local playback speed otherwise.")
        if req.audio_config.sample_rate not in {8000, 16000, 22050, 24000, 44100, 48000}:
            raise ValueError("Unsupported Gnani synthesis sample rate.")
        client_req_id = req.request_id or f"tts_{uuid.uuid4().hex[:16]}"
        speakable_chunks = to_speakable(req.text)
        if not speakable_chunks or not any(c.strip() for c in speakable_chunks):
            raise ValueError("TTS request produced empty speakable text.")

        canonical_speakable = "\n".join(speakable_chunks)
        cache_key = TTSDiskCache.compute_cache_key(
            normalized_text=canonical_speakable,
            model=req.model,
            voice=req.voice,
            language=req.language,
            speed=req.speed,
            audio_config=req.audio_config,
            normalizer_version=NORMALIZER_VERSION,
        )

        cached = self.get_cached_tts(req)
        if cached is not None:
            return cached

        api_key = self._resolve_api_key()
        t0 = time.perf_counter()
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=20.0)
        all_events: list[AudioEvent] = []
        all_pcm_parts: list[bytes] = []
        dispatched_chars = 0
        completed_chars = 0
        dispatched_calls = 0
        audio_emitted = False

        try:
            for segment_index, chunk_text in enumerate(speakable_chunks):
                if is_cancelled is not None and is_cancelled():
                    if self.tts_cache is not None:
                        self.tts_cache.cleanup_partial_temps()
                    raise GnaniTransportError(
                        "TTS synthesis cancelled via barge-in.", retryable=False
                    )

                seg_client_id = (
                    client_req_id
                    if len(speakable_chunks) == 1
                    else f"{client_req_id}_seg{segment_index}"
                )
                headers = {
                    "X-API-Key-ID": api_key,
                    "X-API-Request-ID": seg_client_id,
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                }
                payload = {
                    "text": chunk_text,
                    "model": req.model,
                    "voice": req.voice,
                    "language": req.language,
                    "speed": req.speed,
                    "audio_config": req.audio_config.model_dump(mode="json"),
                }

                stream_parser = GnaniSSEStreamParser(
                    request_id=client_req_id,
                    client_request_id=client_req_id,
                    playback_id=req.playback_id,
                    segment_index=segment_index,
                    sample_rate=req.audio_config.sample_rate,
                )
                dispatched_chars += len(chunk_text)
                dispatched_calls += 1
                async with client.stream(
                    "POST",
                    self.tts_endpoint,
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status_code == 429:
                        raise GnaniTransportError(
                            "Gnani TTS HTTP 429 rate limit / single-concurrency exceeded.",
                            status_code=429,
                            retryable=True,
                        )
                    if resp.status_code >= 400:
                        err_body = (await resp.aread()).decode(errors="ignore")
                        raise GnaniTransportError(
                            f"Gnani TTS failed with HTTP {resp.status_code}: {err_body[:200]}",
                            status_code=resp.status_code,
                            retryable=resp.status_code in _RETRYABLE_HTTP_STATUS_CODES,
                        )
                    async for byte_chunk in resp.aiter_bytes():
                        if is_cancelled is not None and is_cancelled():
                            if self.tts_cache is not None:
                                self.tts_cache.cleanup_partial_temps()
                            raise GnaniTransportError(
                                "TTS synthesis cancelled via barge-in.", retryable=False
                            )
                        for audio_event in stream_parser.feed(byte_chunk):
                            audio_emitted = audio_emitted or bool(audio_event.audio_b64)
                            if on_event is not None:
                                await on_event(audio_event)

                previous_events = len(stream_parser.events)
                seg_pcm = stream_parser.finish()
                if on_event is not None:
                    for audio_event in stream_parser.events[previous_events:]:
                        await on_event(audio_event)
                completed_chars += len(chunk_text)
                seg_events = stream_parser.events
                all_events.extend(seg_events)
                all_pcm_parts.append(_extract_raw_pcm_if_wav(seg_pcm))
                if sum(len(part) for part in all_pcm_parts) > 16 * 1024 * 1024:
                    raise GnaniTransportError("TTS utterance exceeded total PCM limit.")
        except GnaniTransportError as exc:
            exc.dispatched_chars = dispatched_chars
            exc.completed_chars = completed_chars
            exc.dispatched_calls = dispatched_calls
            exc.audio_emitted = audio_emitted
            raise
        except httpx.HTTPError as exc:
            error = GnaniTransportError(
                "Gnani TTS network request did not complete.",
                status_code=None,
                retryable=True,
            )
            error.dispatched_chars = dispatched_chars
            error.completed_chars = completed_chars
            error.dispatched_calls = dispatched_calls
            error.audio_emitted = audio_emitted
            raise error from exc
        finally:
            if owns_client:
                await client.aclose()

        latency_ms = max(0, int((time.perf_counter() - t0) * 1000))
        assembled_pcm = b"".join(all_pcm_parts)

        if self.tts_cache is not None:
            final_wav = self.tts_cache.put_completed_stream(
                cache_key,
                assembled_pcm,
                stream_completed=True,
                audio_config=req.audio_config.model_copy(update={"container": "raw"}),
                scope=req.cache_scope,
                session_id=req.session_id,
            )
        else:
            final_wav = wrap_raw_pcm_as_wav(
                assembled_pcm,
                sample_rate_hz=req.audio_config.sample_rate,
                num_channels=req.audio_config.num_channels,
                sample_width_bytes=req.audio_config.sample_width,
            )

        total_chars_billed = sum(len(c) for c in speakable_chunks)
        final_req_id = (
            next(
                (
                    ev.provider_request_id
                    for ev in reversed(all_events)
                    if ev.provider_request_id
                ),
                None,
            )
            or client_req_id
        )

        return AssembledTTSSynthesis(
            request_id=final_req_id,
            cache_key=cache_key,
            cache_hit=False,
            wav_bytes=final_wav,
            events=all_events,
            speakable_chunks=speakable_chunks,
            total_chars_billed=total_chars_billed,
            latency_ms=latency_ms,
            provider_calls=dispatched_calls,
        )

    async def iter_tts_audio_events(
        self,
        req: TTSRequest,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[AudioEvent]:
        """Yield validated chunks while the provider produces them, with bounded backpressure."""
        queue: asyncio.Queue[AudioEvent] = asyncio.Queue(maxsize=16)

        async def publish(event: AudioEvent) -> None:
            await queue.put(event)

        task = asyncio.create_task(
            self.synthesize_tts(req, is_cancelled=is_cancelled, on_event=publish)
        )
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), 0.1)
                except TimeoutError:
                    continue
                yield event
            result = await task
            if result.cache_hit:
                for event in result.events:
                    yield event
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
