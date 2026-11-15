"""Initial *partial* PostgreSQL coaching schema, not connected to runtime.

Text JSON/timestamps and integer booleans match SQLite storage conventions.
Composite foreign keys intentionally strengthen ownership checks and therefore
require a compatibility/data audit before importing SQLite data. This does not
implement application-level revision publication or concurrent job admission.
Nullable references use SQL NULL; the future repository must normalize SQLite empty
challenge IDs. Referenced jobs, traces, and evidence prevent individual parent
deletion; session-wide cascade remains supported. Historical rows require audit.
"""
from .migrations import Migration

CORE_MIGRATION = Migration(1, "coaching_core", """
CREATE TABLE sessions (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
 exercise_id TEXT NOT NULL, spec_version TEXT NOT NULL,
 spec_acknowledged INTEGER NOT NULL DEFAULT 1 CHECK (spec_acknowledged IN (0,1)),
 language_mode TEXT NOT NULL, interaction_mode TEXT NOT NULL,
 active_code_version_id INTEGER NOT NULL DEFAULT 1,
 active_turn_generation INTEGER NOT NULL DEFAULT 0,
 latest_client_edit_sequence INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'READY', learning_state TEXT NOT NULL DEFAULT 'EXPLAINING',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 deleted_at TEXT, voice TEXT, spoken_language TEXT
);
CREATE TABLE code_versions (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 code_version_id INTEGER NOT NULL, source_code TEXT NOT NULL, code_hash TEXT NOT NULL,
 ast_symbols_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
 UNIQUE (session_id, code_version_id)
);
CREATE TABLE challenges (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 exercise_id TEXT NOT NULL, spec_version TEXT NOT NULL, code_version_id INTEGER NOT NULL,
 code_hash TEXT NOT NULL, turn_generation INTEGER NOT NULL, input_args_json TEXT NOT NULL,
 case_hash TEXT NOT NULL, purpose TEXT NOT NULL CHECK (purpose IN ('DIAGNOSTIC','TRANSFER')),
 reveal_state TEXT NOT NULL DEFAULT 'HIDDEN' CHECK (reveal_state IN ('HIDDEN','REVEALED')),
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 UNIQUE (session_id,id),
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id)
);
CREATE TABLE turns (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 turn_generation INTEGER NOT NULL, code_version_id INTEGER NOT NULL, challenge_id TEXT,
 transport_mode TEXT NOT NULL, language_mode TEXT NOT NULL, raw_transcript TEXT,
 normalized_transcript TEXT, claim_json TEXT, state TEXT NOT NULL, confirmed_at TEXT,
 latest_capture_attempt_id INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE (session_id,id), UNIQUE (session_id,id,challenge_id),
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id),
 FOREIGN KEY (session_id,challenge_id) REFERENCES challenges(session_id,id) ON DELETE CASCADE
);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 job_type TEXT NOT NULL, status TEXT NOT NULL, turn_generation INTEGER NOT NULL,
 code_version_id INTEGER NOT NULL, deadline_at TEXT, cancelled_at TEXT, result_json TEXT,
 error_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision_json TEXT, challenge_id TEXT,
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id),
 FOREIGN KEY (session_id,challenge_id) REFERENCES challenges(session_id,id)
);
CREATE TABLE artifacts (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 challenge_id TEXT NOT NULL, turn_id TEXT, schema_version TEXT NOT NULL,
 code_version_id INTEGER NOT NULL, code_hash TEXT NOT NULL, turn_generation INTEGER NOT NULL,
 verification_status TEXT NOT NULL, prediction_status TEXT NOT NULL,
 artifact_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id),
 FOREIGN KEY (session_id,challenge_id) REFERENCES challenges(session_id,id) ON DELETE CASCADE,
 FOREIGN KEY (session_id,turn_id,challenge_id) REFERENCES turns(session_id,id,challenge_id) ON DELETE CASCADE
);
CREATE TABLE evidence_artifacts (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 challenge_id TEXT NOT NULL, code_version_id INTEGER NOT NULL, turn_generation INTEGER NOT NULL,
 case_hash TEXT NOT NULL, confirmed_prediction INTEGER, prediction_status TEXT NOT NULL,
 verification_status TEXT NOT NULL, minimization_status TEXT NOT NULL, trace_id TEXT,
 artifact_json TEXT NOT NULL, created_at TEXT NOT NULL, confirmed_prediction_json TEXT,
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id),
 FOREIGN KEY (session_id,challenge_id) REFERENCES challenges(session_id,id) ON DELETE CASCADE
);
CREATE TABLE traces (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 code_version_id INTEGER NOT NULL, turn_generation INTEGER NOT NULL, case_hash TEXT NOT NULL,
 status TEXT NOT NULL, total_observed INTEGER NOT NULL, trace_truncated INTEGER NOT NULL,
 termination_reason TEXT NOT NULL, runtime_version TEXT NOT NULL, steps_json TEXT NOT NULL,
 observation_json TEXT, created_at TEXT NOT NULL, revision_json TEXT, challenge_id TEXT,
 UNIQUE (session_id,id),
 FOREIGN KEY (session_id,code_version_id) REFERENCES code_versions(session_id,code_version_id),
 FOREIGN KEY (session_id,challenge_id) REFERENCES challenges(session_id,id)
);
ALTER TABLE evidence_artifacts ADD CONSTRAINT evidence_trace_owner_fk
 FOREIGN KEY (session_id,trace_id) REFERENCES traces(session_id,id);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX idx_sessions_created_at ON sessions(created_at);
CREATE INDEX idx_code_versions_session_created ON code_versions(session_id,created_at);
CREATE INDEX idx_turns_session_created ON turns(session_id,created_at);
CREATE INDEX idx_turns_status_created ON turns(state,created_at);
CREATE INDEX idx_challenges_session_created ON challenges(session_id,created_at);
CREATE INDEX idx_challenges_expires_at ON challenges(expires_at);
CREATE INDEX idx_jobs_session_created ON jobs(session_id,created_at);
CREATE INDEX idx_jobs_status_created ON jobs(status,created_at);
CREATE INDEX idx_jobs_session_active ON jobs(session_id,status);
CREATE INDEX idx_artifacts_session_created ON artifacts(session_id,created_at);
CREATE INDEX idx_evidence_session ON evidence_artifacts(session_id,created_at);
CREATE INDEX idx_trace_session_v2 ON traces(session_id,created_at);
""")
