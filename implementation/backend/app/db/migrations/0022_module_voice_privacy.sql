-- Keep anonymous spent/reserved credit while removing soft-deleted source linkage.
-- The 0018 AFTER DELETE trigger rolls these counts into studio_speech_deleted_daily.
CREATE TRIGGER module_speech_soft_delete_privacy
AFTER UPDATE OF deleted_at ON studio_workspaces
WHEN NEW.deleted_at IS NOT NULL
BEGIN
 DELETE FROM module_speech_usage WHERE workspace_id=NEW.id;
END;
-- Apply the same cleanup to workspaces deleted before this migration was installed.
DELETE FROM module_speech_usage
WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
