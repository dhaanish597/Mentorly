-- Optional semantic quality is versioned evidence and can never grant objective credit.
CREATE TABLE interview_semantic_reviews (
 answer_id TEXT PRIMARY KEY REFERENCES interview_answers(id) ON DELETE CASCADE,
 review_json TEXT NOT NULL CHECK(json_valid(review_json))
);
CREATE TRIGGER interview_semantic_review_immutable BEFORE UPDATE ON interview_semantic_reviews
BEGIN SELECT RAISE(ABORT,'Interview semantic reviews are immutable'); END;
CREATE TABLE learning_explanation_reviews (
 answer_id TEXT PRIMARY KEY REFERENCES learning_answers(id) ON DELETE CASCADE,
 explanation TEXT NOT NULL CHECK(length(explanation) BETWEEN 1 AND 12000),
 review_json TEXT NOT NULL CHECK(json_valid(review_json))
);
CREATE TRIGGER learning_explanation_review_immutable BEFORE UPDATE ON learning_explanation_reviews
BEGIN SELECT RAISE(ABORT,'Learning explanation reviews are immutable'); END;
CREATE TABLE assessment_model_usage (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_type TEXT NOT NULL CHECK(source_type IN ('interview','learning')),
 session_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
 request_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL, model TEXT NOT NULL,
 UNIQUE(source_type,session_id,revision)
);
CREATE TABLE assessment_model_deleted_daily (
 day TEXT PRIMARY KEY, request_count INTEGER NOT NULL CHECK(request_count>=0)
);
CREATE TRIGGER assessment_model_deleted_accounting BEFORE DELETE ON assessment_model_usage
BEGIN
 INSERT INTO assessment_model_deleted_daily(day,request_count) VALUES(date(OLD.created_at),1)
 ON CONFLICT(day) DO UPDATE SET request_count=request_count+1;
END;
