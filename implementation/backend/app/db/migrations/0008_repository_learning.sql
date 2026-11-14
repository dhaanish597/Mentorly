CREATE TABLE repo_snapshots (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL, source_locator TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_hash TEXT,
 total_files INTEGER NOT NULL DEFAULT 0, files_indexed INTEGER NOT NULL DEFAULT 0,
 coverage_json TEXT NOT NULL DEFAULT '{}', failure_code TEXT
);
CREATE INDEX idx_repo_snapshots_workspace ON repo_snapshots(workspace_id,id);
CREATE TABLE repo_files (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 path TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, language TEXT NOT NULL,
 parse_status TEXT NOT NULL, imports_json TEXT NOT NULL, calls_json TEXT NOT NULL,
 symbols_json TEXT NOT NULL, rank REAL NOT NULL DEFAULT 0, UNIQUE(snapshot_id,path)
);
CREATE TABLE repo_chunks (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES repo_files(id) ON DELETE CASCADE, path TEXT NOT NULL,
 symbol TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
 chunk_hash TEXT NOT NULL, text TEXT NOT NULL
);
CREATE VIRTUAL TABLE repo_chunks_fts USING fts5(chunk_id UNINDEXED, snapshot_id UNINDEXED, text);
CREATE TRIGGER repo_chunks_delete_fts AFTER DELETE ON repo_chunks BEGIN
 DELETE FROM repo_chunks_fts WHERE chunk_id=old.id;
END;

CREATE TABLE repo_evidence_cards (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, origin TEXT NOT NULL
);
CREATE TABLE repo_defense_sessions (
 id TEXT PRIMARY KEY, studio_session_id TEXT NOT NULL UNIQUE REFERENCES studio_sessions(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 phase TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE repo_defense_answers (
 id TEXT PRIMARY KEY, defense_id TEXT NOT NULL REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL, phase TEXT NOT NULL, answer TEXT NOT NULL, citations_json TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(defense_id,sequence)
);
CREATE TABLE repo_decisions (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, rationale TEXT NOT NULL,
 learner_alternative TEXT, created_at TEXT NOT NULL
);
