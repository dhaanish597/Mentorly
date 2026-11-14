# Voice foundation repair status

Status: `IMPLEMENTED_UNVERIFIED`; live gate: `BLOCKED_EXTERNAL`.

This is a new local takeover record. The corresponding imported native Google Doc was zero bytes; its unseen content has not been reconstructed.

Observed local repairs: compatible speech-service startup/settings, shared dispatcher configuration, bounded WS/SSE handling, real provider/client ID separation with nullable confidence, source/capture freshness, cancellation, session cache and conservative uncertain usage after unconfirmed provider work.

Offline evidence is in test_speech_foundation.py, test_speech_takeover.py, test_startup_settings.py and frontend audio/streaming tests. These do not prove real recognition accuracy, capture permissions, autoplay recovery or measured barge-in latency.

The authorized one-request TTS smoke received HTTP 401. No STT or retry occurred. Obtain valid account authentication before another bounded dispatcher-controlled live attempt. Keep Linux/gVisor acceptance separate from macOS voice/UI checks.
