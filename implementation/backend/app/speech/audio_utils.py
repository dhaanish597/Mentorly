"""Audio Validation, RMS Heuristic, and WAV Container Utilities (`audio_utils.py`).

Enforces Plan §6 / §8.1 / Phase 2 Prompt §B.1 & P2 Repair:
- STT Input Format: 16 kHz (`16000 Hz`), 16-bit (`2 bytes`), mono (`1 channel`) linear PCM WAV.
- Max STT Payload: `<= 1,048,576` bytes (`1 MiB`) and `<= 30.0` seconds.
- Low-Energy RMS Warning: Computes normalized RMS energy `[0.0, 1.0]` and flags quiet/near-silent
  captures (`low_energy_warning=True`) as a non-blocking diagnostic without rejecting quiet speech.
- TTS WAV Validation (`inspect_and_validate_tts_wav`): Validates full RIFF/WAVE header, declared
  RIFF chunk length, PCM compression (`NONE`), channel count (`1`), sample width (`2`), positive
  frame count, and exact frame byte alignment so corrupt/truncated WAV files are rejected.
- TTS WAV Wrapping: Wraps raw 22,050 Hz (or 16,000 Hz) 16-bit mono linear PCM chunks in a single
  canonical RIFF/WAVE header while detecting and rejecting double-wrapping if already WAV.
- Synthetic Speech Waveform (`generate_synthetic_speech_wav_bytes`): Synthesizes a deterministic
  voiced vowel-formant / syllable-modulated waveform (`F0=125 Hz` + harmonics `F1=700 Hz`,
  `F2=1200 Hz`, `F3=2500 Hz` with syllable envelope) for protocol smoke testing.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import dataclass

REQUIRED_SAMPLE_RATE_HZ = 16_000
REQUIRED_CHANNELS = 1
REQUIRED_SAMPLE_WIDTH_BYTES = 2
MAX_STT_DURATION_SEC = 30.0
MAX_STT_AUDIO_BYTES = 1_048_576  # 1 MiB
LOW_ENERGY_RMS_THRESHOLD = 0.008


class AudioValidationError(ValueError):
    """Raised when an audio payload violates format, size, or duration invariants."""


@dataclass(frozen=True)
class WavInspectionResult:
    """Verified properties of a 16-bit mono PCM WAV payload."""

    sample_rate_hz: int
    num_channels: int
    sample_width_bytes: int
    num_frames: int
    duration_sec: float
    byte_length: int
    rms_normalized: float
    peak_normalized: float
    low_energy_warning: bool


def compute_pcm16_rms_and_peak(pcm_bytes: bytes) -> tuple[float, float]:
    """Compute normalized RMS and peak amplitude `[0.0, 1.0]` for 16-bit signed little-endian PCM."""
    num_samples = len(pcm_bytes) // 2
    if num_samples == 0:
        return 0.0, 0.0

    samples = struct.unpack(f"<{num_samples}h", pcm_bytes[: num_samples * 2])
    sum_sq = 0.0
    peak = 0
    for s in samples:
        abs_s = abs(s)
        if abs_s > peak:
            peak = abs_s
        sum_sq += float(s * s)

    rms = math.sqrt(sum_sq / num_samples) / 32768.0
    peak_norm = min(1.0, peak / 32768.0)
    return round(min(1.0, rms), 6), round(peak_norm, 6)


def _validate_riff_envelope(wav_bytes: bytes) -> int:
    """Validate outer RIFF/WAVE magic and ensure payload is not truncated relative to RIFF size."""
    if not isinstance(wav_bytes, (bytes, bytearray)):
        raise AudioValidationError("Audio payload must be bytes.")
    byte_len = len(wav_bytes)
    if byte_len < 44:
        raise AudioValidationError(
            f"WAV payload too short ({byte_len} bytes < 44-byte RIFF header)."
        )
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise AudioValidationError("Invalid RIFF/WAVE header magic bytes.")
    declared_riff_size = struct.unpack("<I", wav_bytes[4:8])[0]
    if declared_riff_size + 8 > byte_len:
        raise AudioValidationError(
            f"Truncated RIFF container: header declares {declared_riff_size + 8} bytes, "
            f"got {byte_len} bytes."
        )
    return byte_len


def inspect_and_validate_stt_wav(
    wav_bytes: bytes,
    *,
    max_bytes: int = MAX_STT_AUDIO_BYTES,
    max_duration_sec: float = MAX_STT_DURATION_SEC,
    low_energy_threshold: float = LOW_ENERGY_RMS_THRESHOLD,
) -> WavInspectionResult:
    """Validate that `wav_bytes` is a canonical 16 kHz, 16-bit mono linear PCM WAV within bounds."""
    byte_len = _validate_riff_envelope(wav_bytes)
    if byte_len > max_bytes:
        raise AudioValidationError(
            f"WAV payload exceeds maximum byte budget ({byte_len} > {max_bytes} bytes)."
        )

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            num_frames = wf.getnframes()
            comp_type = wf.getcomptype()
            pcm_data = wf.readframes(num_frames)
    except (wave.Error, EOFError, struct.error) as exc:
        raise AudioValidationError(f"Malformed WAV container: {exc}") from exc

    if comp_type != "NONE":
        raise AudioValidationError(
            f"Unsupported WAV compression type: {comp_type!r} (expected PCM 'NONE')."
        )
    if channels != REQUIRED_CHANNELS:
        raise AudioValidationError(
            f"Invalid channel count: {channels} (expected mono = 1)."
        )
    if sample_width != REQUIRED_SAMPLE_WIDTH_BYTES:
        raise AudioValidationError(
            f"Invalid sample width: {sample_width} bytes (expected 16-bit = 2 bytes)."
        )
    if sample_rate != REQUIRED_SAMPLE_RATE_HZ:
        raise AudioValidationError(
            f"Invalid sample rate: {sample_rate} Hz (expected {REQUIRED_SAMPLE_RATE_HZ} Hz)."
        )
    if num_frames <= 0 or len(pcm_data) == 0:
        raise AudioValidationError("WAV payload contains zero audio frames.")

    expected_frame_bytes = num_frames * channels * sample_width
    if len(pcm_data) != expected_frame_bytes:
        raise AudioValidationError(
            f"Truncated WAV data chunk: expected {expected_frame_bytes} bytes, got {len(pcm_data)}."
        )

    duration_sec = round(num_frames / float(sample_rate), 4)
    if duration_sec > max_duration_sec:
        raise AudioValidationError(
            f"Utterance duration {duration_sec:.2f}s exceeds {max_duration_sec:.1f}s limit."
        )

    rms_norm, peak_norm = compute_pcm16_rms_and_peak(pcm_data)
    low_energy = rms_norm < low_energy_threshold

    return WavInspectionResult(
        sample_rate_hz=sample_rate,
        num_channels=channels,
        sample_width_bytes=sample_width,
        num_frames=num_frames,
        duration_sec=duration_sec,
        byte_length=byte_len,
        rms_normalized=rms_norm,
        peak_normalized=peak_norm,
        low_energy_warning=low_energy,
    )


def inspect_and_validate_tts_wav(
    wav_bytes: bytes,
    *,
    expected_sample_rate_hz: int | None = None,
) -> WavInspectionResult:
    """Validate a synthesized TTS WAV container before caching or serving.

    Verifies the full RIFF/WAVE header, declared RIFF size, uncompressed linear PCM
    (`NONE`), mono channel count (`1`), 16-bit sample width (`2` bytes), positive
    frame count, and exact frame byte alignment so truncated or corrupt WAV files
    are never promoted to or served from `TTSDiskCache`.
    """
    byte_len = _validate_riff_envelope(wav_bytes)

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            num_frames = wf.getnframes()
            comp_type = wf.getcomptype()
            pcm_data = wf.readframes(num_frames)
    except (wave.Error, EOFError, struct.error) as exc:
        raise AudioValidationError(f"Malformed TTS WAV container: {exc}") from exc

    if comp_type != "NONE":
        raise AudioValidationError(
            f"Unsupported TTS WAV compression type: {comp_type!r} (expected PCM 'NONE')."
        )
    if channels != REQUIRED_CHANNELS:
        raise AudioValidationError(
            f"Invalid TTS WAV channel count: {channels} (expected mono = 1)."
        )
    if sample_width != REQUIRED_SAMPLE_WIDTH_BYTES:
        raise AudioValidationError(
            f"Invalid TTS WAV sample width: {sample_width} bytes (expected 16-bit = 2 bytes)."
        )
    if sample_rate < 8000 or sample_rate > 48000:
        raise AudioValidationError(
            f"Invalid TTS WAV sample rate: {sample_rate} Hz (expected 8000..48000 Hz)."
        )
    if expected_sample_rate_hz is not None and sample_rate != expected_sample_rate_hz:
        raise AudioValidationError(
            f"TTS WAV sample rate mismatch: got {sample_rate} Hz, "
            f"expected {expected_sample_rate_hz} Hz."
        )
    if num_frames <= 0 or len(pcm_data) == 0:
        raise AudioValidationError("TTS WAV payload contains zero audio frames.")

    expected_frame_bytes = num_frames * channels * sample_width
    if len(pcm_data) != expected_frame_bytes or len(pcm_data) % (channels * sample_width) != 0:
        raise AudioValidationError(
            f"Truncated or misaligned TTS WAV data chunk: expected {expected_frame_bytes} bytes, "
            f"got {len(pcm_data)}."
        )

    duration_sec = round(num_frames / float(sample_rate), 4)
    rms_norm, peak_norm = compute_pcm16_rms_and_peak(pcm_data)
    low_energy = rms_norm < LOW_ENERGY_RMS_THRESHOLD

    return WavInspectionResult(
        sample_rate_hz=sample_rate,
        num_channels=channels,
        sample_width_bytes=sample_width,
        num_frames=num_frames,
        duration_sec=duration_sec,
        byte_length=byte_len,
        rms_normalized=rms_norm,
        peak_normalized=peak_norm,
        low_energy_warning=low_energy,
    )


def is_riff_wav(data: bytes) -> bool:
    """Return True if `data` begins with a 44+ byte RIFF/WAVE header."""
    return len(data) >= 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def wrap_raw_pcm_as_wav(
    raw_pcm: bytes,
    *,
    sample_rate_hz: int = 22_050,
    num_channels: int = 1,
    sample_width_bytes: int = 2,
) -> bytes:
    """Wrap raw 16-bit mono linear PCM bytes in a single RIFF/WAVE header.

    If `raw_pcm` already has a RIFF/WAVE header, validates the full WAV container
    and returns it without double-wrapping.
    """
    if is_riff_wav(raw_pcm):
        inspect_and_validate_tts_wav(
            bytes(raw_pcm), expected_sample_rate_hz=sample_rate_hz
        )
        return bytes(raw_pcm)
    if not raw_pcm:
        raise AudioValidationError("Cannot wrap empty raw PCM payload as WAV.")
    if len(raw_pcm) % (num_channels * sample_width_bytes) != 0:
        raise AudioValidationError(
            f"Raw PCM byte length ({len(raw_pcm)}) is not aligned to frame size "
            f"({num_channels * sample_width_bytes} bytes)."
        )

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width_bytes)
        wf.setframerate(sample_rate_hz)
        wf.writeframes(raw_pcm)
    return buf.getvalue()


def generate_sine_wav_bytes(
    *,
    duration_sec: float = 0.5,
    freq_hz: float = 440.0,
    amplitude: float = 0.25,
    sample_rate_hz: int = REQUIRED_SAMPLE_RATE_HZ,
) -> bytes:
    """Generate a deterministic 16 kHz, 16-bit mono PCM sine-wave WAV for unit tests."""
    num_samples = max(1, int(duration_sec * sample_rate_hz))
    clamped_amp = max(0.0, min(0.99, amplitude))
    samples = [
        int(
            clamped_amp
            * 32767.0
            * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate_hz))
        )
        for i in range(num_samples)
    ]
    pcm_bytes = struct.pack(f"<{num_samples}h", *samples)
    return wrap_raw_pcm_as_wav(
        pcm_bytes,
        sample_rate_hz=sample_rate_hz,
        num_channels=1,
        sample_width_bytes=2,
    )


def generate_synthetic_speech_wav_bytes(
    *,
    duration_sec: float = 1.2,
    sample_rate_hz: int = REQUIRED_SAMPLE_RATE_HZ,
) -> bytes:
    """Synthesize a deterministic voiced vowel-formant / syllable-modulated 16 kHz WAV.

    Combines a fundamental pitch (`F0 = 125 Hz`) with vowel-formant resonances
    (`F1 = 700 Hz`, `F2 = 1200 Hz`, `F3 = 2500 Hz`) and a 4 Hz syllable envelope so
    VAD/endpointing filters observe realistic voice band energy during protocol
    smoke tests.

    NOTE: Synthetic formant audio tests HTTP/WebSocket protocol roundtrip,
    authentication, and VAD energy admission rather than human ASR word recognition
    accuracy.
    """
    num_samples = max(1, int(duration_sec * sample_rate_hz))
    f0 = 125.0
    f1 = 700.0
    f2 = 1200.0
    f3 = 2500.0
    syllable_rate_hz = 4.0

    samples: list[int] = []
    for i in range(num_samples):
        t = i / float(sample_rate_hz)
        # 25 ms fade-in/out edge taper to avoid click transients
        edge_window = min(1.0, t / 0.025, max(0.0, (duration_sec - t) / 0.025))
        # Syllable-rate amplitude modulation in [0.15, 1.0]
        syllable_env = 0.15 + 0.85 * (
            0.5 * (1.0 - math.cos(2.0 * math.pi * syllable_rate_hz * t))
        )
        voiced_carrier = (
            0.40 * math.sin(2.0 * math.pi * f0 * t)
            + 0.30 * math.sin(2.0 * math.pi * f1 * t)
            + 0.20 * math.sin(2.0 * math.pi * f2 * t)
            + 0.10 * math.sin(2.0 * math.pi * f3 * t)
        )
        val = int(0.45 * 32767.0 * edge_window * syllable_env * voiced_carrier)
        samples.append(max(-32767, min(32767, val)))

    pcm_bytes = struct.pack(f"<{num_samples}h", *samples)
    return wrap_raw_pcm_as_wav(
        pcm_bytes,
        sample_rate_hz=sample_rate_hz,
        num_channels=1,
        sample_width_bytes=2,
    )
