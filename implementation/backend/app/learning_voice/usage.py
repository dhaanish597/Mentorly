"""One transactional ledger joins all shared speech budgets without storing content."""

from __future__ import annotations
from backend.app.db.migrations import database_target

from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.config import validated_credential
from backend.app.db.migrations import open_connection
from backend.app.speech.gatekeeper import accounted_speech_totals
from fastapi import HTTPException, Request

from .schemas import Module
from .sources import Capability, Source, resolve

COUNTED = "('RESERVED','COMMITTED','UNCERTAIN')"


def reserve(
    request: Request,
    capability: Capability,
    module: Module,
    session_id: str,
    epoch: int,
    message_id: str | None,
    expected: Source,
    seconds: float,
    chars: int,
    calls: int,
) -> str:
    settings = request.app.state.settings
    with closing(open_connection(database_target(settings))) as db:
        db.execute("BEGIN IMMEDIATE")
        if (
            resolve(db, request, capability, module, session_id, epoch, message_id)
            != expected
        ):
            raise HTTPException(409, "Voice source superseded")
        if not validated_credential(settings.gnani_api_key):
            raise HTTPException(503, "Cloud speech unavailable; continue with text")
        today = datetime.now(UTC).isoformat()
        ledgers = ("usage_reservations", "studio_speech_usage", "module_speech_usage", "codebase_speech_usage")
        total_seconds, total_chars = accounted_speech_totals(db)
        daily_calls = 0
        source_seconds, source_chars = 0.0, 0
        for table in ledgers:
            daily_calls += db.execute(
                f"SELECT COALESCE(SUM(request_count),0) FROM {table} WHERE status IN {COUNTED} AND date(created_at)=date(?)",
                (today,),
            ).fetchone()[0]
            where = (
                "workspace_id=? AND module=? AND source_id=?"
                if table == "module_speech_usage"
                else "session_id=?"
            )
            params = (
                (capability.workspace_id, module, session_id)
                if table == "module_speech_usage"
                else (session_id,)
            )
            usage = db.execute(
                f"SELECT COALESCE(SUM(stt_seconds),0),COALESCE(SUM(tts_chars),0) FROM {table} WHERE {where} AND status IN {COUNTED}",
                params,
            ).fetchone()
            source_seconds += usage[0]
            source_chars += usage[1]
        daily_calls += db.execute(
            "SELECT COALESCE(SUM(request_count),0) FROM studio_speech_deleted_daily WHERE day=date(?)",
            (today,),
        ).fetchone()[0]
        gate = request.app.state.speech.gatekeeper
        if (
            source_seconds + seconds > settings.max_stt_seconds_per_session
            or source_chars + chars > settings.max_tts_chars_per_session
            or daily_calls + calls > settings.global_daily_call_limit
            or total_seconds + seconds > gate.max_stt_seconds_budget
            or total_chars + chars > gate.max_tts_chars_budget
        ):
            raise HTTPException(429, "Speech quota exhausted; continue with text")
        rid = str(uuid4())
        db.execute(
            "INSERT INTO module_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                capability.workspace_id,
                session_id,
                module,
                epoch,
                "TTS" if message_id is not None else "STT",
                seconds,
                chars,
                calls,
                "RESERVED",
                today,
                today,
            ),
        )
        db.commit()
        return rid


def settle(request: Request, reservation_id: str | None, status: str) -> None:
    if reservation_id is None:
        return
    with closing(open_connection(database_target(request.app.state.settings))) as db:
        # A reservation is created only immediately before dispatch; failures retain credit.
        db.execute(
            "UPDATE module_speech_usage SET status=?,updated_at=? WHERE id=? AND status='RESERVED'",
            (status, datetime.now(UTC).isoformat(), reservation_id),
        )
