"""Single shared speech admission and disconnect-safe provider lifetime."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException, Request

from backend.app.core.config import validated_credential
from backend.app.speech.gatekeeper import SpeechBusyError
from backend.app.speech.gnani_adapter import GnaniTransportError
from backend.app.speech.routes import _await_connected_voice
from backend.app.studio.speech import NeutralAdapter, speech_slot
from . import usage
from .schemas import Module
from .sources import Capability, Source, current

PROVIDER_DEADLINE_SECONDS = 60.0
T = TypeVar('T')


def adapter(request: Request) -> NeutralAdapter:
    settings = request.app.state.settings
    key = validated_credential(settings.gnani_api_key)
    if not key:
        raise HTTPException(503, 'Cloud speech unavailable; continue with text')
    base = settings.gnani_base_url.rstrip('/')
    # No cache is supplied: module source audio is private and not retained on disk.
    return NeutralAdapter(api_key=key, stt_endpoint=base + '/stt/v3',
                          tts_endpoint=base + '/api/v1/tts/sse')


async def run(request: Request, capability: Capability, module: Module, session_id: str,
              epoch: int, message_id: str | None, source: Source,
              seconds: float, chars: int, calls: int, dispatch: Callable[[], Awaitable[T]]) -> T:
    async def check() -> None:
        await asyncio.to_thread(current, request, capability, module, session_id, epoch, message_id, source)

    reservation_id = None
    status = 'UNCERTAIN'
    try:
        await check()
        async with speech_slot(request):
            await check()
            # Reservation performs the final ownership + CAS check atomically. It cannot
            # outlive cancellation: SQLite admission is local, short, and has no await.
            reservation_id = usage.reserve(request, capability, module, session_id, epoch,
                                           message_id, source, seconds, chars, calls)
            result = await asyncio.wait_for(_await_connected_voice(request, dispatch()),
                                            timeout=PROVIDER_DEADLINE_SECONDS)
            status = 'COMMITTED'
            await check()
            return result
    except SpeechBusyError as exc:
        raise HTTPException(429, 'Speech busy; continue with text') from exc
    except (TimeoutError, GnaniTransportError) as exc:
        raise HTTPException(503, 'Cloud speech unavailable; continue with text') from exc
    except asyncio.CancelledError as exc:
        raise HTTPException(409, 'Voice request cancelled or superseded; continue with text') from exc
    finally:
        # Even on disconnect, provider cancellation has been awaited before slot exit.
        usage.settle(request, reservation_id, status)
