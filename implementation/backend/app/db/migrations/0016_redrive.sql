-- Workspace-scoped passive beginner learning, separate from studio defense epochs.
CREATE TABLE repo_learning_plans (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 snapshot_hash TEXT NOT NULL,
 steps_json TEXT NOT NULL,
 cursor INTEGER NOT NULL DEFAULT 0 CHECK(cursor >= 0),
 epoch INTEGER NOT NULL DEFAULT 1 CHECK(epoch >= 1),
 revisit_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(workspace_id,snapshot_id)
);
CREATE TABLE repo_learning_attempts (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL CHECK(sequence >= 1),
 step_id TEXT NOT NULL,
 answer TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
);
CREATE TABLE repo_learning_evidence_events (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES repo_learning_attempts(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL,
 evidence_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
);
CREATE INDEX idx_repo_learning_attempts_rate ON repo_learning_attempts(created_at,plan_id);
