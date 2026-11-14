"""Persistent lesson practice with compare-and-set writes and immutable evidence."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Iterator
import uuid

from fastapi import HTTPException
from backend.app.studio.routes import auth_workspace_row
from .catalog import VERSION, content_hash, encode, evaluate_answer, lesson_by_id, public_question

MAX_ANSWERS = 5
MAX_HINTS = 3
MAX_DAILY_SESSIONS = 100
MAX_DAILY_WRITES = 2000
MAX_OBSERVED_GAP_SECONDS = 300


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def transaction(conn: sqlite3.Connection, workspace_id: str, token: str) -> Iterator[None]:
    conn.execute('BEGIN IMMEDIATE')
    try:
        # Recheck expiry/deletion after acquiring the write lock, not only in the dependency.
        auth_workspace_row(conn, workspace_id, 'Bearer ' + token)
        count = conn.execute("SELECT count(*) FROM learning_events WHERE workspace_id=? AND created_at>=?",
                             (workspace_id, utc_now()[:10])).fetchone()[0]
        if count >= MAX_DAILY_WRITES:
            raise HTTPException(429, 'Daily learning write limit reached')
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def owned_session(conn: sqlite3.Connection, workspace_id: str, session_id: str) -> sqlite3.Row:
    row = conn.execute('SELECT * FROM learning_sessions WHERE id=? AND workspace_id=?',
                       (session_id, workspace_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Learning session not found')
    return row


def snapshot(row: sqlite3.Row) -> dict[str, Any]:
    lesson = json.loads(row['lesson_json'])
    messages = json.loads(row['coach_messages_json'])
    value = {'id': row['id'], 'lesson_id': row['lesson_id'], 'epoch': row['epoch'],
             'mode': 'practice', 'state': row['state'], 'language_mode': row['language_mode'],
             'catalog_version': row['catalog_version'], 'content_hash': row['content_hash'],
             'question': public_question(lesson['question']), 'coach_messages': messages,
             'answer_count': row['answer_count'], 'hint_count': row['hint_count'], 'deadline': None,
             'feedback': json.loads(row['feedback_json']) if row['feedback_json'] else None,
             'report': json.loads(row['report_json']) if row['report_json'] else None}
    if messages and messages[-1]['kind'] == 'hint':
        value['hint'] = messages[-1]['text']
    return value


def message(kind: str, text: str) -> dict[str, str]:
    return {'id': str(uuid.uuid4()), 'role': 'assistant', 'kind': kind, 'text': text}


def opening_messages(lesson: dict) -> list[dict[str, str]]:
    return [message('explanation', lesson['explanation']), message('example', lesson['example']),
            message('assessment_scope', 'Choose one objective answer. Your explanation is unassessed; this check does not establish topic mastery.')]


def record_event(conn: sqlite3.Connection, row: sqlite3.Row, kind: str, *,
                 answer_id: str | None = None, study_seconds: int = 0) -> str:
    identifier = str(uuid.uuid4())
    conn.execute('INSERT INTO learning_events(id,workspace_id,session_id,run,kind,source,answer_id,study_seconds,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                 (identifier, row['workspace_id'], row['id'], row['run'], kind,
                  'learning_engine', answer_id, study_seconds, utc_now()))
    return identifier


def create_session(conn: sqlite3.Connection, workspace_id: str, lesson_id: str,
                   language_mode: str) -> dict[str, Any]:
    lesson = lesson_by_id(lesson_id)
    if lesson is None:
        raise HTTPException(404, 'Lesson not published')
    today = utc_now()[:10]
    count = conn.execute('SELECT count(*) FROM learning_sessions WHERE workspace_id=? AND created_at>=?',
                         (workspace_id, today)).fetchone()[0]
    if count >= MAX_DAILY_SESSIONS:
        raise HTTPException(429, 'Daily practice session limit reached')
    sid, timestamp = str(uuid.uuid4()), utc_now()
    conn.execute('INSERT INTO learning_sessions(id,workspace_id,lesson_id,catalog_version,content_hash,lesson_json,language_mode,coach_messages_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (sid, workspace_id, lesson_id, VERSION, content_hash(lesson), encode(lesson),
                  language_mode, encode(opening_messages(lesson)), timestamp, timestamp))
    row = owned_session(conn, workspace_id, sid)
    record_event(conn, row, 'session.started')
    return snapshot(row)


def require_epoch(row: sqlite3.Row, epoch: int, *, active: bool = True) -> None:
    if row['epoch'] != epoch:
        raise HTTPException(409, 'Stale learning session epoch; reload the latest snapshot')
    if active and row['state'] != 'active':
        raise HTTPException(409, 'Session is not active; restart to practice again')


def observed_seconds(row: sqlite3.Row, timestamp: str) -> int:
    elapsed = (datetime.fromisoformat(timestamp) - datetime.fromisoformat(row['updated_at'])).total_seconds()
    return min(MAX_OBSERVED_GAP_SECONDS, max(0, int(elapsed)))


def award_completion(conn: sqlite3.Connection, row: sqlite3.Row, source_event: str) -> None:
    completed = conn.execute("SELECT count(DISTINCT s.lesson_id) FROM learning_events e JOIN learning_sessions s ON s.id=e.session_id WHERE e.workspace_id=? AND e.kind='lesson.completed'",
                             (row['workspace_id'],)).fetchone()[0]
    awards = [('first_lesson', 'First verified lesson')]
    if completed >= 5:
        awards.append(('five_lessons', 'Five verified lessons'))
    for identifier, title in awards:
        conn.execute('INSERT OR IGNORE INTO learning_achievements(workspace_id,id,title,earned_at,source_event) VALUES(?,?,?,?,?)',
                     (row['workspace_id'], identifier, title, utc_now(), source_event))


def answer_session(conn: sqlite3.Connection, workspace_id: str, sid: str,
                   expected_epoch: int, question_id: str, answer: str) -> dict[str, Any]:
    row = owned_session(conn, workspace_id, sid)
    require_epoch(row, expected_epoch)
    lesson = json.loads(row['lesson_json'])
    if lesson['question']['id'] != question_id:
        raise HTTPException(409, 'Question does not match the pinned lesson')
    if row['answer_count'] >= MAX_ANSWERS:
        raise HTTPException(409, 'Answer limit reached')
    feedback = evaluate_answer(lesson['question'], answer)
    timestamp, answer_id = utc_now(), str(uuid.uuid4())
    conn.execute('INSERT INTO learning_answers(id,session_id,workspace_id,run,epoch,question_id,answer,correct,evaluation_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (answer_id, sid, workspace_id, row['run'], expected_epoch, question_id, answer,
                  int(feedback['correct']), encode(feedback), timestamp))
    count = row['answer_count'] + 1
    state = 'completed' if feedback['correct'] else ('exhausted' if count >= MAX_ANSWERS else 'active')
    report = {'lesson_completed': feedback['correct'], 'mastery_awarded': False,
              'summary': 'Objective answer verified; explanation remains unassessed.' if feedback['correct'] else 'Objective answer not verified; no completion or mastery awarded.',
              'explanation_rubric': lesson['explanation_rubric']}
    messages = json.loads(row['coach_messages_json']) + [message('feedback', feedback['message'])]
    changed = conn.execute('UPDATE learning_sessions SET epoch=epoch+1,state=?,answer_count=?,coach_messages_json=?,feedback_json=?,report_json=?,updated_at=? WHERE id=? AND workspace_id=? AND epoch=?',
                           (state, count, encode(messages), encode(feedback), encode(report), timestamp,
                            sid, workspace_id, expected_epoch)).rowcount
    if changed != 1:
        raise HTTPException(409, 'Learning session changed')
    record_event(conn, row, 'answer.evaluated', answer_id=answer_id,
                 study_seconds=observed_seconds(row, timestamp))
    if feedback['correct']:
        event_id = record_event(conn, row, 'lesson.completed', answer_id=answer_id)
        award_completion(conn, row, event_id)
    return snapshot(owned_session(conn, workspace_id, sid))


def hint_session(conn: sqlite3.Connection, workspace_id: str, sid: str,
                 expected_epoch: int) -> dict[str, Any]:
    row = owned_session(conn, workspace_id, sid)
    require_epoch(row, expected_epoch)
    if row['hint_count'] >= MAX_HINTS:
        raise HTTPException(409, 'All graduated hints have been used')
    lesson = json.loads(row['lesson_json'])
    hint = lesson['hints'][row['hint_count']]
    messages = json.loads(row['coach_messages_json']) + [message('hint', hint)]
    timestamp = utc_now()
    conn.execute('UPDATE learning_sessions SET epoch=epoch+1,hint_count=hint_count+1,coach_messages_json=?,updated_at=? WHERE id=? AND workspace_id=? AND epoch=?',
                 (encode(messages), timestamp, sid, workspace_id, expected_epoch))
    record_event(conn, row, 'hint.requested', study_seconds=observed_seconds(row, timestamp))
    return snapshot(owned_session(conn, workspace_id, sid))


def restart_session(conn: sqlite3.Connection, workspace_id: str, sid: str,
                    expected_epoch: int) -> dict[str, Any]:
    row = owned_session(conn, workspace_id, sid)
    require_epoch(row, expected_epoch, active=False)
    lesson = json.loads(row['lesson_json'])
    conn.execute("UPDATE learning_sessions SET epoch=epoch+1,run=run+1,state='active',answer_count=0,hint_count=0,coach_messages_json=?,feedback_json=NULL,report_json=NULL,updated_at=? WHERE id=? AND workspace_id=? AND epoch=?",
                 (encode(opening_messages(lesson)), utc_now(), sid, workspace_id, expected_epoch))
    fresh = owned_session(conn, workspace_id, sid)
    record_event(conn, fresh, 'session.restarted')
    return snapshot(fresh)


def record_interview_completion(conn: sqlite3.Connection, workspace_id: str,
                               event: dict[str, Any]) -> str:
    """Coordinator completion hook; caller claims alone cannot create evidence.

    Call within the interview completion transaction, after its immutable report
    and interview.completed outbox event exist. No public endpoint exposes this.
    """
    sid = event.get('session_id')
    if not isinstance(sid, str):
        raise ValueError('Interview completion requires a session identifier')
    source = conn.execute("SELECT s.completed_at FROM interview_sessions s JOIN interview_reports r ON r.session_id=s.id JOIN interview_events e ON e.session_id=s.id AND e.event_type='interview.completed' WHERE s.id=? AND s.workspace_id=? AND s.state='completed' AND s.completed_at IS NOT NULL",
                          (sid, workspace_id)).fetchone()
    if source is None:
        raise ValueError('Interview completion requires durable owned report and outbox')
    identifier = f'interview:{sid}:completed'
    conn.execute('INSERT OR IGNORE INTO learning_external_events(id,workspace_id,source,source_id,kind,created_at) VALUES(?,?,?,?,?,?)',
                 (identifier, workspace_id, 'interview', sid, 'interview.completed', source['completed_at']))
    return identifier
