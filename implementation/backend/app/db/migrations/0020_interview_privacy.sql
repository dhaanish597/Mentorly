-- Studio deletes workspaces by tombstone, so FK hard-delete cascade is not enough.
CREATE TRIGGER interview_workspace_soft_delete
AFTER UPDATE OF deleted_at ON studio_workspaces
WHEN NEW.deleted_at IS NOT NULL
BEGIN
 DELETE FROM interview_sessions WHERE workspace_id=NEW.id;
END;
-- Also purge data owned by workspaces tombstoned before this upgrade.
DELETE FROM interview_sessions
 WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
