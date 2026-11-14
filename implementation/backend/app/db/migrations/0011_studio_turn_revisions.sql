-- Preserve immutable learner content while linking successive corrections.
ALTER TABLE studio_turns ADD COLUMN transcript_revision INTEGER NOT NULL DEFAULT 1 CHECK(transcript_revision >= 1);
ALTER TABLE studio_turns ADD COLUMN superseded_by TEXT REFERENCES studio_turns(id) ON DELETE SET NULL;
CREATE INDEX studio_turns_current ON studio_turns(session_id,superseded_by,created_at);
