"""Phase 2 Speech Foundation Package (`backend/app/speech`).

Exports audio validation/synthesis helpers, AST keyterm extraction, pre-TTS and
post-STT normalizers, SHA-256 TTS disk caching, the Gnani Vachana REST/WS/SSE
adapter, and the single-concurrency SQLite-backed `SpeechGatekeeper`.
"""

from .ast_keyterms import (
    MAX_BIAS_KEYTERMS,
    MAX_TOPIC_CHARS,
    build_stt_topic_string,
    extract_bias_keyterms,
)
from .audio_utils import (
    LOW_ENERGY_RMS_THRESHOLD,
    MAX_STT_AUDIO_BYTES,
    MAX_STT_DURATION_SEC,
    REQUIRED_CHANNELS,
    REQUIRED_SAMPLE_RATE_HZ,
    REQUIRED_SAMPLE_WIDTH_BYTES,
    AudioValidationError,
    WavInspectionResult,
    compute_pcm16_rms_and_peak,
    generate_sine_wav_bytes,
    generate_synthetic_speech_wav_bytes,
    inspect_and_validate_stt_wav,
    inspect_and_validate_tts_wav,
    is_riff_wav,
    wrap_raw_pcm_as_wav,
)
from .gatekeeper import (
    SpeechBusyError,
    SpeechGatekeeper,
    SpeechQuotaExhaustedError,
)
from .gnani_adapter import (
    GNANI_STT_REST_URL,
    GNANI_STT_WS_URL,
    GNANI_TTS_SSE_URL,
    AssembledTTSSynthesis,
    GnaniSpeechAdapter,
    GnaniTransportError,
    build_ws_stt_commit_frame,
    build_ws_stt_init_frame,
    parse_gnani_sse_stream,
    select_gnani_stt_format,
)
from .pre_tts_normalizer import (
    MAX_TTS_CHUNK_CHARS,
    NORMALIZER_VERSION,
    to_speakable,
)
from .transcript_normalizer import (
    NormalizationProposal,
    normalize_learner_transcript,
)
from .tts_cache import TTSDiskCache

__all__ = [
    "AssembledTTSSynthesis",
    "AudioValidationError",
    "GNANI_STT_REST_URL",
    "GNANI_STT_WS_URL",
    "GNANI_TTS_SSE_URL",
    "GnaniSpeechAdapter",
    "GnaniTransportError",
    "LOW_ENERGY_RMS_THRESHOLD",
    "MAX_BIAS_KEYTERMS",
    "MAX_STT_AUDIO_BYTES",
    "MAX_STT_DURATION_SEC",
    "MAX_TOPIC_CHARS",
    "MAX_TTS_CHUNK_CHARS",
    "NORMALIZER_VERSION",
    "NormalizationProposal",
    "REQUIRED_CHANNELS",
    "REQUIRED_SAMPLE_RATE_HZ",
    "REQUIRED_SAMPLE_WIDTH_BYTES",
    "SpeechBusyError",
    "SpeechGatekeeper",
    "SpeechQuotaExhaustedError",
    "TTSDiskCache",
    "WavInspectionResult",
    "build_stt_topic_string",
    "build_ws_stt_commit_frame",
    "build_ws_stt_init_frame",
    "compute_pcm16_rms_and_peak",
    "extract_bias_keyterms",
    "generate_sine_wav_bytes",
    "generate_synthetic_speech_wav_bytes",
    "inspect_and_validate_stt_wav",
    "inspect_and_validate_tts_wav",
    "is_riff_wav",
    "normalize_learner_transcript",
    "parse_gnani_sse_stream",
    "select_gnani_stt_format",
    "to_speakable",
    "wrap_raw_pcm_as_wav",
]
