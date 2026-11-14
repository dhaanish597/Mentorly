CREATE TABLE studio_workspaces (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE studio_sessions (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id), token_hash TEXT NOT NULL,
 mode TEXT NOT NULL, posture TEXT NOT NULL, scenario_id TEXT NOT NULL, scenario_version TEXT NOT NULL,
 repo_snapshot_id TEXT, epoch INTEGER NOT NULL DEFAULT 1, diagram_revision INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, expires_at TEXT NOT NULL, deleted_at TEXT,
 deadline_at TEXT, paused_at TEXT, remaining_seconds INTEGER, scenario_hash TEXT NOT NULL DEFAULT '', scenario_json TEXT NOT NULL DEFAULT '{}', constraint_index INTEGER NOT NULL DEFAULT 0, hint_level INTEGER NOT NULL DEFAULT 0, cleaned_at TEXT
);
CREATE INDEX studio_session_workspace ON studio_sessions(workspace_id);
CREATE TABLE studio_diagrams (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, revision INTEGER NOT NULL,
 parent_revision INTEGER, graph_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,revision)
);
CREATE TABLE studio_events (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, sequence INTEGER NOT NULL,
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
);
CREATE TABLE studio_idempotency (
 owner_id TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, key TEXT NOT NULL,
 digest TEXT NOT NULL, status INTEGER NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,method,path,key)
);
CREATE TABLE studio_turns (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch INTEGER NOT NULL, diagram_revision INTEGER NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE studio_proposals (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 base_revision INTEGER NOT NULL, graph_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE studio_review_cards (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 prompt TEXT NOT NULL, evidence_json TEXT NOT NULL, fsrs_json TEXT NOT NULL, due_at TEXT NOT NULL
);
CREATE INDEX studio_review_due ON studio_review_cards(workspace_id,due_at);
