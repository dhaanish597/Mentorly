"""Bounded requests: callers choose source identity, never arbitrary speech text."""

from typing import Literal

from backend.app.models.enums import LanguageMode, SpeechLocale, TTSVoice
from pydantic import BaseModel, ConfigDict, Field, StrictInt

Module = Literal["lesson", "interview", "redrive"]
MAX_AUDIO_BASE64 = 1_398_104  # Base64 representation of the shared 1 MiB capture limit.


class STTBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    epoch: StrictInt = Field(ge=1)
    audio_base64: str = Field(min_length=1, max_length=MAX_AUDIO_BASE64)
    language_mode: LanguageMode = LanguageMode.EN_IN


class TTSBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    epoch: StrictInt = Field(ge=1)
    message_id: str = Field(min_length=1, max_length=160)
    language: SpeechLocale = SpeechLocale.EN_IN
    voice: TTSVoice = TTSVoice.AVINASH


class TranscriptResponse(BaseModel):
    raw_transcript: str = Field(max_length=4000)
    normalized_transcript: str = Field(max_length=4000)
    requires_confirmation: Literal[True] = True
    epoch: int


class AudioResponse(BaseModel):
    audio_base64: str
    content_type: Literal["audio/wav"] = "audio/wav"
    epoch: int
