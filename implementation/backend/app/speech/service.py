"""One coordinator-owned speech service; all provider calls share its dispatcher."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.api_schemas import STTRequest, STTResult, TTSRequest
from backend.app.models.domain import RevisionRef
from backend.app.models.enums import LanguageMode
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechGatekeeper
from backend.app.speech.capabilities import session_tts_selection
from backend.app.speech.gnani_adapter import AssembledTTSSynthesis, GnaniSpeechAdapter
from backend.app.speech.tts_cache import TTSDiskCache
from backend.app.speech.ws_streamer import GnaniWebSocketSTTRelay


_CAPTURE_SUPERSEDED_REASON = "speech_capture_superseded"


class SpeechService:
    def __init__(
        self,
        *,
        db_path: str | Path,
        cache_dir: str | Path,
        api_key: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        configured = settings or Settings(_env_file=None)
        self.settings = configured
        self.cache = TTSDiskCache(Path(cache_dir), max_bytes=configured.tts_cache_max_bytes,
                                  max_age_seconds=configured.tts_cache_max_age_seconds)
        provider_origin = configured.gnani_base_url.rstrip("/")
        self.adapter = GnaniSpeechAdapter(
            api_key=(api_key if api_key is not None else (
                configured.gnani_api_key.get_secret_value() if configured.gnani_api_key else ""
            )),
            tts_cache=self.cache,
            stt_endpoint=f"{provider_origin}/stt/v3",
            tts_endpoint=f"{provider_origin}/api/v1/tts/sse",
        )
        self.gatekeeper = SpeechGatekeeper(
            self.adapter,
            db_path=db_path,
            per_session_stt_seconds=configured.max_stt_seconds_per_session,
            per_session_tts_chars=configured.max_tts_chars_per_session,
            global_daily_call_limit=configured.global_daily_call_limit,
        )
        self.gatekeeper.recover_pending_usage()
        self.ws = GnaniWebSocketSTTRelay(self.gatekeeper)
        self._tasks: dict[tuple[str, int], set[asyncio.Task]] = {}

    def _assert_current(self, session_id: str, revision: RevisionRef) -> str:
        if str(revision.session_id) != session_id:
            raise SpeechBusyError("Speech revision belongs to another session.")
        with self.gatekeeper._db_lock:
            row = self.gatekeeper._conn.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if row is None or row["deleted_at"] is not None:
                raise SpeechBusyError("Speech session is no longer available.")
            if (
                row["active_code_version_id"] != revision.code_version_id
                or row["active_turn_generation"] != revision.turn_generation
                or row["exercise_id"] != revision.exercise_id.value
                or row["spec_version"] != revision.spec_version.value
            ):
                raise SpeechBusyError("Speech revision is superseded.")
            code = self.gatekeeper._conn.execute(
                "SELECT source_code,code_hash FROM code_versions WHERE session_id=? AND code_version_id=?",
                (session_id, revision.code_version_id),
            ).fetchone()
            if (
                code is None
                or code["code_hash"] != revision.code_hash
                or hashlib.sha256(code["source_code"].encode()).hexdigest()
                != revision.code_hash
            ):
                raise SpeechBusyError(
                    "Speech source hash does not match the current revision."
                )
            return str(code["source_code"])

    async def _track(self, session_id: str, generation: int, awaitable):
        task = asyncio.create_task(awaitable)
        identity = (session_id, generation)
        tasks = self._tasks.setdefault(identity, set())
        tasks.add(task)
        try:
            return await task
        finally:
            tasks.discard(task)
            if not tasks:
                self._tasks.pop(identity, None)

    def _cancel_previous_capture_work(self, session_id: str, generation: int) -> None:
        """Barge in on this session only; dispatcher cleanup owns slot release."""
        for identity, tasks in tuple(self._tasks.items()):
            sid, previous_generation = identity
            if sid != session_id or previous_generation > generation:
                continue
            if previous_generation < generation:
                self.gatekeeper.cancel_turn_speech(sid, previous_generation)
            # Same-generation rerecords cancel tasks, not the logical turn.
            for task in tuple(tasks):
                task.cancel(_CAPTURE_SUPERSEDED_REASON)

    async def transcribe(
        self,
        session_id: str,
        audio_bytes: bytes,
        language_mode: LanguageMode | str,
        revision: RevisionRef,
        capture_attempt_id: int,
        transport: str = "REST_V3",
    ) -> STTResult:
        source = self._assert_current(session_id, revision)
        registered = self.gatekeeper.register_capture_attempt(
            session_id, revision.turn_generation, capture_attempt_id
        )
        if registered != capture_attempt_id:
            raise SpeechBusyError(
                "Capture attempt is stale; start a new recording attempt."
            )
        self._cancel_previous_capture_work(session_id, revision.turn_generation)
        req = STTRequest(
            session_id=session_id,
            revision=revision,
            turn_generation=revision.turn_generation,
            capture_attempt_id=capture_attempt_id,
            exercise_id=revision.exercise_id,
            spec_version=revision.spec_version,
            language_mode=LanguageMode(language_mode),
            source_code=source,
        )
        if transport == "WS_V3":
            operation = self.ws.transcribe_stream_with_fallback(req, [audio_bytes], assert_current=lambda: self._assert_current(session_id, revision))
        elif transport == "REST_V3":
            operation = self.gatekeeper.execute_stt(req, audio_bytes, assert_current=lambda: self._assert_current(session_id, revision))
        else:
            raise ValueError("Unsupported STT transport.")
        result = await self._track(session_id, revision.turn_generation, operation)
        self._assert_current(session_id, revision)
        return result

    async def synthesize(
        self,
        session_id: str,
        text: str,
        revision: RevisionRef,
        turn_id: str | None = None,
        playback_id: str | None = None,
        *, language: str | None = None, voice: str | None = None,
    ) -> AssembledTTSSynthesis:
        # Personalized learner/coach text has no public-scope option.
        return await self._synthesize_request(session_id, text, revision, turn_id, playback_id,
                                               language=language, voice=voice)

    async def synthesize_fixed(
        self, session_id: str, revision: RevisionRef, *, purpose: str,
        playback_id: str | None = None, language: str | None = None, voice: str | None = None,
    ) -> AssembledTTSSynthesis:
        """Only server-owned fixed public content may share audio across sessions."""
        self._assert_current(session_id, revision)
        from backend.app.speech.routes import fixed_introduction, _TEST_VOICE_TEXT
        if purpose == "INTRODUCTION":
            text = fixed_introduction(revision)
        elif purpose == "TEST_VOICE":
            text = _TEST_VOICE_TEXT
        else:
            raise ValueError("Unknown fixed public voice purpose.")
        return await self._synthesize_request(session_id, text, revision, playback_id=playback_id,
                                              cache_scope="PUBLIC_GENERIC", language=language, voice=voice)

    def _tts_selection(self, session_id: str, *, language: str | None = None, voice: str | None = None) -> dict[str, str]:
        with self.gatekeeper._db_lock:
            row = self.gatekeeper._conn.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise SpeechBusyError('Speech session is no longer available.')
        return session_tts_selection(row, model=self.settings.gnani_tts_model,
                                     default_voice=self.settings.gnani_tts_voice, language=language, voice=voice)

    async def _synthesize_request(
        self, session_id: str, text: str, revision: RevisionRef,
        turn_id: str | None = None, playback_id: str | None = None, *,
        cache_scope: str = "SESSION_SCOPED", language: str | None = None, voice: str | None = None,
    ) -> AssembledTTSSynthesis:
        self._assert_current(session_id, revision)
        req = TTSRequest(
            session_id=session_id,
            revision=revision,
            turn_generation=revision.turn_generation,
            turn_id=turn_id,
            playback_id=playback_id,
            text=text,
            **self._tts_selection(session_id, language=language, voice=voice),
            cache_scope=cache_scope,
        )
        try:
            result = await self._track(
                session_id, revision.turn_generation, self.gatekeeper.execute_tts(req, assert_current=lambda: self._assert_current(session_id, revision))
            )
        except asyncio.CancelledError as exc:
            # Rerecording can supersede playback without advancing generation.
            # Only capture-owned cancellation is translated; disconnects,
            # interrupts and shutdown retain ordinary cancellation semantics.
            if exc.args == (_CAPTURE_SUPERSEDED_REASON,):
                raise SpeechBusyError("Speech playback superseded by a newer capture.") from exc
            self._assert_current(session_id, revision)
            raise
        self._assert_current(session_id, revision)
        return result

    def interrupt(self, session_id: str, turn_generation: int) -> None:
        """Stop current audio work while allowing a higher capture on this logical turn."""
        tracker = self.gatekeeper._session_captures.get(session_id)
        if tracker and tracker.turn_generation == turn_generation:
            tracker.cancelled_attempts.add(tracker.latest_capture_attempt_id)
        for task in tuple(self._tasks.get((session_id,turn_generation),())):
            task.cancel()

    def cancel(self, session_id: str, turn_generation: int) -> None:
        self.gatekeeper.cancel_turn_speech(session_id, turn_generation)
        for task in tuple(self._tasks.get((session_id, turn_generation), ())):
            task.cancel()

    async def cancel_session(self, session_id: str, turn_generation: int, *, timeout_seconds: float = 2.0) -> int:
        """Bounded barrier: report pending work instead of claiming cache eviction is safe."""
        generations = {turn_generation} | {generation for sid, generation in self._tasks if sid == session_id}
        for generation in generations:
            self.cancel(session_id, generation)
        tasks = {task for (sid, _), group in self._tasks.items() if sid == session_id for task in group}
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
            await asyncio.gather(*done, return_exceptions=True)
            if pending:
                return len(pending)
        self._tasks = {identity: group for identity, group in self._tasks.items() if identity[0] != session_id}
        self.gatekeeper._session_captures = {sid: tracker for sid, tracker in self.gatekeeper._session_captures.items() if sid != session_id}
        self.gatekeeper._cancelled_turns = {identity for identity in self.gatekeeper._cancelled_turns if identity[0] != session_id}
        return 0

    async def aclose(self) -> None:
        tasks = [task for group in self._tasks.values() for task in group]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.gatekeeper._conn.close()

    def close(self) -> None:
        """Compatibility shutdown; async lifespans should await aclose()."""
        if self._tasks:
            asyncio.get_running_loop().create_task(self.aclose())
        else:
            self.gatekeeper._conn.close()

    async def stream_synthesize(
        self,
        session_id: str,
        text: str,
        revision: RevisionRef,
        playback_id: str | None = None,
        turn_id: str | None = None,
        *, language: str | None = None, voice: str | None = None,
    ):
        """Stream provider PCM under one reservation/slot for its entire lifetime."""
        self._assert_current(session_id, revision)
        req = TTSRequest(
            session_id=session_id,
            revision=revision,
            turn_generation=revision.turn_generation,
            turn_id=turn_id,
            playback_id=playback_id,
            text=text,
            **self._tts_selection(session_id, language=language, voice=voice),
        )
        queue = asyncio.Queue(maxsize=16)

        async def publish(event):
            self._assert_current(session_id, revision)
            await queue.put(event)

        task = asyncio.create_task(self.gatekeeper.execute_tts(req, on_event=publish, assert_current=lambda: self._assert_current(session_id, revision)))
        identity = (session_id, revision.turn_generation)
        self._tasks.setdefault(identity, set()).add(task)
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), 0.1)
                except TimeoutError:
                    continue
                self._assert_current(session_id, revision)
                yield event
            result = await task
            if result.cache_hit:
                for event in result.events:
                    yield event
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            tasks = self._tasks.get(identity, set())
            tasks.discard(task)
            if not tasks:
                self._tasks.pop(identity, None)

    async def transcribe_frames(
        self,
        session_id: str,
        frames,
        language_mode: LanguageMode | str,
        revision: RevisionRef,
        capture_attempt_id: int,
    ) -> STTResult:
        source = self._assert_current(session_id, revision)
        registered = self.gatekeeper.register_capture_attempt(
            session_id, revision.turn_generation, capture_attempt_id
        )
        if registered != capture_attempt_id:
            raise SpeechBusyError(
                "Capture attempt is stale; start a new recording attempt."
            )
        self._cancel_previous_capture_work(session_id, revision.turn_generation)
        req = STTRequest(
            session_id=session_id,
            revision=revision,
            turn_generation=revision.turn_generation,
            capture_attempt_id=capture_attempt_id,
            exercise_id=revision.exercise_id,
            spec_version=revision.spec_version,
            language_mode=LanguageMode(language_mode),
            source_code=source,
        )
        result = await self._track(
            session_id, revision.turn_generation, self.ws.transcribe_live(req, frames, assert_current=lambda: self._assert_current(session_id, revision))
        )
        self._assert_current(session_id, revision)
        return result
