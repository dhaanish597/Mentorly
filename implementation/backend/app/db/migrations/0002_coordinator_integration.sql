-- Reconcile P0 persisted rows with the extended coordinator without changing 0001.
ALTER TABLE turns RENAME COLUMN status TO state;
ALTER TABLE turns RENAME COLUMN transport TO transport_mode;
ALTER TABLE turns RENAME COLUMN confirmed_claim_json TO claim_json;
ALTER TABLE turns ADD COLUMN confirmed_at TEXT;
ALTER TABLE turns ADD COLUMN latest_capture_attempt_id INTEGER NOT NULL DEFAULT 0;
UPDATE turns SET latest_capture_attempt_id = COALESCE((SELECT MAX(attempt_seq) FROM capture_attempts WHERE turn_id = turns.id), 0);
ALTER TABLE capture_attempts RENAME COLUMN attempt_seq TO attempt_number;
ALTER TABLE case_history ADD COLUMN exercise_id TEXT NOT NULL DEFAULT '';
ALTER TABLE case_history ADD COLUMN purpose TEXT NOT NULL DEFAULT 'DIAGNOSTIC';
ALTER TABLE case_history ADD COLUMN challenge_id TEXT;
ALTER TABLE case_history ADD COLUMN created_at TEXT NOT NULL DEFAULT '';
UPDATE case_history SET exercise_id = COALESCE((SELECT exercise_id FROM sessions WHERE id = session_id), ''), created_at = first_seen_at;
ALTER TABLE session_events RENAME COLUMN event_seq TO sequence_no;
ALTER TABLE coaching_messages ADD COLUMN source_mode TEXT NOT NULL DEFAULT 'DETERMINISTIC';
ALTER TABLE coaching_messages ADD COLUMN display_text TEXT NOT NULL DEFAULT '';
ALTER TABLE coaching_messages ADD COLUMN speakable_text TEXT NOT NULL DEFAULT '';
UPDATE coaching_messages SET display_text = text, speakable_text = text;
CREATE TABLE evidence_artifacts (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
 code_version_id INTEGER NOT NULL, turn_generation INTEGER NOT NULL,
 case_hash TEXT NOT NULL, confirmed_prediction INTEGER, prediction_status TEXT NOT NULL,
 verification_status TEXT NOT NULL, minimization_status TEXT NOT NULL,
 trace_id TEXT, artifact_json TEXT NOT NULL, created_at TEXT NOT NULL
);
INSERT INTO evidence_artifacts SELECT id, session_id, challenge_id, code_version_id, turn_generation,
 COALESCE(json_extract(artifact_json,'$.case_hash'),''), json_extract(artifact_json,'$.confirmed_prediction'),
 prediction_status, verification_status, COALESCE(json_extract(artifact_json,'$.minimization_status'),'NOT_ATTEMPTED'),
 json_extract(artifact_json,'$.trace_id'), artifact_json, created_at FROM artifacts;
-- Keep historical raw trace rows; their schema remains available for migration review.
ALTER TABLE traces RENAME TO legacy_traces;
CREATE TABLE traces (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 code_version_id INTEGER NOT NULL, turn_generation INTEGER NOT NULL,
 case_hash TEXT NOT NULL, status TEXT NOT NULL, total_observed INTEGER NOT NULL,
 trace_truncated INTEGER NOT NULL, termination_reason TEXT NOT NULL,
 runtime_version TEXT NOT NULL, steps_json TEXT NOT NULL, observation_json TEXT,
 created_at TEXT NOT NULL
);
INSERT INTO traces SELECT id, session_id,
 COALESCE(json_extract(trace_json,'$.revision.code_version_id'),1),
 COALESCE(json_extract(trace_json,'$.revision.turn_generation'),0),
 COALESCE(json_extract(trace_json,'$.case_hash'),''),
 COALESCE(json_extract(trace_json,'$.status'),'TRACE_UNAVAILABLE'),total_observed,truncated,
 COALESCE(json_extract(trace_json,'$.termination_reason'),'Historical import'),
 COALESCE(json_extract(trace_json,'$.runtime_version'),'UNKNOWN'),
 COALESCE(json_extract(trace_json,'$.steps'),'[]'),json_extract(trace_json,'$.observation'),created_at
 FROM legacy_traces;
CREATE INDEX idx_evidence_session ON evidence_artifacts(session_id,created_at);
CREATE INDEX idx_trace_session_v2 ON traces(session_id,created_at);
