"""Opt-in tests; never contact Gnani."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import uuid

import httpx
import pytest

from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.speech_coordination import SPEECH_MIGRATION, CoordinationError, configure
from backend.app.db.postgres.gnani_dispatcher import GnaniDispatcher
from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
from backend.app.speech.audio_utils import generate_sine_wav_bytes

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires dedicated VIVA_POSTGRES_TEST_DSN")


def test_dispatch_concurrency_and_failure_reservations():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    schema = "viva_dispatch_" + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema)))
        try:
            def connect():
                conn = psycopg.connect(DSN)
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                conn.commit()
                return conn
            with connect() as conn:
                apply_migrations(conn, [CORE_MIGRATION, SPEECH_MIGRATION])
                configure(conn, max_slots=1, max_stt_ms=10000, max_tts_chars=10000, max_calls=10)
            barrier = threading.Barrier(2)
            entered = threading.Event()
            finish = threading.Event()
            calls = []
            async def handler(request):
                calls.append(request.url.path)
                entered.set()
                assert await asyncio.to_thread(finish.wait, 10)
                return httpx.Response(200, json={"success": True, "transcript": "hello"})
            def run():
                async def go():
                    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                        dispatcher = GnaniDispatcher(connect=connect, adapter=GnaniSpeechAdapter(api_key="test", http_client=client))
                        barrier.wait(timeout=10)
                        return await dispatcher.transcribe_rest(STTRequest(session_id="test"), generate_sine_wav_bytes())
                try:
                    return asyncio.run(go())
                except CoordinationError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run) for _ in range(2)]
                assert entered.wait(10)
                # Wait for the rejected contender before allowing the provider to finish.
                rejected = next(f for f in futures if f.done() or _wait_done(f))
                assert rejected.result() is None
                finish.set()
                assert sum(f.result(timeout=10) is not None for f in futures) == 1
            assert len(calls) == 1
            with connect() as conn:
                assert conn.execute("SELECT state,calls FROM viva_speech_reservations").fetchall() == [("COMMITTED", 1)]
                conn.rollback()
            async def fail(request):
                raise httpx.ConnectError("test")
            async def failure():
                async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
                    d = GnaniDispatcher(connect=connect, adapter=GnaniSpeechAdapter(api_key="test", http_client=client))
                    with pytest.raises(Exception):
                        await d.transcribe_rest(STTRequest(session_id="test"), generate_sine_wav_bytes())
                    with pytest.raises(ValueError, match="exactly one"):
                        await d.synthesize_tts(TTSRequest(session_id="test", text="word " * 1000))
            asyncio.run(failure())
            with connect() as conn:
                assert conn.execute("SELECT state,count(*) FROM viva_speech_reservations GROUP BY state ORDER BY state").fetchall() == [("COMMITTED", 1), ("STARTED", 1)]
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _wait_done(future):
    import time
    for _ in range(100):
        if future.done():
            return True
        time.sleep(.05)
    return False
