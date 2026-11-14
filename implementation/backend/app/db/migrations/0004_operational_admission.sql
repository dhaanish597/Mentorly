-- Shared fixed-window admission counters; subjects contain SHA-256 digests only.
CREATE TABLE admission_counters (
    bucket TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL CHECK (request_count >= 0),
    PRIMARY KEY (bucket, subject_hash, window_start)
);
CREATE INDEX idx_admission_counters_expiry ON admission_counters (window_start);
