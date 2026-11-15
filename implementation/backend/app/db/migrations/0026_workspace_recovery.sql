-- Opt-in high-entropy recovery. Never retain raw bearer credentials.
CREATE TABLE workspace_recovery (
    workspace_id TEXT PRIMARY KEY REFERENCES studio_workspaces(id) ON DELETE CASCADE,
    credential_hash TEXT NOT NULL UNIQUE,
    generation INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE workspace_recovery_attempts (
    id TEXT PRIMARY KEY,
    subject_hash TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX recovery_attempt_time ON workspace_recovery_attempts(created_at);
CREATE TABLE workspace_dsa_sessions (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE INDEX workspace_dsa_owner ON workspace_dsa_sessions(workspace_id);
CREATE TRIGGER recovery_workspace_deleted AFTER UPDATE OF deleted_at ON studio_workspaces
WHEN NEW.deleted_at IS NOT NULL BEGIN
    DELETE FROM workspace_recovery WHERE workspace_id=NEW.id;
    DELETE FROM workspace_recovery_attempts WHERE workspace_id=NEW.id;
END;
