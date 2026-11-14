"""Bounded Gnani WebSocket STT, through the same account dispatcher as REST.

Configuration goes in upgrade headers. Audio uses 1024-byte PCM frames paced at
32 ms, followed by commit. This buffered-turn path does not claim full duplex.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
import wave
from collections.abc import Callable, Iterable
from typing import Any

from backend.app.models.api_schemas import STTRequest, STTResult
from backend.app.speech.audio_utils import (
    inspect_and_validate_stt_wav,
    is_riff_wav,
    wrap_raw_pcm_as_wav,
)
from backend.app.speech.ast_keyterms import extract_bias_keyterms
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechGatekeeper
from backend.app.speech.gnani_adapter import (
    GNANI_STT_WS_URL,
    GnaniTransportError,
    build_ws_stt_init_frame,
    build_ws_stt_commit_frame,
    select_gnani_stt_format,
)
from backend.app.speech.transcript_normalizer import normalize_learner_transcript


def strip_wav_header_to_raw_pcm16(audio_bytes: bytes) -> bytes:
    if is_riff_wav(audio_bytes):
        inspect_and_validate_stt_wav(audio_bytes)
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
            return wav.readframes(wav.getnframes())
    if not audio_bytes or len(audio_bytes) % 2:
        raise ValueError("Raw PCM16 must be nonempty and two-byte aligned.")
    if len(audio_bytes) > 960000:
        raise ValueError("PCM capture exceeds 30 seconds.")
    return audio_bytes


class GnaniWebSocketSTTRelay:
    def __init__(
        self,
        gatekeeper: SpeechGatekeeper,
        *,
        connect_fn: Callable | None = None,
        pace_frames: bool = True,
        ws_transport_fn: Callable | None = None,
    ):
        self.gatekeeper = gatekeeper
        self._connect_fn = connect_fn
        self._pace_frames = pace_frames
        self._legacy_transport = ws_transport_fn

    async def transcribe_stream_with_fallback(
        self, req: STTRequest, pcm_or_wav_chunks: Iterable[bytes], *, assert_current: Callable[[], None] | None = None
    ) -> STTResult:
        # Bound accumulation before concatenating an untrusted iterable.
        chunks = []
        total = 0
        for chunk in pcm_or_wav_chunks:
            total += len(chunk)
            if total > 1024 * 1024:
                raise ValueError("Capture exceeds the one MiB audio limit.")
            chunks.append(chunk)
        raw = strip_wav_header_to_raw_pcm16(b"".join(chunks))
        wav = wrap_raw_pcm_as_wav(
            raw, sample_rate_hz=16000, num_channels=1, sample_width_bytes=2
        )
        try:
            return await self.gatekeeper.execute_stt(
                req, wav, transcribe_fn=self._transcribe, assert_current=assert_current
            )
        except GnaniTransportError as exc:
            # Known auth/quota/schema failures stop. A transport failure is visibly
            # accounted as uncertain before an independently reserved REST attempt.
            if exc.status_code is not None and exc.status_code not in (
                408,
                502,
                503,
                504,
            ):
                raise
            if not exc.retryable:
                raise
            return await self.gatekeeper.execute_stt(req, wav, assert_current=assert_current)

    async def _transcribe(self, req: STTRequest, wav: bytes) -> STTResult:
        inspection = inspect_and_validate_stt_wav(wav)
        raw = strip_wav_header_to_raw_pcm16(wav)
        config = build_ws_stt_init_frame(req)
        client_id = str(config["x-api-request-id"])
        headers = {
            k: json.dumps(v, ensure_ascii=True)
            if isinstance(v, (list, dict))
            else str(v)
            for k, v in config.items()
            if k != "sample_rate"
        }
        headers["x-api-key-id"] = self.gatekeeper.adapter._resolve_api_key()
        start = time.perf_counter()
        transcripts = []
        provider_id = None
        detected_language = None
        confidence = None
        if self._legacy_transport is not None:
            response = self._legacy_transport(
                config,
                [
                    raw[i : i + 1024].ljust(1024, b"\0")
                    for i in range(0, len(raw), 1024)
                ],
                build_ws_stt_commit_frame(),
            )
            if asyncio.iscoroutine(response):
                response = await response
            transcripts = [
                str(response.get("transcript") or response.get("text") or "")
            ]
            provider_id = response.get("request_id")
        else:
            from websockets.asyncio.client import connect
            from websockets.exceptions import InvalidStatus, WebSocketException

            connect_fn = self._connect_fn or connect
            try:
                async with asyncio.timeout(inspection.duration_sec + 15):
                    async with connect_fn(
                        GNANI_STT_WS_URL,
                        additional_headers=headers,
                        open_timeout=6,
                        close_timeout=2,
                        max_size=65536,
                        max_queue=16,
                    ) as ws:
                        connected = json.loads(await asyncio.wait_for(ws.recv(), 6))
                        if connected.get("type") != "connected":
                            raise GnaniTransportError(
                                "Gnani WS did not acknowledge configuration.",
                                retryable=False,
                            )
                        provider_id = connected.get("request_id")
                        segments = set()
                        pending = set()
                        finished = asyncio.Event()

                        async def receive():
                            nonlocal provider_id, detected_language, confidence
                            for _ in range(200):
                                try:
                                    message = json.loads(
                                        await asyncio.wait_for(ws.recv(), 0.5)
                                    )
                                except TimeoutError:
                                    if (
                                        finished.is_set()
                                        and transcripts
                                        and not pending
                                    ):
                                        return
                                    continue
                                if not isinstance(message, dict):
                                    raise GnaniTransportError(
                                        "Invalid WS event.", retryable=False
                                    )
                                kind = message.get("type")
                                if kind == "error":
                                    raise GnaniTransportError(
                                        "Gnani WS rejected the stream.", retryable=False
                                    )
                                utterance = message.get("utterance_id")
                                if kind == "processing" and utterance:
                                    pending.add(utterance)
                                if kind == "transcript":
                                    if message.get("is_final") is False:
                                        continue
                                    sid = message.get("segment_id")
                                    if sid and sid in segments:
                                        continue
                                    if sid:
                                        segments.add(sid)
                                    if utterance:
                                        pending.discard(utterance)
                                    text = message.get("text")
                                    if not isinstance(text, str):
                                        raise GnaniTransportError(
                                            "Invalid WS transcript.", retryable=False
                                        )
                                    transcripts.append(text)
                                    if sum(len(t) for t in transcripts) > 4000:
                                        raise GnaniTransportError(
                                            "WS transcript exceeds limit.",
                                            retryable=False,
                                        )
                                    provider_id = (
                                        message.get("request_id") or provider_id
                                    )
                                    detected_language = (
                                        message.get("detected_language_code")
                                        or detected_language
                                    )
                                    value = message.get("confidence")
                                    confidence = (
                                        float(value)
                                        if type(value) in (float, int)
                                        and 0 <= value <= 1
                                        else None
                                    )

                        async def send():
                            clock = time.monotonic()
                            for index in range(0, len(raw), 1024):
                                if self.gatekeeper.is_capture_superseded(
                                    req.session_id,
                                    req.turn_generation,
                                    req.capture_attempt_id,
                                ):
                                    raise SpeechBusyError(
                                        "Capture superseded during WS upload."
                                    )
                                await ws.send(
                                    raw[index : index + 1024].ljust(1024, b"\0")
                                )
                                clock += 0.032
                                if self._pace_frames:
                                    await asyncio.sleep(
                                        max(0, clock - time.monotonic())
                                    )
                            await ws.send(json.dumps(build_ws_stt_commit_frame()))
                            # Give commit/VAD enough time to acknowledge pending work.
                            await asyncio.sleep(0.1)
                            finished.set()

                        receiver = asyncio.create_task(receive())
                        sender = asyncio.create_task(send())
                        try:
                            await asyncio.gather(sender, receiver)
                        finally:
                            for task in (receiver, sender):
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(
                                receiver, sender, return_exceptions=True
                            )
            except InvalidStatus as exc:
                raise GnaniTransportError(
                    "Gnani WS handshake rejected.", status_code=exc.response.status_code
                ) from exc
            except (TimeoutError, OSError, WebSocketException) as exc:
                raise GnaniTransportError(
                    "Gnani WS transport unavailable.", retryable=True
                ) from exc
        proposal = normalize_learner_transcript(
            " ".join(transcripts),
            known_identifiers=extract_bias_keyterms(req.source_code, req.exercise_id),
        )
        return STTResult(
            request_id=str(provider_id or client_id),
            client_request_id=client_id,
            provider_request_id=str(provider_id)[:128] if provider_id else None,
            transport="WS_V3",
            configured_model="prisma-v3.0",
            provider_model=None,
            language_mode=req.language_mode,
            observed_format=select_gnani_stt_format(req.language_mode),
            raw_transcript=proposal.raw_transcript,
            normalized_transcript=proposal.normalized_transcript,
            normalization_notes=proposal.normalization_notes,
            contains_self_correction=proposal.contains_self_correction,
            requires_confirmation=True,
            provider_confidence=confidence,
            detected_language_code=detected_language,
            audio_duration_sec=inspection.duration_sec,
            low_energy_warning=inspection.low_energy_warning,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )

    async def transcribe_live(self, req: STTRequest, incoming_frames, *, assert_current: Callable[[], None] | None = None) -> STTResult:
        """Relay a browser PCM iterator directly, with bounded framing and no billed retry."""
        # Reserve the upper bound until the live capture's duration is known.
        reservation_wav = wrap_raw_pcm_as_wav(
            b"\0" * 960000, sample_rate_hz=16000, num_channels=1, sample_width_bytes=2
        )

        async def operation(_req, _wav):
            return await self._live_wire(req, incoming_frames)

        return await self.gatekeeper.execute_stt(
            req, reservation_wav, transcribe_fn=operation, assert_current=assert_current
        )

    async def _live_wire(self, req: STTRequest, incoming_frames) -> STTResult:
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus, WebSocketException

        config = build_ws_stt_init_frame(req)
        headers = {
            k: json.dumps(v, ensure_ascii=True)
            if isinstance(v, (list, dict))
            else str(v)
            for k, v in config.items()
            if k != "sample_rate"
        }
        headers["x-api-key-id"] = self.gatekeeper.adapter._resolve_api_key()
        client_id = str(config["x-api-request-id"])
        provider_id = None
        transcripts = []
        detected = None
        confidence = None
        received_bytes = 0
        start = time.perf_counter()
        connect_fn = self._connect_fn or connect
        try:
            async with asyncio.timeout(45):
                async with connect_fn(
                    GNANI_STT_WS_URL,
                    additional_headers=headers,
                    open_timeout=6,
                    close_timeout=2,
                    max_size=65536,
                    max_queue=16,
                ) as ws:
                    connected = json.loads(await asyncio.wait_for(ws.recv(), 6))
                    if (
                        not isinstance(connected, dict)
                        or connected.get("type") != "connected"
                    ):
                        raise GnaniTransportError(
                            "Gnani WS did not acknowledge configuration.",
                            retryable=False,
                        )
                    provider_id = connected.get("request_id")
                    finished = asyncio.Event()
                    pending = set()
                    segment_ids = set()
                    committed_at = None

                    async def receive():
                        nonlocal provider_id, detected, confidence
                        for _ in range(200):
                            try:
                                message = json.loads(
                                    await asyncio.wait_for(ws.recv(), 0.25)
                                )
                            except TimeoutError:
                                if (
                                    finished.is_set()
                                    and transcripts
                                    and not pending
                                    and time.monotonic() - committed_at >= 1
                                ):
                                    return
                                continue
                            if not isinstance(message, dict):
                                raise GnaniTransportError(
                                    "Invalid WS event.", retryable=False
                                )
                            kind = message.get("type")
                            utterance = message.get("utterance_id")
                            if kind == "error":
                                raise GnaniTransportError(
                                    "Gnani WS rejected the stream.", retryable=False
                                )
                            if kind == "processing" and utterance:
                                pending.add(utterance)
                            if (
                                kind == "transcript"
                                and message.get("is_final") is not False
                            ):
                                segment_id = message.get("segment_id")
                                if segment_id and segment_id in segment_ids:
                                    continue
                                if segment_id:
                                    segment_ids.add(segment_id)
                                if utterance:
                                    pending.discard(utterance)
                                text = message.get("text")
                                if not isinstance(text, str):
                                    raise GnaniTransportError(
                                        "Invalid WS transcript.", retryable=False
                                    )
                                transcripts.append(text)
                                if sum(len(t) for t in transcripts) > 4000:
                                    raise GnaniTransportError(
                                        "WS transcript exceeds bound.", retryable=False
                                    )
                                provider_id = message.get("request_id") or provider_id
                                detected = (
                                    message.get("detected_language_code") or detected
                                )
                                value = message.get("confidence")
                                confidence = (
                                    float(value)
                                    if type(value) in (int, float) and 0 <= value <= 1
                                    else None
                                )
                        raise GnaniTransportError(
                            "WS event count exceeded bound.", retryable=False
                        )

                    async def send():
                        nonlocal received_bytes, committed_at
                        buffer = b""
                        iterator = incoming_frames.__aiter__()
                        frame_count = 0
                        clock = time.monotonic()
                        while True:
                            try:
                                chunk = await asyncio.wait_for(anext(iterator), 5)
                            except StopAsyncIteration:
                                break
                            if (
                                not isinstance(chunk, bytes)
                                or len(chunk) > 65536
                                or len(chunk) % 2
                            ):
                                raise ValueError(
                                    "Browser PCM frame is invalid or too large."
                                )
                            received_bytes += len(chunk)
                            if received_bytes > 960000:
                                raise ValueError("Capture exceeds 30 seconds.")
                            if self.gatekeeper.is_capture_superseded(
                                req.session_id,
                                req.turn_generation,
                                req.capture_attempt_id,
                            ):
                                raise SpeechBusyError("Live capture superseded.")
                            buffer += chunk
                            while len(buffer) >= 1024:
                                await ws.send(buffer[:1024])
                                buffer = buffer[1024:]
                                frame_count += 1
                                clock = max(clock + 0.032, time.monotonic())
                                if self._pace_frames:
                                    await asyncio.sleep(
                                        max(0, clock - time.monotonic())
                                    )
                        if not received_bytes:
                            raise ValueError("Live capture contained no audio.")
                        if buffer:
                            await ws.send(buffer.ljust(1024, b"\0"))
                        await ws.send(json.dumps(build_ws_stt_commit_frame()))
                        committed_at = time.monotonic()
                        finished.set()

                    sender = asyncio.create_task(send())
                    receiver = asyncio.create_task(receive())
                    try:
                        await asyncio.gather(sender, receiver)
                    finally:
                        for task in (sender, receiver):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(sender, receiver, return_exceptions=True)
        except InvalidStatus as exc:
            raise GnaniTransportError(
                "Gnani WS handshake rejected.", status_code=exc.response.status_code
            ) from exc
        except (TimeoutError, OSError, WebSocketException) as exc:
            raise GnaniTransportError(
                "Gnani WS transport unavailable; live work is unconfirmed.",
                retryable=False,
            ) from exc
        proposal = normalize_learner_transcript(
            " ".join(transcripts),
            known_identifiers=extract_bias_keyterms(req.source_code, req.exercise_id),
        )
        return STTResult(
            request_id=str(provider_id or client_id),
            client_request_id=client_id,
            provider_request_id=str(provider_id)[:128] if provider_id else None,
            transport="WS_V3",
            configured_model="prisma-v3.0",
            provider_model=None,
            language_mode=req.language_mode,
            observed_format=select_gnani_stt_format(req.language_mode),
            raw_transcript=proposal.raw_transcript,
            normalized_transcript=proposal.normalized_transcript,
            normalization_notes=proposal.normalization_notes,
            contains_self_correction=proposal.contains_self_correction,
            requires_confirmation=True,
            provider_confidence=confidence,
            detected_language_code=detected,
            audio_duration_sec=received_bytes / 32000,
            low_energy_warning=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
