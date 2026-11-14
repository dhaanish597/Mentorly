"""Revision-bound learning snapshots, separate from redacted historical export."""
from __future__ import annotations

import json
from typing import Any

from backend.app.db.repository import SQLiteRepository, SessionNotFoundError
from backend.app.models.domain import RevisionRef


def build_learning_snapshot(repo: SQLiteRepository, machine: Any, session_id: str) -> dict[str, Any]:
    session = repo.get_session(session_id)
    if session is None:
        raise SessionNotFoundError(f"Session not found: {session_id}")
    revision = machine.build_revision_ref(session_id)
    revision_data = revision.model_dump(mode="json")
    code = repo.get_code_version(session_id, revision.code_version_id)
    bundle = repo.export_session_bundle(session_id)
    challenges = [case for case in bundle["challenges"] if case["revision"] == revision_data]
    with repo._connect() as conn:
        rows = conn.execute(
            "SELECT id FROM evidence_artifacts WHERE session_id=? AND code_version_id=? "
            "AND turn_generation=? ORDER BY created_at,rowid",
            (session_id, revision.code_version_id, revision.turn_generation),
        ).fetchall()
        events = conn.execute(
            "SELECT payload_json FROM session_events WHERE session_id=? "
            "AND event_type='COACHING_DELIVERED' ORDER BY sequence_no DESC",
            (session_id,),
        ).fetchall()
        verification_events = conn.execute(
            "SELECT payload_json FROM session_events WHERE session_id=? "
            "AND event_type='VERIFICATION_COMPLETED' ORDER BY sequence_no DESC",
            (session_id,),
        ).fetchall()
    verification_report = next((
        payload['verification_report'] for event in verification_events
        if (payload := json.loads(event[0]))['revision'] == revision_data
    ), None)
    artifacts = [
        view for row in rows
        if (view := repo.get_artifact_view(session_id, row["id"]))
        and view["revision"] == revision_data
    ]
    turn = repo.get_active_turn(session_id)
    if turn is None:
        challenges, artifacts = [], []
    active_turn = {
        "turn_id": turn.id,
        "proposed_claim": json.loads(turn.claim_json) if turn.claim_json else None,
        "capture_attempt_id": turn.latest_capture_attempt_id,
        "turn_generation": turn.turn_generation,
        "transcript": turn.normalized_transcript,
        "state": turn.state,
    } if turn else None
    latest = next((item for item in reversed(artifacts) if item.get("reveal_state") != "HIDDEN"), None)
    trace = repo.get_trace_report(session_id, latest["trace_id"]) if latest and latest.get("trace_id") else None
    coaching = next((
        payload["coaching"] for event in events
        if (payload := json.loads(event[0]))["revision"] == revision_data
    ), None) if latest else None
    # A concurrent save/cancel cannot produce a snapshot labelled as a new revision
    # while carrying the previous revision's active evidence.
    machine.assert_revision_matches(session_id, revision)
    return {
        "session_id": session_id,
        "state": session.state,
        "learning_state": session.learning_state,
        "spec_acknowledged": session.spec_acknowledged,
        "language_mode": session.language_mode,
        "voice": session.voice,
        "spoken_language": session.spoken_language,
        "interaction_mode": session.interaction_mode,
        "latest_client_edit_sequence": session.latest_client_edit_sequence,
        "source_code": code.source_code if code else "",
        "revision": revision_data,
        "challenges": challenges,
        "evidence_artifacts": artifacts,
        "active_turn": active_turn,
        "trace_report": trace,
        "coaching": coaching,
        "verification_report": verification_report,
        "prior_artifact_id": repo.get_prior_failing_artifact_id(session_id, revision),
    }
