"""Content-Addressed SHA-256 TTS Disk Cache (`tts_cache.py`).

Implements Plan §8.5 / Phase 2 Prompt §B.5 & P2 Repair:
- Deterministic Cache Key:
  `sha256(json.dumps([normalized_text, model, voice, language, audio_config, normalizer_version], sort_keys=True))`
- Scope Isolation:
  - `PUBLIC_GENERIC`: Stored under `<cache_root>/public/<content-version>/<key>.wav` for fixed server-owned UI/onboarding phrases.
  - `SESSION_SCOPED`: Stored under `<cache_root>/sessions/<session_id>/<key>.wav` for learner-specific
    coaching turns and automatically purged on `evict_session(session_id)`.
- Atomic Finalization & Full Container Validation:
  - Uses `inspect_and_validate_tts_wav` in both `get_wav` and `put_completed_stream` so corrupt or
    truncated WAV files are rejected and never served or promoted.
  - Streams into a temporary `.tmp.<uuid>` file and promotes via `os.replace()` ONLY after
    the SSE `complete` event arrives and the assembled WAV container passes full header/frame validation.
  - Wraps raw linear PCM (`container == "raw"`) in a single WAV header and never double-wraps
    when `container == "wav"`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid

from backend.app.core.logging import get_logger

_LOGGER = get_logger("vcc.tts_cache")
DEFAULT_CACHE_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
DEFAULT_CACHE_MAX_ENTRIES = 1024
# Bump when the server-owned public utterance contract changes without changing text.
PUBLIC_GENERIC_CONTENT_VERSION = "fixed-voice-v1"
from pathlib import Path

from backend.app.models.api_schemas import TTSAudioConfig
from backend.app.speech.audio_utils import (
    AudioValidationError,
    inspect_and_validate_tts_wav,
    is_riff_wav,
    wrap_raw_pcm_as_wav,
)
from backend.app.speech.pre_tts_normalizer import NORMALIZER_VERSION


class TTSDiskCache:
    """Content-addressed SHA-256 disk cache for synthesized TTS WAV artifacts."""

    def __init__(self, cache_root: Path | str, *, max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
                 max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS,
                 max_entries: int = DEFAULT_CACHE_MAX_ENTRIES) -> None:
        if any(type(value) is not int or value <= 0 for value in (max_bytes, max_age_seconds, max_entries)):
            raise ValueError("Cache bounds must be positive integers")
        self.cache_root = Path(cache_root).resolve()
        public_root = self.cache_root / "public"
        if public_root.is_symlink():
            raise ValueError("Public cache root must not be a symlink")
        self.public_dir = public_root / PUBLIC_GENERIC_CONTENT_VERSION
        self.sessions_dir = self.cache_root / "sessions"
        self.max_bytes, self.max_age_seconds, self.max_entries = max_bytes, max_age_seconds, max_entries
        self._lock = threading.RLock()
        for directory in (self.public_dir, self.sessions_dir):
            if directory.is_symlink():
                raise ValueError("Cache directories must not be symlinks")
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                _LOGGER.warning("Audio cache storage is unavailable; synthesis remains uncached")

    @staticmethod
    def compute_cache_key(
        *,
        normalized_text: str,
        model: str = "timbre-v3.0",
        voice: str = "Avinash",
        language: str = "en-IN",
        speed: float = 1.0,
        audio_config: TTSAudioConfig | dict[str, object] | None = None,
        normalizer_version: str = NORMALIZER_VERSION,
    ) -> str:
        """Compute the canonical SHA-256 hex digest for a TTS synthesis request."""
        if isinstance(audio_config, TTSAudioConfig):
            cfg_dict = audio_config.model_dump(mode="json")
        elif isinstance(audio_config, dict):
            cfg_dict = dict(audio_config)
        else:
            cfg_dict = TTSAudioConfig().model_dump(mode="json")

        payload = [
            normalized_text.strip(),
            model,
            voice,
            language,
            speed,
            cfg_dict,
            normalizer_version,
        ]
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _target_path(
        self,
        cache_key: str,
        *,
        scope: str = "SESSION_SCOPED",
        session_id: str | None = None,
    ) -> Path:
        if not cache_key or len(cache_key) > 128 or cache_key in (".", "..") or "/" in cache_key or "\\" in cache_key:
            raise ValueError("Invalid cache key")
        if scope == "PUBLIC_GENERIC":
            target = self.public_dir / f"{cache_key}.wav"
        elif scope == "SESSION_SCOPED" and session_id and session_id.strip():
            safe_session = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            target = self.sessions_dir / safe_session / f"{cache_key}.wav"
        else:
            raise ValueError("A valid cache scope and session identity are required")
        if target.is_symlink() or target.parent.is_symlink():
            raise ValueError("Cache entries must not follow symlinks")
        return target

    def get_wav(
        self,
        cache_key: str,
        *,
        scope: str = "SESSION_SCOPED",
        session_id: str | None = None,
        expected_sample_rate_hz: int | None = None,
    ) -> bytes | None:
        """Return cached WAV bytes if a complete, valid entry exists, else `None`."""
        with self._lock:
            path = self._target_path(cache_key, scope=scope, session_id=session_id)
            try:
                if not path.is_file():
                    return None
                stat = path.stat()
                if stat.st_mtime < time.time() - self.max_age_seconds or stat.st_size > self.max_bytes:
                    path.unlink()
                    return None
                data = path.read_bytes()
                inspect_and_validate_tts_wav(data, expected_sample_rate_hz=expected_sample_rate_hz)
            except (OSError, AudioValidationError):
                _LOGGER.warning("Cached audio could not be validated; synthesis will use a cache miss")
                return None
            return data

    def put_completed_stream(
        self,
        cache_key: str,
        raw_audio_bytes: bytes,
        *,
        stream_completed: bool,
        audio_config: TTSAudioConfig | None = None,
        scope: str = "SESSION_SCOPED",
        session_id: str | None = None,
    ) -> bytes:
        """Atomically persist a completed TTS audio stream as a single-wrapped WAV file.

        Validates the full WAV container via `inspect_and_validate_tts_wav` before promotion.
        Raises `ValueError` / `AudioValidationError` if `stream_completed` is False,
        `raw_audio_bytes` is empty, or the resulting WAV container is invalid/truncated.
        """
        if not stream_completed:
            raise ValueError("Cannot cache incomplete or cancelled TTS stream.")
        if not raw_audio_bytes:
            raise ValueError("Cannot cache empty TTS audio payload.")

        cfg = audio_config or TTSAudioConfig()
        if cfg.container == "wav" or is_riff_wav(raw_audio_bytes):
            if not is_riff_wav(raw_audio_bytes):
                raise ValueError("Expected RIFF/WAVE bytes when container='wav'.")
            final_wav = bytes(raw_audio_bytes)
        else:
            final_wav = wrap_raw_pcm_as_wav(
                raw_audio_bytes,
                sample_rate_hz=cfg.sample_rate,
                num_channels=cfg.num_channels,
                sample_width_bytes=cfg.sample_width,
            )

        # Full header, PCM format, positive frames, and frame byte-alignment check
        inspect_and_validate_tts_wav(final_wav, expected_sample_rate_hz=cfg.sample_rate)

        if len(final_wav) > self.max_bytes:
            _LOGGER.warning("Completed audio exceeds the cache cap; delivered without disk caching")
            return final_wav
        with self._lock:
            target = self._target_path(cache_key, scope=scope, session_id=session_id)
            tmp_path = target.with_name(f".{cache_key}.tmp.{uuid.uuid4().hex[:8]}")
            try:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                descriptor = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as file:
                    file.write(final_wav)
                os.replace(tmp_path, target)
                self.enforce_limits()
            except OSError:
                _LOGGER.warning("Completed audio delivered without caching; cache storage is unavailable")
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    _LOGGER.warning("Audio cache temporary cleanup requires maintenance")
        return final_wav

    def enforce_limits(self) -> int:
        """Evict expired and oldest entries under one cache-instance lock."""
        with self._lock:
            entries = []
            removed = 0
            cutoff = time.time() - self.max_age_seconds
            for path in self.cache_root.rglob("*.wav"):
                if path.is_symlink():
                    raise ValueError("Cache entries must not be symlinks")
                if not path.is_file():
                    continue
                stat = path.stat()
                if stat.st_mtime < cutoff:
                    path.unlink()
                    removed += 1
                else:
                    entries.append((stat.st_mtime, path, stat.st_size))
            total = sum(size for _, _, size in entries)
            remaining = len(entries)
            for _, path, size in sorted(entries):
                if total <= self.max_bytes and remaining <= self.max_entries:
                    break
                path.unlink()
                total -= size
                remaining -= 1
                removed += 1
            return removed

    def evict_session(self, session_id: str) -> int:
        """Delete private audio, reporting filesystem errors instead of false success."""
        with self._lock:
            s_dir = self.sessions_dir / hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            if s_dir.is_symlink():
                raise ValueError("Session cache directories must not be symlinks")
            if not s_dir.exists():
                return 0
            removed = sum(1 for path in s_dir.glob("*.wav") if path.is_file())
            shutil.rmtree(s_dir)
            return removed

    def cleanup_partial_temps(self) -> int:
        """Remove orphaned temporary files; maintenance failures remain observable."""
        with self._lock:
            removed = 0
            for path in self.cache_root.rglob("*.tmp.*"):
                if path.is_symlink():
                    raise ValueError("Cache temporary files must not be symlinks")
                if path.is_file():
                    path.unlink()
                    removed += 1
            return removed
