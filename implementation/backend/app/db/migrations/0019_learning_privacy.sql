-- Additive upgrade: never change already-applied 0014 learning checksums.
CREATE TABLE learning_evidence_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL CHECK(id IN ('first_interview','three_study_days')),
 title TEXT NOT NULL, earned_at TEXT NOT NULL, source_event TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('learning_engine','interview')),
 PRIMARY KEY(workspace_id,id)
);
CREATE TRIGGER learning_evidence_achievement_guard BEFORE INSERT ON learning_evidence_achievements
BEGIN
 SELECT CASE WHEN NOT (
  (NEW.id='first_interview' AND NEW.source='interview' AND EXISTS (
   SELECT 1 FROM learning_external_events e WHERE e.id=NEW.source_event
   AND e.workspace_id=NEW.workspace_id AND e.source='interview' AND e.kind='interview.completed'
  )) OR
  (NEW.id='three_study_days' AND NEW.source='learning_engine' AND EXISTS (
   SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
   AND e.kind IN ('answer.evaluated','hint.requested') AND date(e.created_at)=date(NEW.earned_at)
  ) AND (
   SELECT count(DISTINCT date(e.created_at)) FROM learning_events e
   WHERE e.workspace_id=NEW.workspace_id AND e.kind IN ('answer.evaluated','hint.requested')
   AND date(e.created_at) BETWEEN date(NEW.earned_at,'-2 days') AND date(NEW.earned_at)
  )=3)
 ) THEN RAISE(ABORT,'Achievement requires verified owned evidence and threshold') END;
END;
CREATE TRIGGER learning_evidence_achievement_immutable BEFORE UPDATE ON learning_evidence_achievements
BEGIN SELECT RAISE(ABORT,'Learning evidence achievements are immutable'); END;
CREATE TRIGGER learning_action_badge_cascade AFTER DELETE ON learning_events
BEGIN
 DELETE FROM learning_evidence_achievements WHERE source='learning_engine' AND source_event=OLD.id;
END;
CREATE TRIGGER learning_external_badge_cascade AFTER DELETE ON learning_external_events
BEGIN
 DELETE FROM learning_evidence_achievements WHERE source='interview' AND source_event=OLD.id;
END;
CREATE TRIGGER learning_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces
WHEN NEW.deleted_at IS NOT NULL
BEGIN
 DELETE FROM learning_sessions WHERE workspace_id=NEW.id;
 DELETE FROM learning_external_events WHERE workspace_id=NEW.id;
 DELETE FROM learning_evidence_achievements WHERE workspace_id=NEW.id;
END;
CREATE TRIGGER learning_interview_delete AFTER DELETE ON interview_sessions
BEGIN
 DELETE FROM learning_external_events WHERE source='interview' AND source_id=OLD.id;
END;
-- Existing soft-deleted workspaces must also be purged during the upgrade.
DELETE FROM learning_sessions WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
DELETE FROM learning_external_events WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
DELETE FROM learning_evidence_achievements WHERE workspace_id IN (SELECT id FROM studio_workspaces WHERE deleted_at IS NOT NULL);
