"""Event-derived progress; objective lesson completion is not topic mastery."""
from __future__ import annotations

from datetime import date, timedelta
import json
import sqlite3
from typing import Any

from .catalog import public_catalog


def _streak(days: set[str], today: date | None = None) -> int:
    cursor = today or date.today()
    if cursor.isoformat() not in days:
        cursor -= timedelta(days=1)
    result = 0
    while cursor.isoformat() in days:
        result += 1
        cursor -= timedelta(days=1)
    return result


def _interviews(conn: sqlite3.Connection, workspace_id: str) -> list[dict[str, Any]]:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'interview_sessions', 'interview_reports', 'interview_events'} <= tables:
        return []
    # The durable source outbox remains authoritative even if the optional hook was not wired.
    rows = conn.execute("SELECT s.id,s.type,s.completed_at FROM interview_sessions s JOIN interview_reports r ON r.session_id=s.id WHERE s.workspace_id=? AND s.state='completed' AND s.completed_at IS NOT NULL AND EXISTS(SELECT 1 FROM interview_events e WHERE e.session_id=s.id AND e.event_type='interview.completed') ORDER BY s.completed_at DESC", (workspace_id,)).fetchall()
    return [{'id': f'interview:{row["id"]}:completed', 'source_event': f'interview:{row["id"]}:completed',
             'type': 'interview.completed', 'title': f'{row["type"]} interview',
             'created_at': row['completed_at'], 'session_id': row['id'],
             'summary': 'Interview report persisted; correctness and mastery unassessed.'} for row in rows]


def _recommendations(conn: sqlite3.Connection, workspace_id: str,
                     completed: set[str], lessons: list[dict]) -> list[dict[str, str]]:
    active = conn.execute("SELECT lesson_id,id FROM learning_sessions WHERE workspace_id=? AND state='active' ORDER BY updated_at DESC", (workspace_id,)).fetchall()
    resumes = {row['lesson_id']: row['id'] for row in reversed(active)}
    result = []
    for lesson in lessons:
        identifier = lesson['id']
        if identifier in resumes:
            reason = 'Resume your saved practice session.'
            url = f'/learn/{identifier}?session={resumes[identifier]}'
        elif identifier not in completed and set(lesson['prerequisites']) <= completed:
            reason = 'Start this foundation lesson.' if not lesson['prerequisites'] else 'Required prerequisite lessons have verified objective completions.'
            url = f'/learn/{identifier}'
        else:
            continue
        result.append({'lesson_id': identifier, 'title': lesson['title'], 'reason': reason, 'url': url})
    return result


def progress_snapshot(conn: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
    lessons = [lesson for track in public_catalog()['tracks'] for lesson in track['lessons']]
    completed_rows = conn.execute("SELECT DISTINCT s.lesson_id FROM learning_events e JOIN learning_sessions s ON s.id=e.session_id JOIN learning_answers a ON a.id=e.answer_id AND a.correct=1 WHERE e.workspace_id=? AND e.kind='lesson.completed' AND e.source='learning_engine' ORDER BY s.lesson_id", (workspace_id,)).fetchall()
    completed = {row['lesson_id'] for row in completed_rows}
    totals = conn.execute("SELECT COALESCE(SUM(kind='answer.evaluated'),0) attempts,COALESCE(SUM(kind='session.started'),0) sessions,COALESCE(SUM(study_seconds),0) seconds FROM learning_events WHERE workspace_id=?", (workspace_id,)).fetchone()
    activity = conn.execute('SELECT e.id,e.kind,e.created_at,e.session_id,s.lesson_id,s.lesson_json FROM learning_events e JOIN learning_sessions s ON s.id=e.session_id WHERE e.workspace_id=? ORDER BY e.created_at DESC LIMIT 25', (workspace_id,)).fetchall()
    recent = [{'id': row['id'], 'source_event': row['id'], 'type': row['kind'],
               'created_at': row['created_at'], 'session_id': row['session_id'],
               'lesson_id': row['lesson_id'], 'title': json.loads(row['lesson_json'])['title']}
              for row in activity]
    interviews = _interviews(conn, workspace_id)
    days = {row[0] for row in conn.execute("SELECT DISTINCT substr(created_at,1,10) FROM learning_events WHERE workspace_id=? AND kind IN ('answer.evaluated','hint.requested')", (workspace_id,))}
    days |= {event['created_at'][:10] for event in interviews}
    achievements = [dict(row) for row in conn.execute('SELECT id,title,earned_at,source_event FROM learning_achievements WHERE workspace_id=? ORDER BY earned_at,id', (workspace_id,))]
    return {'lessons_completed': len(completed), 'attempts': totals['attempts'], 'topics_mastered': 0,
            'practice_sessions': totals['sessions'], 'interviews_completed': len(interviews),
            'study_seconds': totals['seconds'], 'streak': _streak(days),
            'completed_lesson_ids': sorted(completed), 'achievements': achievements,
            'recommendations': _recommendations(conn, workspace_id, completed, lessons),
            'recent_activity': sorted(recent + interviews, key=lambda e: e['created_at'], reverse=True)[:25]}
