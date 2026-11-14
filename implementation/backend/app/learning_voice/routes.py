"""Mount exported router under /api/v1; workspace capabilities own all sources."""
from __future__ import annotations

import asyncio
import base64
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response

from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.speech.audio_utils import inspect_and_validate_stt_wav, inspect_and_validate_tts_wav
from backend.app.speech.capabilities import resolve_tts_selection
from backend.app.speech.pre_tts_normalizer import to_speakable
from . import provider
from .schemas import AudioResponse, Module, STTBody, TTSBody, TranscriptResponse
from .sources import Capability, current

router = APIRouter(prefix='/module-voice', tags=['module-voice'])
WorkspaceId = Annotated[str, Header(alias='X-Workspace-Id', min_length=1, max_length=128)]
WorkspaceToken = Annotated[str, Header(alias='X-Workspace-Token', min_length=1, max_length=128)]


@router.post('/{module}/{session_id}/stt', response_model=TranscriptResponse)
async def stt(module: Module, session_id: str, data: STTBody, request: Request, response: Response,
              x_workspace_id: WorkspaceId, x_workspace_token: WorkspaceToken) -> TranscriptResponse:
    capability = Capability(x_workspace_id, x_workspace_token)
    source = await asyncio.to_thread(current, request, capability, module, session_id, data.epoch)
    try:
        audio = base64.b64decode(data.audio_base64, validate=True)
        info = inspect_and_validate_stt_wav(audio)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, 'Invalid bounded 16 kHz mono PCM WAV') from exc
    outbound = STTRequest(session_id=session_id, turn_generation=data.epoch,
                          language_mode=data.language_mode, source_code='',
                          topic_override='Learning and engineering discussion')
    result = await provider.run(request, capability, module, session_id, data.epoch, None,
                                source, info.duration_sec, 0, 1,
                                lambda: provider.adapter(request).transcribe_rest(outbound, audio))
    response.headers['Cache-Control'] = 'no-store'
    return TranscriptResponse(raw_transcript=result.raw_transcript,
                              normalized_transcript=result.normalized_transcript, epoch=data.epoch)


@router.post('/{module}/{session_id}/tts', response_model=AudioResponse)
async def tts(module: Module, session_id: str, data: TTSBody, request: Request, response: Response,
              x_workspace_id: WorkspaceId, x_workspace_token: WorkspaceToken) -> AudioResponse:
    capability = Capability(x_workspace_id, x_workspace_token)
    source = await asyncio.to_thread(current, request, capability, module, session_id, data.epoch, data.message_id)
    try:
        selection = resolve_tts_selection(spoken_language=data.language, voice=data.voice,
                                         model=request.app.state.settings.gnani_tts_model)
    except ValueError as exc:
        raise HTTPException(422, 'Unsupported documented speech selection') from exc
    chunks = to_speakable(source.text)
    if not chunks or not any(chunk.strip() for chunk in chunks):
        raise HTTPException(422, 'No speakable persisted coach text')
    outbound = TTSRequest(session_id=session_id, turn_generation=data.epoch,
                          turn_id=data.message_id, text=source.text, **selection)
    result = await provider.run(request, capability, module, session_id, data.epoch, data.message_id,
                                source, 0, sum(len(chunk) for chunk in chunks), len(chunks),
                                lambda: provider.adapter(request).synthesize_tts(outbound))
    try:
        inspect_and_validate_tts_wav(result.wav_bytes)
    except ValueError as exc:
        raise HTTPException(503, 'Cloud speech returned invalid audio; continue with text') from exc
    response.headers['Cache-Control'] = 'no-store'
    return AudioResponse(audio_base64=base64.b64encode(result.wav_bytes).decode(), epoch=data.epoch)
