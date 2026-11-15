"""Read only authored, persisted public speech text from the owned current source."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.db.migrations import open_connection
from backend.app.studio.routes import auth_workspace_row
from backend.app.studio.security import authenticate_workspace
from fastapi import HTTPException, Request

from .schemas import Module


@dataclass(frozen=True)
class Capability:
    workspace_id: str
    token: str


@dataclass(frozen=True)
class Source:
    epoch: int
    fingerprint: str
    text: str | None


def workspace_current(db: sqlite3.Connection, capability: Capability) -> None:
    """Recheck the studio capability inside the same transaction as reservation."""
    auth_workspace_row(db, capability.workspace_id, "Bearer " + capability.token)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise HTTPException(422, "Persisted coach text unavailable; continue with text")
    return value


def _lesson_text(row: sqlite3.Row, message_id: str) -> str:
    question = json.loads(row["lesson_json"]).get("question", {})
    if question.get("id") == message_id:
        return _text(question.get("prompt"))
    messages = json.loads(row["coach_messages_json"])
    message = next((item for item in messages if item.get("id") == message_id), None)
    if (
        not message
        or message.get("role") != "assistant"
        or message.get("kind")
        not in {"explanation", "example", "hint", "feedback", "assessment_scope"}
    ):
        raise HTTPException(404, "Owned coach message unavailable")
    return _text(message.get("text"))


def _interview_text(db: sqlite3.Connection, row: sqlite3.Row, message_id: str) -> str:
    question = db.execute(
        "SELECT json_extract(question_json,'$.text') AS text FROM interview_questions WHERE session_id=? AND id=? AND epoch=?",
        (row["id"], message_id, row["epoch"]),
    ).fetchone()
    if not question:
        raise HTTPException(404, "Current interview question unavailable")
    # Deliberately exclude private indicator_ids, probe_target, topic, and report answers.
    return _text(question["text"])


def _redrive_source(
    db: sqlite3.Connection,
    request: Request,
    capability: Capability,
    session_id: str,
    epoch: int,
    message_id: str | None,
) -> Source:
    from backend.app.repo_learning.rederive import EpochConflict, get_plan

    try:
        plan = get_plan(
            request.app.state.settings.database_path,
            capability.workspace_id,
            session_id,
        )
    except LookupError as exc:
        raise HTTPException(404, "Owned learning source unavailable") from exc
    except (EpochConflict, ValueError) as exc:
        raise HTTPException(409, "Repository learning source superseded") from exc
    if plan["epoch"] != epoch or plan["current_step"] is None:
        raise HTTPException(409, "Repository learning epoch superseded")
    step = plan["current_step"]
    text = None
    if message_id is not None:
        choices = {
            step["step_id"]: step["question"],
            step["step_id"] + ":explanation": step["explanation"],
        }
        if message_id not in choices:
            raise HTTPException(404, "Current repository coach message unavailable")
        text = _text(choices[message_id])
    row = db.execute(
        "SELECT * FROM repo_learning_plans WHERE id=? AND workspace_id=?",
        (session_id, capability.workspace_id),
    ).fetchone()
    if row is None or row["epoch"] != epoch:
        raise HTTPException(409, "Repository learning epoch superseded")
    # Include current authored question since failed evidence can select a follow-up.
    fingerprint = hashlib.sha256(
        (
            json.dumps(dict(row), sort_keys=True) + json.dumps(step, sort_keys=True)
        ).encode()
    ).hexdigest()
    return Source(epoch, fingerprint, text)


def resolve(
    db: sqlite3.Connection,
    request: Request,
    capability: Capability,
    module: Module,
    session_id: str,
    epoch: int,
    message_id: str | None = None,
) -> Source:
    workspace_current(db, capability)
    if module == "redrive":
        return _redrive_source(db, request, capability, session_id, epoch, message_id)
    table = {"lesson": "learning_sessions", "interview": "interview_sessions"}[module]
    row = db.execute(
        f"SELECT * FROM {table} WHERE id=? AND workspace_id=?",
        (session_id, capability.workspace_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Owned source session unavailable")
    if row["epoch"] != epoch:
        raise HTTPException(409, "Source session epoch superseded")
    if message_id is None and row["state"] != "active":
        raise HTTPException(409, "Source session is not accepting a draft")
    if module == "interview" and (
        row["state"] != "active"
        or datetime.fromisoformat(row["deadline_at"]) <= datetime.now(UTC)
    ):
        raise HTTPException(409, "Interview question superseded or expired")
    text = (
        None
        if message_id is None
        else (
            _lesson_text(row, message_id)
            if module == "lesson"
            else _interview_text(db, row, message_id)
        )
    )
    fingerprint = hashlib.sha256(
        json.dumps(dict(row), sort_keys=True).encode()
    ).hexdigest()
    return Source(epoch, fingerprint, text)


def current(
    request: Request,
    capability: Capability,
    module: Module,
    session_id: str,
    epoch: int,
    message_id: str | None = None,
    expected: Source | None = None,
) -> Source:
    authenticate_workspace(request, capability.workspace_id, capability.token)
    with closing(open_connection(request.app.state.settings.database_path)) as db:
        source = resolve(db, request, capability, module, session_id, epoch, message_id)
    if expected is not None and source != expected:
        raise HTTPException(409, "Voice source content superseded")
    return source
