"""Live-confirmed WS compatibility mapping remains separate from REST semantics."""
import pytest
from backend.app.models.api_schemas import STTRequest
from backend.app.models.enums import ExerciseId, LanguageMode
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, build_ws_stt_init_frame


@pytest.mark.parametrize(
    ("mode", "ws_language", "rest_language", "format_name"),
    [
        (LanguageMode.EN_IN, "en-IN", "en-IN", "transcribe"),
        (LanguageMode.TA_IN, "ta-IN", "ta-IN", "transcribe"),
        (LanguageMode.TA_IN_EN_IN, "ta-IN", "ta-IN,en-IN", "codemix"),
    ],
)
def test_ws_compatibility_preserves_learner_mode_and_rest(mode, ws_language, rest_language, format_name):
    req = STTRequest(session_id="offline-language-contract", turn_generation=1,
                     exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                     language_mode=mode, source_code="def answer():\n    return 3\n")
    frame = build_ws_stt_init_frame(req)
    rest, _ = GnaniSpeechAdapter(api_key="").build_rest_stt_form_fields(req)
    assert frame["language_code"] == ws_language
    assert rest["language_code"] == rest_language
    assert frame["format"] == rest["format"] == format_name
    assert req.language_mode == mode
