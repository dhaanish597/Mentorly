-- Repository-only retry state follows every privacy deletion path through FKs.
CREATE TABLE repo_idempotency (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 operation TEXT NOT NULL, key TEXT NOT NULL, input_hash TEXT NOT NULL,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 studio_session_id TEXT REFERENCES studio_sessions(id) ON DELETE CASCADE,
 defense_id TEXT REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 evidence_card_id TEXT REFERENCES repo_evidence_cards(id) ON DELETE CASCADE,
 decision_id TEXT REFERENCES repo_decisions(id) ON DELETE CASCADE,
 response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,operation,key)
);
CREATE INDEX idx_repo_idempotency_snapshot ON repo_idempotency(snapshot_id);
CREATE INDEX idx_repo_idempotency_defense ON repo_idempotency(defense_id);

-- Native prompt events carry source identifiers; purge them on every snapshot
-- deletion/cascade while preserving unrelated learner and studio events.
CREATE TRIGGER repo_snapshot_delete_authored_prompt_events BEFORE DELETE ON repo_snapshots BEGIN
 DELETE FROM studio_events
 WHERE event_type='coach.action' AND json_valid(payload_json)
 AND json_extract(payload_json,'$.source')='authored_repo_defense'
 AND json_extract(payload_json,'$.snapshot_id')=old.id;
END;

-- Keep the original answer schema compatible with existing studio consumers.
CREATE TABLE repo_defense_answer_evidence (
 answer_id TEXT PRIMARY KEY REFERENCES repo_defense_answers(id) ON DELETE CASCADE,
 evidence_links_json TEXT NOT NULL DEFAULT '[]',
 changed_requirement TEXT, learner_alternative TEXT,
 unknowns_json TEXT NOT NULL DEFAULT '[]'
);
