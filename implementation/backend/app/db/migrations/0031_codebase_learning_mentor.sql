CREATE TABLE IF NOT EXISTS codebase_learning_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
    repo_snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
    repo_url TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    commit_sha TEXT,
    title TEXT NOT NULL,
    current_topic TEXT NOT NULL DEFAULT 'overview',
    knowledge_level TEXT NOT NULL DEFAULT 'undetermined',
    learning_progress_json TEXT NOT NULL DEFAULT '{}',
    pending_question TEXT,
    state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cls_workspace_updated ON codebase_learning_sessions(workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cls_snapshot ON codebase_learning_sessions(repo_snapshot_id);

CREATE TABLE IF NOT EXISTS codebase_learning_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES codebase_learning_sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    audio_path TEXT,
    citations_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_clm_session_sequence ON codebase_learning_messages(session_id, sequence);
