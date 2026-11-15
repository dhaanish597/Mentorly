"""One bounded model attempt, with no credential-proxy inheritance or retries."""
import asyncio
import time

import httpx

class ModelThreadRequired(RuntimeError):
    """No dispatch was attempted because a synchronous adapter is on an event loop."""


def post_model(endpoint, *, payload, headers, timeout_seconds, client=None):
    if client is not None:
        # Explicit injected clients used by tests/consumers retain their API.
        started = time.monotonic()
        response = client.post(endpoint,json=payload,headers=headers,timeout=timeout_seconds)
        if time.monotonic() - started > timeout_seconds:
            raise httpx.ReadTimeout('Model deadline exceeded')
        return response

    async def request():
        async with asyncio.timeout(timeout_seconds), httpx.AsyncClient(timeout=timeout_seconds,trust_env=False) as active:
            return await active.post(endpoint,json=payload,headers=headers)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(request())
    # A synchronous adapter must not block a serving event loop. Callers needing
    # native async model work use conversation/assessment/studio adapters.
    raise ModelThreadRequired('Synchronous model adapter requires a worker thread')
