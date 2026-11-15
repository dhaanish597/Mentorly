"""SQLite-serialized interview lifecycle. All sessions belong to authenticated workspaces."""

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, Row

from backend.app.db.migrations import open_connection
from fastapi import HTTPException

from .catalog import build_plan
from .policies import POLICIES
from .reports import build_report
from .schemas import Answer, NewSession

CompletionHook = Callable[[Connection, str, dict], None]
INTRODUCTION = {
    "text": "Welcome to your interview. I will ask one question at a time and may ask for more detail. Answers are recorded neutrally; feedback is available only after the interview ends. You may finish at any time. Camera is optional and never assessed.",
    "source_refs": [],
}
ACKNOWLEDGEMENT = {"text": "Answer recorded.", "source_refs": []}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@contextmanager
def transaction(path: str) -> Iterator[Connection]:
    with closing(open_connection(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def owned(conn: Connection, session_id: str, workspace_id: str) -> Row:
    row = conn.execute(
        """SELECT s.* FROM interview_sessions s JOIN studio_workspaces w ON w.id=s.workspace_id
        WHERE s.id=? AND s.workspace_id=? AND w.deleted_at IS NULL AND w.expires_at>?""",
        (session_id, workspace_id, now_iso()),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Interview session not found")
    return row


def event(
    conn: Connection, session_id: str, kind: str, payload: dict, timestamp: str
) -> None:
    seq = conn.execute(
        "SELECT COALESCE(MAX(sequence),0)+1 FROM interview_events WHERE session_id=?",
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO interview_events VALUES(?,?,?,?,?)",
        (session_id, seq, kind, encode(payload), timestamp),
    )


def ask(
    conn: Connection, session_id: str, epoch: int, question: dict, timestamp: str
) -> None:
    sequence = conn.execute(
        "SELECT COUNT(*)+1 FROM interview_questions WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    ident = str(uuid.uuid4())
    pinned = {**question, "id": ident}
    conn.execute(
        "INSERT INTO interview_questions VALUES(?,?,?,?,?,?)",
        (ident, session_id, sequence, epoch, encode(pinned), timestamp),
    )
    event(
        conn,
        session_id,
        "interview.question",
        {"question_id": ident, "epoch": epoch},
        timestamp,
    )


def view(conn: Connection, session: Row) -> dict:
    report_row = conn.execute(
        "SELECT report_json FROM interview_reports WHERE session_id=?", (session["id"],)
    ).fetchone()
    current = conn.execute(
        "SELECT question_json FROM interview_questions WHERE session_id=? ORDER BY epoch DESC LIMIT 1",
        (session["id"],),
    ).fetchone()
    question = (
        json.loads(current["question_json"])
        if current and session["state"] == "active"
        else None
    )
    if question:
        question = {
            k: question[k] for k in ("id", "text", "kind", "parent_id", "source_refs")
        }
    answered = conn.execute(
        "SELECT 1 FROM interview_answers WHERE session_id=? LIMIT 1", (session["id"],)
    ).fetchone()
    return {
        "id": session["id"],
        "type": session["type"],
        "difficulty": session["difficulty"],
        "topics": json.loads(session["topics_json"]),
        "duration_minutes": session["duration_minutes"],
        "language_mode": session["language_mode"],
        "epoch": session["epoch"],
        "state": session["state"],
        "started_at": session["started_at"],
        "deadline_at": session["deadline_at"],
        "introduction": INTRODUCTION,
        "acknowledgement": ACKNOWLEDGEMENT if answered else None,
        "question": question,
        "report": json.loads(report_row["report_json"]) if report_row else None,
    }


def complete(
    conn: Connection, session: Row, reason: str, hook: CompletionHook | None = None
) -> Row:
    if session["state"] == "completed":
        return session
    timestamp = now_iso()
    report = build_report(conn, session, reason, timestamp)
    conn.execute(
        "INSERT INTO interview_reports VALUES(?,?,?)",
        (session["id"], encode(report), timestamp),
    )
    conn.execute(
        "UPDATE interview_sessions SET state='completed',epoch=epoch+1,completed_at=?,completion_reason=? WHERE id=? AND state='active'",
        (timestamp, reason, session["id"]),
    )
    payload = {
        "session_id": session["id"],
        "type": session["type"],
        "completion_reason": reason,
        "answered_count": report["answered_count"],
        "report_available": True,
        "correctness_assessed": False,
    }
    event(conn, session["id"], "interview.completed", payload, timestamp)
    if hook:
        hook(conn, session["workspace_id"], payload)
    return owned(conn, session["id"], session["workspace_id"])


def expire(conn: Connection, session: Row, hook: CompletionHook | None = None) -> Row:
    if session["state"] == "active" and datetime.fromisoformat(
        session["deadline_at"]
    ) <= datetime.now(UTC):
        return complete(conn, session, "timeout", hook)
    return session


def create(conn: Connection, workspace_id: str, body: NewSession) -> dict:
    owner = conn.execute(
        "SELECT 1 FROM studio_workspaces WHERE id=? AND deleted_at IS NULL AND expires_at>?",
        (workspace_id, now_iso()),
    ).fetchone()
    if not owner:
        raise HTTPException(401, "Invalid workspace capability")
    active = conn.execute(
        "SELECT COUNT(*) FROM interview_sessions WHERE workspace_id=? AND state='active' AND deadline_at>?",
        (workspace_id, now_iso()),
    ).fetchone()[0]
    daily = conn.execute(
        "SELECT COUNT(*) FROM interview_sessions WHERE workspace_id=? AND started_at>=?",
        (workspace_id, datetime.now(UTC).date().isoformat()),
    ).fetchone()[0]
    if active >= 3 or daily >= 100:
        raise HTTPException(
            429,
            "Interview workspace limit reached; finish an active session or try later",
        )
    try:
        plan = build_plan(
            body.type, body.difficulty, body.topics, body.duration_minutes
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    sid, started = str(uuid.uuid4()), datetime.now(UTC)
    deadline = started + timedelta(minutes=body.duration_minutes)
    conn.execute(
        """INSERT INTO interview_sessions
        (id,workspace_id,type,difficulty,topics_json,duration_minutes,language_mode,epoch,state,started_at,deadline_at,plan_json)
        VALUES(?,?,?,?,?,?,?,1,'active',?,?,?)""",
        (
            sid,
            workspace_id,
            body.type,
            body.difficulty,
            encode(body.topics),
            body.duration_minutes,
            body.language_mode,
            started.isoformat(),
            deadline.isoformat(),
            encode(plan),
        ),
    )
    event(
        conn,
        sid,
        "interview.started",
        {"type": body.type, "epoch": 1},
        started.isoformat(),
    )
    ask(conn, sid, 1, plan[0], started.isoformat())
    return view(conn, owned(conn, sid, workspace_id))


def submit(
    conn: Connection,
    session_id: str,
    workspace_id: str,
    body: Answer,
    hook: CompletionHook | None = None,
) -> dict:
    before = owned(conn, session_id, workspace_id)
    session = expire(conn, before, hook)
    if before["state"] == "active" and session["state"] == "completed":
        return view(conn, session)  # Timeout committed; late input never recorded.
    if session["state"] != "active":
        raise HTTPException(409, "Interview has ended")
    if body.expected_epoch != session["epoch"]:
        raise HTTPException(409, "Epoch conflict. Reload the session.")
    row = conn.execute(
        "SELECT question_json FROM interview_questions WHERE session_id=? AND epoch=?",
        (session_id, session["epoch"]),
    ).fetchone()
    question = json.loads(row["question_json"])
    timestamp = now_iso()
    conn.execute(
        "INSERT INTO interview_answers VALUES(?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            session_id,
            question["id"],
            session["epoch"],
            body.answer,
            body.code,
            timestamp,
        ),
    )
    event(
        conn,
        session_id,
        "interview.answer_recorded",
        {"question_id": question["id"], "epoch": session["epoch"]},
        timestamp,
    )
    next_question = advance_question(conn, session, question, body.answer)
    if next_question is None:
        return view(conn, complete(conn, session, "questions_exhausted", hook))
    conn.execute(
        "UPDATE interview_sessions SET epoch=epoch+1 WHERE id=?", (session_id,)
    )
    ask(conn, session_id, session["epoch"] + 1, next_question, timestamp)
    return view(conn, owned(conn, session_id, workspace_id))


def advance_question(
    conn: Connection, session: Row, question: dict, answer: str
) -> dict | None:
    if question["kind"] == "primary":
        return POLICIES[session["type"]].followup(question, answer)
    used = conn.execute(
        "SELECT COUNT(*) FROM interview_questions WHERE session_id=? AND json_extract(question_json,'$.kind')='primary'",
        (session["id"],),
    ).fetchone()[0]
    plan = json.loads(session["plan_json"])
    return plan[used] if used < len(plan) else None


def finish(
    conn: Connection,
    session_id: str,
    workspace_id: str,
    expected_epoch: int,
    hook: CompletionHook | None = None,
) -> dict:
    before = owned(conn, session_id, workspace_id)
    session = expire(conn, before, hook)
    if before["state"] == "active" and session["state"] == "completed":
        return view(conn, session)["report"]
    if session["state"] == "completed":
        if expected_epoch not in (session["epoch"], session["epoch"] - 1):
            raise HTTPException(409, "Epoch conflict. Reload the session.")
    elif expected_epoch != session["epoch"]:
        raise HTTPException(409, "Epoch conflict. Reload the session.")
    else:
        session = complete(conn, session, "finished", hook)
    return view(conn, session)["report"]


def sweep_expired(path: str, hook: CompletionHook | None = None) -> int:
    """Optional coordinator job. Reads/mutations also finalize expired sessions lazily."""
    with transaction(path) as conn:
        sessions = conn.execute(
            "SELECT s.* FROM interview_sessions s JOIN studio_workspaces w ON w.id=s.workspace_id WHERE s.state='active' AND s.deadline_at<=? AND w.deleted_at IS NULL AND w.expires_at>?",
            (now_iso(), now_iso()),
        ).fetchall()
        for session in sessions:
            complete(conn, session, "timeout", hook)
        return len(sessions)
