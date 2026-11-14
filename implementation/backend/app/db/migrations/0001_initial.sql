-- Voice Coding Coach initial database schema (Migration 0001)
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    exercise_id TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    spec_acknowledged INTEGER NOT NULL DEFAULT 1 CHECK (spec_acknowledged IN (0, 1)),
    language_mode TEXT NOT NULL,
    interaction_mode TEXT NOT NULL,
    active_code_version_id INTEGER NOT NULL DEFAULT 1,
    active_turn_generation INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'READY',
    learning_state TEXT NOT NULL DEFAULT 'EXPLAINING',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS code_versions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    code_version_id INTEGER NOT NULL,
    source_code TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    ast_symbols_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (session_id, code_version_id)
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_generation INTEGER NOT NULL,
    code_version_id INTEGER NOT NULL,
    challenge_id TEXT,
    transport TEXT NOT NULL,
    language_mode TEXT NOT NULL,
    raw_transcript TEXT,
    normalized_transcript TEXT,
    confirmed_claim_json TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capture_attempts (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    attempt_seq INTEGER NOT NULL,
    raw_transcript TEXT,
    normalized_transcript TEXT,
    provider_confidence REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (turn_id, attempt_seq)
);

CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    code_version_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    turn_generation INTEGER NOT NULL,
    input_args_json TEXT NOT NULL,
    case_hash TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('DIAGNOSTIC', 'TRANSFER')),
    reveal_state TEXT NOT NULL DEFAULT 'HIDDEN' CHECK (reveal_state IN ('HIDDEN', 'REVEALED')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_history (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    spec_version TEXT NOT NULL,
    case_hash TEXT NOT NULL,
    input_args_json TEXT NOT NULL,
    executed INTEGER NOT NULL DEFAULT 0 CHECK (executed IN (0, 1)),
    revealed INTEGER NOT NULL DEFAULT 0 CHECK (revealed IN (0, 1)),
    first_seen_at TEXT NOT NULL,
    UNIQUE (session_id, spec_version, case_hash)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    turn_generation INTEGER NOT NULL,
    code_version_id INTEGER NOT NULL,
    deadline_at TEXT,
    cancelled_at TEXT,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    code_version_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    turn_generation INTEGER NOT NULL,
    verification_status TEXT NOT NULL,
    prediction_status TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    trace_json TEXT NOT NULL,
    truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    total_observed INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coaching_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
    hint_level INTEGER NOT NULL CHECK (hint_level IN (1, 2, 3)),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS speech_jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    coaching_message_id TEXT REFERENCES coaching_messages(id) ON DELETE CASCADE,
    playback_id TEXT NOT NULL UNIQUE,
    turn_id TEXT,
    code_version_id INTEGER NOT NULL,
    turn_generation INTEGER NOT NULL,
    normalized_text_hash TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('LIVE', 'CACHED', 'DEMO')),
    status TEXT NOT NULL,
    audio_path TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    method TEXT NOT NULL,
    route TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    response_json TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, method, route, idempotency_key)
);

CREATE TABLE IF NOT EXISTS usage_reservations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    operation_type TEXT NOT NULL,
    stt_seconds REAL NOT NULL DEFAULT 0.0,
    tts_chars INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    operation_type TEXT NOT NULL,
    stt_seconds REAL NOT NULL DEFAULT 0.0,
    tts_chars INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    event_seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, event_seq)
);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at);
CREATE INDEX IF NOT EXISTS idx_code_versions_session_created ON code_versions (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_session_created ON turns (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_status_created ON turns (status, created_at);
CREATE INDEX IF NOT EXISTS idx_capture_attempts_session_created ON capture_attempts (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_capture_attempts_status_created ON capture_attempts (status, created_at);
CREATE INDEX IF NOT EXISTS idx_challenges_session_created ON challenges (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_challenges_expires_at ON challenges (expires_at);
CREATE INDEX IF NOT EXISTS idx_case_history_session_seen ON case_history (session_id, first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_session_created ON jobs (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_session_created ON artifacts (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_traces_session_created ON traces (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_coaching_messages_session_created ON coaching_messages (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_speech_jobs_session_created ON speech_jobs (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_speech_jobs_status_created ON speech_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_speech_jobs_expires_at ON speech_jobs (expires_at);
CREATE INDEX IF NOT EXISTS idx_idempotency_session_created ON idempotency_records (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_idempotency_status_created ON idempotency_records (status, created_at);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires_at ON idempotency_records (expires_at);
CREATE INDEX IF NOT EXISTS idx_usage_reservations_session_created ON usage_reservations (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_reservations_status_created ON usage_reservations (status, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_session_created ON usage_ledger (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_status_created ON usage_ledger (status, created_at);
CREATE INDEX IF NOT EXISTS idx_session_events_session_created ON session_events (session_id, created_at);
