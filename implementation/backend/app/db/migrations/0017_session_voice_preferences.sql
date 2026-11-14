-- Additive preferences; no rewriting historical migrations or existing learner data.
ALTER TABLE sessions ADD COLUMN voice TEXT;
ALTER TABLE sessions ADD COLUMN spoken_language TEXT;
