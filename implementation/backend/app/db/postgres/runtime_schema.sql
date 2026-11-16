-- Complete coordinator schema. Generated from pristine authored SQLite migrations.

-- Text JSON/timestamps and integer booleans retain existing service contracts.

-- BEGIN IMMEDIATE is serialized across processes by PostgreSQL advisory lock.


CREATE FUNCTION viva_datetime(value text, VARIADIC modifiers text[] DEFAULT ARRAY[]::text[])
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE moment timestamptz; modifier text;
BEGIN
 IF value IS NULL THEN RETURN NULL; END IF;
 IF value='now' THEN moment:=CURRENT_TIMESTAMP; ELSE moment:=value::timestamptz; END IF;
 FOREACH modifier IN ARRAY modifiers LOOP
  IF modifier !~ '^[+-][0-9]+ (day|days|minute|minutes|second|seconds)$' THEN RETURN NULL; END IF;
  moment:=moment+modifier::interval;
 END LOOP;
 RETURN to_char(moment AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS');
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_time_zone_displacement_value THEN RETURN NULL;
END $$;
CREATE FUNCTION viva_date(value text, VARIADIC modifiers text[] DEFAULT ARRAY[]::text[])
RETURNS text LANGUAGE SQL STABLE AS $$ SELECT substring(viva_datetime(value,VARIADIC modifiers),1,10) $$;
CREATE FUNCTION viva_julianday(value text) RETURNS double precision LANGUAGE plpgsql STABLE AS $$
BEGIN RETURN extract(epoch FROM value::timestamptz)/86400.0+2440587.5;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_time_zone_displacement_value THEN RETURN NULL;
END $$;
CREATE FUNCTION viva_json_valid(value text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN PERFORM value::jsonb; RETURN value IS NOT NULL;
EXCEPTION WHEN invalid_text_representation THEN RETURN false;
END $$;
CREATE FUNCTION viva_json_extract(value text, path text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF path !~ '^\$\.[a-zA-Z_][a-zA-Z_0-9]*(\.[a-zA-Z_][a-zA-Z_0-9]*)*$' THEN
  RAISE EXCEPTION 'Unsupported JSON path';
 END IF;
 RETURN value::jsonb #>> string_to_array(substring(path,3),'.');
END $$;
CREATE FUNCTION viva_json_each(value text) RETURNS TABLE(key text,value text) LANGUAGE SQL IMMUTABLE AS $$
 SELECT (ordinality-1)::text,element::text FROM jsonb_array_elements($1::jsonb) WITH ORDINALITY AS e(element,ordinality)
$$;



CREATE SCHEMA IF NOT EXISTS viva_provider_coordination;
CREATE TABLE IF NOT EXISTS viva_provider_coordination.accounts (
 account_hash TEXT PRIMARY KEY,
 capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 32)
);
CREATE TABLE IF NOT EXISTS viva_provider_coordination.leases (
 id TEXT PRIMARY KEY,
 account_hash TEXT NOT NULL REFERENCES viva_provider_coordination.accounts(account_hash),
 fence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('UNDISPATCHED','INFLIGHT','UNCERTAIN','RELEASED')),
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS provider_account_active ON viva_provider_coordination.leases(account_hash,state);


CREATE TABLE runtime_maintenance_owner (
 id TEXT PRIMARY KEY, owner TEXT,
 generation BIGINT NOT NULL DEFAULT 0,
 expires_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity'
);

CREATE TABLE runtime_transfer_history (
 content_hash TEXT PRIMARY KEY, imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 table_count INTEGER NOT NULL, row_count BIGINT NOT NULL
);

CREATE TABLE achievements (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  icon TEXT NOT NULL,
  category TEXT NOT NULL,
  xp_reward BIGINT NOT NULL DEFAULT 100
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE admission_counters (
    bucket TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    request_count BIGINT NOT NULL CHECK (request_count >= 0),
    PRIMARY KEY (bucket, subject_hash, window_start)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE assessment_model_deleted_daily (
 day TEXT PRIMARY KEY, request_count BIGINT NOT NULL CHECK(request_count>=0)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_dispatch_fences (
 usage_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, token TEXT NOT NULL, operation TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PREPARED','DISPATCHING','SETTLED','FENCED'))
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_model_deleted_daily(day TEXT PRIMARY KEY, request_count BIGINT NOT NULL, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_model_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, operation TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_provider_requests (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','DONE')),
 created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_request_fences (
 request_id TEXT PRIMARY KEY, token TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ACTIVE','FENCED','DONE'))
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_speech_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, operation TEXT NOT NULL,
 stt_seconds DOUBLE PRECISION NOT NULL, tts_chars BIGINT NOT NULL, request_count BIGINT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')), created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE daily_quizzes (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  category TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  question TEXT NOT NULL,
  options_json TEXT NOT NULL,
  correct_option_index BIGINT NOT NULL,
  explanation TEXT NOT NULL,
  xp_reward BIGINT NOT NULL DEFAULT 50,
  created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE dsa_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count BIGINT NOT NULL CHECK(request_count>=0)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE legacy_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count BIGINT NOT NULL CHECK(request_count>=0)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE model_dispatch_leases (
 id TEXT PRIMARY KEY,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','UNCERTAIN')),
 created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE module_speech_deleted_totals (
 day TEXT PRIMARY KEY,
 stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(stt_seconds>=0),
 tts_chars BIGINT NOT NULL DEFAULT 0 CHECK(tts_chars>=0)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        , _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    exercise_id TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    spec_acknowledged BIGINT NOT NULL DEFAULT 1 CHECK (spec_acknowledged IN (0, 1)),
    language_mode TEXT NOT NULL,
    interaction_mode TEXT NOT NULL,
    active_code_version_id BIGINT NOT NULL DEFAULT 1,
    active_turn_generation BIGINT NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'READY',
    learning_state TEXT NOT NULL DEFAULT 'EXPLAINING',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    deleted_at TEXT
, latest_client_edit_sequence BIGINT NOT NULL DEFAULT 0, voice TEXT, spoken_language TEXT, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_idempotency (
 owner_id TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, key TEXT NOT NULL,
 digest TEXT NOT NULL, status BIGINT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,method,path,key)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count BIGINT NOT NULL CHECK(request_count >= 0)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_speech_deleted_daily (day TEXT PRIMARY KEY, request_count BIGINT NOT NULL, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_workspaces (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, deleted_at TEXT
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE user_goals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  date TEXT NOT NULL,
  target_xp BIGINT NOT NULL DEFAULT 100,
  current_xp BIGINT NOT NULL DEFAULT 0,
  completed BIGINT NOT NULL DEFAULT 0,
  UNIQUE(user_id, date)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE user_profiles (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  avatar_initials TEXT NOT NULL,
  total_xp BIGINT NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE user_streaks (
  user_id TEXT PRIMARY KEY,
  current_streak BIGINT NOT NULL DEFAULT 1,
  max_streak BIGINT NOT NULL DEFAULT 1,
  last_activity_date TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE user_xp_ledger (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  amount BIGINT NOT NULL,
  reason TEXT NOT NULL,
  reference_id TEXT,
  created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE weekly_missions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  target_count BIGINT NOT NULL,
  reward_xp BIGINT NOT NULL DEFAULT 150,
  mission_type TEXT NOT NULL,
  week_key TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE workspace_recovery_attempts (
    id TEXT PRIMARY KEY,
    subject_hash TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE assessment_model_usage (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_type TEXT NOT NULL CHECK(source_type IN ('interview','learning')),
 session_id TEXT NOT NULL, revision BIGINT NOT NULL CHECK(revision>=1),
 request_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL, model TEXT NOT NULL,
 UNIQUE(source_type,session_id,revision)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE case_history (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    spec_version TEXT NOT NULL,
    case_hash TEXT NOT NULL,
    input_args_json TEXT NOT NULL,
    executed BIGINT NOT NULL DEFAULT 0 CHECK (executed IN (0, 1)),
    revealed BIGINT NOT NULL DEFAULT 0 CHECK (revealed IN (0, 1)),
    first_seen_at TEXT NOT NULL, exercise_id TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL DEFAULT 'DIAGNOSTIC', challenge_id TEXT, created_at TEXT NOT NULL DEFAULT '',
    UNIQUE (session_id, spec_version, case_hash)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE challenges (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    code_version_id BIGINT NOT NULL,
    code_hash TEXT NOT NULL,
    turn_generation BIGINT NOT NULL,
    input_args_json TEXT NOT NULL,
    case_hash TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('DIAGNOSTIC', 'TRANSFER')),
    reveal_state TEXT NOT NULL DEFAULT 'HIDDEN' CHECK (reveal_state IN ('HIDDEN', 'REVEALED')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE cleanup_obligations (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    turn_generation BIGINT NOT NULL,
    audio_pending BIGINT NOT NULL DEFAULT 1 CHECK(audio_pending IN (0,1)),
    pending_jobs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE code_versions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    code_version_id BIGINT NOT NULL,
    source_code TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    ast_symbols_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (session_id, code_version_id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE daily_quiz_attempts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  quiz_id TEXT NOT NULL REFERENCES daily_quizzes(id) ON DELETE CASCADE,
  selected_option_index BIGINT NOT NULL,
  is_correct BIGINT NOT NULL,
  xp_awarded BIGINT NOT NULL DEFAULT 0,
  attempted_at TEXT NOT NULL,
  UNIQUE(user_id, quiz_id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE dsa_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL,
 capture_attempt_id BIGINT NOT NULL,
 transcript_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(turn_id,capture_attempt_id,transcript_hash)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE idempotency_records (
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
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE interview_sessions (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 type TEXT NOT NULL CHECK(type IN ('dsa','cs','system_design','codebase_defense')),
 difficulty TEXT NOT NULL CHECK(difficulty IN ('beginner','intermediate','advanced')),
 topics_json TEXT NOT NULL, duration_minutes BIGINT NOT NULL CHECK(duration_minutes BETWEEN 5 AND 60),
 language_mode TEXT NOT NULL, epoch BIGINT NOT NULL CHECK(epoch>=1),
 state TEXT NOT NULL CHECK(state IN ('active','completed')),
 started_at TEXT NOT NULL, deadline_at TEXT NOT NULL, completed_at TEXT,
 completion_reason TEXT, plan_json TEXT NOT NULL,
 CHECK((state='active' AND completed_at IS NULL) OR (state='completed' AND completed_at IS NOT NULL))
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    turn_generation BIGINT NOT NULL,
    code_version_id BIGINT NOT NULL,
    deadline_at TEXT,
    cancelled_at TEXT,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, revision_json TEXT, challenge_id TEXT, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_evidence_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL CHECK(id IN ('first_interview','three_study_days')),
 title TEXT NOT NULL, earned_at TEXT NOT NULL, source_event TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('learning_engine','interview')),
 PRIMARY KEY(workspace_id,id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_external_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source TEXT NOT NULL CHECK(source='interview'), source_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='interview.completed'), created_at TEXT NOT NULL, UNIQUE(source,source_id,kind)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_sessions (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 lesson_id TEXT NOT NULL, catalog_version TEXT NOT NULL, content_hash TEXT NOT NULL,
 lesson_json TEXT NOT NULL, language_mode TEXT NOT NULL,
 epoch BIGINT NOT NULL DEFAULT 1 CHECK(epoch>=1), run BIGINT NOT NULL DEFAULT 1 CHECK(run>=1),
 state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','completed','exhausted')),
 answer_count BIGINT NOT NULL DEFAULT 0 CHECK(answer_count BETWEEN 0 AND 5),
 hint_count BIGINT NOT NULL DEFAULT 0 CHECK(hint_count BETWEEN 0 AND 3),
 coach_messages_json TEXT NOT NULL, feedback_json TEXT, report_json TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(id,workspace_id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE legacy_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 operation TEXT NOT NULL CHECK(operation IN ('claim_extraction','coaching_phrase')),
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE module_speech_usage (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL,
 module TEXT NOT NULL CHECK(module IN ('lesson','interview','redrive')),
 epoch BIGINT NOT NULL CHECK(epoch>=1),
 operation TEXT NOT NULL CHECK(operation IN ('STT','TTS')),
 stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(stt_seconds>=0 AND stt_seconds<=30),
 tts_chars BIGINT NOT NULL DEFAULT 0 CHECK(tts_chars>=0),
 request_count BIGINT NOT NULL CHECK(request_count>=1),
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_snapshots (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL, source_locator TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_hash TEXT,
 total_files BIGINT NOT NULL DEFAULT 0, files_indexed BIGINT NOT NULL DEFAULT 0,
 coverage_json TEXT NOT NULL DEFAULT '{}', failure_code TEXT
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence_no BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, sequence_no)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_sessions (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id), token_hash TEXT NOT NULL,
 mode TEXT NOT NULL, posture TEXT NOT NULL, scenario_id TEXT NOT NULL, scenario_version TEXT NOT NULL,
 repo_snapshot_id TEXT, epoch BIGINT NOT NULL DEFAULT 1, diagram_revision BIGINT NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, expires_at TEXT NOT NULL, deleted_at TEXT,
 deadline_at TEXT, paused_at TEXT, remaining_seconds BIGINT, scenario_hash TEXT NOT NULL DEFAULT '', scenario_json TEXT NOT NULL DEFAULT '{}', constraint_index BIGINT NOT NULL DEFAULT 0, hint_level BIGINT NOT NULL DEFAULT 0, cleaned_at TEXT
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE traces (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 code_version_id BIGINT NOT NULL, turn_generation BIGINT NOT NULL,
 case_hash TEXT NOT NULL, status TEXT NOT NULL, total_observed BIGINT NOT NULL,
 trace_truncated BIGINT NOT NULL, termination_reason TEXT NOT NULL,
 runtime_version TEXT NOT NULL, steps_json TEXT NOT NULL, observation_json TEXT,
 created_at TEXT NOT NULL
, revision_json TEXT, challenge_id TEXT, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_generation BIGINT NOT NULL,
    code_version_id BIGINT NOT NULL,
    challenge_id TEXT,
    transport_mode TEXT NOT NULL,
    language_mode TEXT NOT NULL,
    raw_transcript TEXT,
    normalized_transcript TEXT,
    claim_json TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, confirmed_at TEXT, latest_capture_attempt_id BIGINT NOT NULL DEFAULT 0, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE usage_ledger (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    operation_type TEXT NOT NULL,
    stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    tts_chars BIGINT NOT NULL DEFAULT 0,
    request_count BIGINT NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, entry_id TEXT, reservation_id TEXT NOT NULL DEFAULT '', turn_generation BIGINT NOT NULL DEFAULT 0, cache_hit BIGINT NOT NULL DEFAULT 0, uncertain BIGINT NOT NULL DEFAULT 0, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE usage_reservations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    operation_type TEXT NOT NULL,
    stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    tts_chars BIGINT NOT NULL DEFAULT 0,
    request_count BIGINT NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, reservation_id TEXT, turn_generation BIGINT NOT NULL DEFAULT 0, reserved_stt_sec DOUBLE PRECISION NOT NULL DEFAULT 0.0, reserved_tts_chars BIGINT NOT NULL DEFAULT 0, uncertain BIGINT NOT NULL DEFAULT 0, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE user_achievements (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  achievement_slug TEXT NOT NULL REFERENCES achievements(slug) ON DELETE CASCADE,
  unlocked_at TEXT NOT NULL,
  UNIQUE(user_id, achievement_slug)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE user_mission_progress (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  mission_id TEXT NOT NULL REFERENCES weekly_missions(id) ON DELETE CASCADE,
  current_count BIGINT NOT NULL DEFAULT 0,
  completed BIGINT NOT NULL DEFAULT 0,
  completed_at TEXT,
  UNIQUE(user_id, mission_id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE workspace_dsa_sessions (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE workspace_recovery (
    workspace_id TEXT PRIMARY KEY REFERENCES studio_workspaces(id) ON DELETE CASCADE,
    credential_hash TEXT NOT NULL UNIQUE,
    generation BIGINT NOT NULL DEFAULT 1,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    code_version_id BIGINT NOT NULL,
    code_hash TEXT NOT NULL,
    turn_generation BIGINT NOT NULL,
    verification_status TEXT NOT NULL,
    prediction_status TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE capture_attempts (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    attempt_number BIGINT NOT NULL,
    raw_transcript TEXT,
    normalized_transcript TEXT,
    provider_confidence DOUBLE PRECISION,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (turn_id, attempt_number)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_learning_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
    repo_snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
    repo_url TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    commit_sha TEXT,
    title TEXT NOT NULL,
    current_topic TEXT NOT NULL DEFAULT 'overview',
    knowledge_level TEXT NOT NULL DEFAULT 'undetermined',
    learning_progress_json TEXT NOT NULL DEFAULT '{}',
    pending_question TEXT,
    state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE dsa_conversation_replies (
 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
 capture_attempt_id BIGINT NOT NULL,
 transcript_hash TEXT NOT NULL,
 learner_transcript TEXT NOT NULL,
 text TEXT NOT NULL,
 source_mode TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(turn_id,capture_attempt_id,transcript_hash)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE evidence_artifacts (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
 code_version_id BIGINT NOT NULL, turn_generation BIGINT NOT NULL,
 case_hash TEXT NOT NULL, confirmed_prediction BIGINT, prediction_status TEXT NOT NULL,
 verification_status TEXT NOT NULL, minimization_status TEXT NOT NULL,
 trace_id TEXT, artifact_json TEXT NOT NULL, created_at TEXT NOT NULL
, confirmed_prediction_json TEXT CHECK (confirmed_prediction_json IS NULL OR viva_json_valid(confirmed_prediction_json)), _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE interview_events (
 session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL, event_type TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE interview_questions (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL, epoch BIGINT NOT NULL,
 question_json TEXT NOT NULL, asked_at TEXT NOT NULL,
 UNIQUE(session_id,sequence), UNIQUE(session_id,epoch), UNIQUE(session_id,id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE interview_reports (
 session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
 report_json TEXT NOT NULL, created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_answers (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 run BIGINT NOT NULL CHECK(run>=1), epoch BIGINT NOT NULL CHECK(epoch>=1),
 question_id TEXT NOT NULL, answer TEXT NOT NULL CHECK(length(answer) BETWEEN 1 AND 2000),
 correct BIGINT NOT NULL CHECK(correct IN (0,1)), evaluation_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,workspace_id) REFERENCES learning_sessions(id,workspace_id) ON DELETE CASCADE,
 UNIQUE(session_id,epoch)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_decisions (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, rationale TEXT NOT NULL,
 learner_alternative TEXT, created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_defense_sessions (
 id TEXT PRIMARY KEY, studio_session_id TEXT NOT NULL UNIQUE REFERENCES studio_sessions(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 phase TEXT NOT NULL, created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_evidence_cards (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, origin TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_files (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 path TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, language TEXT NOT NULL,
 parse_status TEXT NOT NULL, imports_json TEXT NOT NULL, calls_json TEXT NOT NULL,
 symbols_json TEXT NOT NULL, rank DOUBLE PRECISION NOT NULL DEFAULT 0, UNIQUE(snapshot_id,path)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_learning_plans (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 snapshot_hash TEXT NOT NULL,
 steps_json TEXT NOT NULL,
 cursor BIGINT NOT NULL DEFAULT 0 CHECK(cursor >= 0),
 epoch BIGINT NOT NULL DEFAULT 1 CHECK(epoch >= 1),
 revisit_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(workspace_id,snapshot_id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_diagrams (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, revision BIGINT NOT NULL,
 parent_revision BIGINT, graph_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,revision)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_events (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, sequence BIGINT NOT NULL,
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch BIGINT NOT NULL,
 idempotency_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(session_id,idempotency_key)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_proposals (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 base_revision BIGINT NOT NULL, graph_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_review_cards (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 prompt TEXT NOT NULL, evidence_json TEXT NOT NULL, fsrs_json TEXT NOT NULL, due_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_speech_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id), epoch BIGINT NOT NULL,
 operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0, tts_chars BIGINT NOT NULL DEFAULT 0,
 request_count BIGINT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(session_id,operation,idempotency_key)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE studio_turns (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch BIGINT NOT NULL, diagram_revision BIGINT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
 created_at TEXT NOT NULL
, transcript_revision BIGINT NOT NULL DEFAULT 1 CHECK(transcript_revision >= 1), superseded_by TEXT REFERENCES studio_turns(id) ON DELETE SET NULL, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE coaching_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
    hint_level BIGINT NOT NULL CHECK (hint_level IN (1, 2, 3)),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
, source_mode TEXT NOT NULL DEFAULT 'DETERMINISTIC', display_text TEXT NOT NULL DEFAULT '', speakable_text TEXT NOT NULL DEFAULT '', _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_learning_audio (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES codebase_learning_sessions(id) ON DELETE CASCADE,
    wav BYTEA NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE codebase_learning_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES codebase_learning_sessions(id) ON DELETE CASCADE,
    sequence BIGINT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    audio_path TEXT,
    citations_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, sequence)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE interview_answers (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 question_id TEXT NOT NULL UNIQUE, epoch BIGINT NOT NULL, answer TEXT NOT NULL,
 code TEXT, created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,question_id) REFERENCES interview_questions(session_id,id),
 UNIQUE(session_id,epoch)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL, run BIGINT NOT NULL CHECK(run>=1),
 kind TEXT NOT NULL CHECK(kind IN ('session.started','session.restarted','answer.evaluated','hint.requested','lesson.completed')),
 source TEXT NOT NULL CHECK(source='learning_engine'), answer_id TEXT REFERENCES learning_answers(id) ON DELETE CASCADE,
 study_seconds BIGINT NOT NULL DEFAULT 0 CHECK(study_seconds BETWEEN 0 AND 300), created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,workspace_id) REFERENCES learning_sessions(id,workspace_id) ON DELETE CASCADE
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_explanation_reviews (
 answer_id TEXT PRIMARY KEY REFERENCES learning_answers(id) ON DELETE CASCADE,
 explanation TEXT NOT NULL CHECK(length(explanation) BETWEEN 1 AND 12000),
 review_json TEXT NOT NULL CHECK(viva_json_valid(review_json))
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE "legacy_traces" (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    trace_json TEXT NOT NULL,
    truncated BIGINT NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    total_observed BIGINT NOT NULL,
    created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_chunks (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES repo_files(id) ON DELETE CASCADE, path TEXT NOT NULL,
 symbol TEXT NOT NULL, start_line BIGINT NOT NULL, end_line BIGINT NOT NULL,
 chunk_hash TEXT NOT NULL, text TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_defense_answers (
 id TEXT PRIMARY KEY, defense_id TEXT NOT NULL REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL, phase TEXT NOT NULL, answer TEXT NOT NULL, citations_json TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(defense_id,sequence)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_idempotency (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 operation TEXT NOT NULL, key TEXT NOT NULL, input_hash TEXT NOT NULL,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 studio_session_id TEXT REFERENCES studio_sessions(id) ON DELETE CASCADE,
 defense_id TEXT REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 evidence_card_id TEXT REFERENCES repo_evidence_cards(id) ON DELETE CASCADE,
 decision_id TEXT REFERENCES repo_decisions(id) ON DELETE CASCADE,
 response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,operation,key)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_learning_attempts (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL CHECK(sequence >= 1),
 step_id TEXT NOT NULL,
 answer TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE interview_semantic_reviews (
 answer_id TEXT PRIMARY KEY REFERENCES interview_answers(id) ON DELETE CASCADE,
 review_json TEXT NOT NULL CHECK(viva_json_valid(review_json))
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE learning_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL, title TEXT NOT NULL, earned_at TEXT NOT NULL,
 source_event TEXT NOT NULL REFERENCES learning_events(id) ON DELETE CASCADE,
 PRIMARY KEY(workspace_id,id)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_defense_answer_evidence (
 answer_id TEXT PRIMARY KEY REFERENCES repo_defense_answers(id) ON DELETE CASCADE,
 evidence_links_json TEXT NOT NULL DEFAULT '[]',
 changed_requirement TEXT, learner_alternative TEXT,
 unknowns_json TEXT NOT NULL DEFAULT '[]'
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_learning_evidence_events (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES repo_learning_attempts(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL,
 evidence_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE speech_jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    coaching_message_id TEXT REFERENCES coaching_messages(id) ON DELETE CASCADE,
    playback_id TEXT NOT NULL UNIQUE,
    turn_id TEXT,
    code_version_id BIGINT NOT NULL,
    turn_generation BIGINT NOT NULL,
    normalized_text_hash TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('LIVE', 'CACHED', 'DEMO')),
    status TEXT NOT NULL,
    audio_path TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
, _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY);

CREATE TABLE repo_chunks_fts (
 chunk_id TEXT PRIMARY KEY REFERENCES repo_chunks(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 text TEXT NOT NULL,
 search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple',text)) STORED,
 _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX repo_chunks_fts_search ON repo_chunks_fts USING GIN(search_vector);

CREATE UNIQUE INDEX codebase_one_active_request ON codebase_provider_requests(session_id) WHERE status='ACTIVE';

CREATE INDEX dsa_model_usage_session ON dsa_model_usage(session_id,created_at);

CREATE INDEX idx_admission_counters_expiry ON admission_counters (window_start);

CREATE INDEX idx_artifacts_session_created ON artifacts (session_id, created_at);

CREATE INDEX idx_capture_attempts_session_created ON capture_attempts (session_id, created_at);

CREATE INDEX idx_capture_attempts_status_created ON capture_attempts (status, created_at);

CREATE INDEX idx_case_history_session_seen ON case_history (session_id, first_seen_at);

CREATE INDEX idx_challenges_expires_at ON challenges (expires_at);

CREATE INDEX idx_challenges_session_created ON challenges (session_id, created_at);

CREATE INDEX idx_cleanup_obligations_updated ON cleanup_obligations(updated_at);

CREATE INDEX idx_clm_session_sequence ON codebase_learning_messages(session_id, sequence);

CREATE INDEX idx_cls_snapshot ON codebase_learning_sessions(repo_snapshot_id);

CREATE INDEX idx_cls_workspace_updated ON codebase_learning_sessions(workspace_id, updated_at DESC);

CREATE INDEX idx_coaching_messages_session_created ON coaching_messages (session_id, created_at);

CREATE INDEX idx_code_versions_session_created ON code_versions (session_id, created_at);

CREATE INDEX idx_codebase_audio_expiry ON codebase_learning_audio(expires_at);

CREATE INDEX idx_codebase_audio_session ON codebase_learning_audio(session_id);

CREATE INDEX idx_daily_quiz_attempts_user ON daily_quiz_attempts(user_id);

CREATE INDEX idx_daily_quizzes_date ON daily_quizzes(date);

CREATE INDEX idx_evidence_session ON evidence_artifacts(session_id,created_at);

CREATE INDEX idx_idempotency_expires_at ON idempotency_records (expires_at);

CREATE INDEX idx_idempotency_session_created ON idempotency_records (session_id, created_at);

CREATE INDEX idx_idempotency_status_created ON idempotency_records (status, created_at);

CREATE INDEX idx_jobs_session_active ON jobs(session_id,status);

CREATE INDEX idx_jobs_session_created ON jobs (session_id, created_at);

CREATE INDEX idx_jobs_status_created ON jobs (status, created_at);

CREATE INDEX idx_repo_idempotency_defense ON repo_idempotency(defense_id);

CREATE INDEX idx_repo_idempotency_snapshot ON repo_idempotency(snapshot_id);

CREATE INDEX idx_repo_learning_attempts_rate ON repo_learning_attempts(created_at,plan_id);

CREATE INDEX idx_repo_snapshots_workspace ON repo_snapshots(workspace_id,id);

CREATE INDEX idx_session_events_session_created ON session_events (session_id, created_at);

CREATE INDEX idx_sessions_created_at ON sessions (created_at);

CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);

CREATE INDEX idx_speech_jobs_expires_at ON speech_jobs (expires_at);

CREATE INDEX idx_speech_jobs_session_created ON speech_jobs (session_id, created_at);

CREATE INDEX idx_speech_jobs_status_created ON speech_jobs (status, created_at);

CREATE INDEX idx_trace_session_v2 ON traces(session_id,created_at);

CREATE INDEX idx_traces_session_created ON "legacy_traces" (session_id, created_at);

CREATE INDEX idx_turns_session_created ON turns (session_id, created_at);

CREATE INDEX idx_turns_status_created ON turns (state, created_at);

CREATE INDEX idx_usage_ledger_session_created ON usage_ledger (session_id, created_at);

CREATE INDEX idx_usage_ledger_status_created ON usage_ledger (status, created_at);

CREATE INDEX idx_usage_reservations_session_created ON usage_reservations (session_id, created_at);

CREATE INDEX idx_usage_reservations_status_created ON usage_reservations (status, created_at);

CREATE INDEX idx_user_xp_ledger_user ON user_xp_ledger(user_id);

CREATE INDEX interview_deadline ON interview_sessions(state,deadline_at);

CREATE UNIQUE INDEX interview_single_completion ON interview_events(session_id)
 WHERE event_type='interview.completed';

CREATE INDEX interview_workspace ON interview_sessions(workspace_id,started_at);

CREATE UNIQUE INDEX learning_answer_event ON learning_events(answer_id,kind) WHERE answer_id IS NOT NULL;

CREATE INDEX learning_answer_session ON learning_answers(session_id,run);

CREATE INDEX learning_event_workspace ON learning_events(workspace_id,created_at);

CREATE INDEX learning_external_workspace ON learning_external_events(workspace_id,created_at);

CREATE UNIQUE INDEX learning_run_completion ON learning_events(session_id,run) WHERE kind='lesson.completed';

CREATE INDEX learning_session_workspace ON learning_sessions(workspace_id,state,updated_at);

CREATE INDEX legacy_model_usage_session ON legacy_model_usage(session_id,created_at);

CREATE INDEX module_speech_daily ON module_speech_usage(created_at,status);

CREATE INDEX module_speech_source ON module_speech_usage(workspace_id,module,source_id,status);

CREATE INDEX recovery_attempt_time ON workspace_recovery_attempts(created_at);

CREATE INDEX studio_model_daily ON studio_model_usage(created_at,status);

CREATE INDEX studio_review_due ON studio_review_cards(workspace_id,due_at);

CREATE INDEX studio_session_workspace ON studio_sessions(workspace_id);

CREATE INDEX studio_speech_usage_daily ON studio_speech_usage(created_at,status);

CREATE INDEX studio_turns_current ON studio_turns(session_id,superseded_by,created_at);

CREATE INDEX workspace_dsa_owner ON workspace_dsa_sessions(workspace_id);

CREATE FUNCTION trigger_assessment_model_deleted_accounting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
INSERT INTO assessment_model_deleted_daily(day,request_count) VALUES(viva_date(OLD.created_at),1)
 ON CONFLICT(day) DO UPDATE SET request_count=assessment_model_deleted_daily.request_count+1;
RETURN OLD;
END $$;
CREATE TRIGGER assessment_model_deleted_accounting BEFORE DELETE ON assessment_model_usage
 FOR EACH ROW EXECUTE FUNCTION trigger_assessment_model_deleted_accounting();

CREATE FUNCTION trigger_dsa_session_model_accounting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
INSERT INTO dsa_model_deleted_daily(day,request_count)
 SELECT viva_date(created_at),count(*) FROM dsa_model_usage
 WHERE session_id=OLD.id AND status IN ('RESERVED','COMMITTED','UNCERTAIN')
 GROUP BY viva_date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=dsa_model_deleted_daily.request_count+excluded.request_count;
RETURN OLD;
END $$;
CREATE TRIGGER dsa_session_model_accounting BEFORE DELETE ON sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_dsa_session_model_accounting();

CREATE FUNCTION trigger_dsa_session_soft_delete_accounting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
INSERT INTO dsa_model_deleted_daily(day,request_count)
 SELECT viva_date(created_at),count(*) FROM dsa_model_usage
 WHERE session_id=NEW.id AND status IN ('RESERVED','COMMITTED','UNCERTAIN')
 GROUP BY viva_date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=dsa_model_deleted_daily.request_count+excluded.request_count;
 DELETE FROM dsa_conversation_replies WHERE session_id=NEW.id;
 DELETE FROM dsa_model_usage WHERE session_id=NEW.id;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER dsa_session_soft_delete_accounting AFTER UPDATE OF deleted_at ON sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_dsa_session_soft_delete_accounting();

CREATE FUNCTION trigger_interview_report_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Interview reports are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER interview_report_immutable BEFORE UPDATE ON interview_reports
 FOR EACH ROW EXECUTE FUNCTION trigger_interview_report_immutable();

CREATE FUNCTION trigger_interview_semantic_review_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Interview semantic reviews are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER interview_semantic_review_immutable BEFORE UPDATE ON interview_semantic_reviews
 FOR EACH ROW EXECUTE FUNCTION trigger_interview_semantic_review_immutable();

CREATE FUNCTION trigger_interview_workspace_soft_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.deleted_at IS NOT NULL THEN
DELETE FROM interview_sessions WHERE workspace_id=NEW.id;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER interview_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces
 FOR EACH ROW EXECUTE FUNCTION trigger_interview_workspace_soft_delete();

CREATE FUNCTION trigger_learning_achievement_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NOT EXISTS (
  SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
  AND e.kind='lesson.completed' AND e.source='learning_engine'
 ) THEN RAISE EXCEPTION 'Achievement requires verified completion event'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER learning_achievement_evidence BEFORE INSERT ON learning_achievements
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_achievement_evidence();

CREATE FUNCTION trigger_learning_achievement_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Learning achievements are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER learning_achievement_immutable BEFORE UPDATE ON learning_achievements
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_achievement_immutable();

CREATE FUNCTION trigger_learning_action_badge_cascade() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
DELETE FROM learning_evidence_achievements WHERE source='learning_engine' AND source_event=OLD.id;
RETURN OLD;
END $$;
CREATE TRIGGER learning_action_badge_cascade AFTER DELETE ON learning_events
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_action_badge_cascade();

CREATE FUNCTION trigger_learning_answer_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Learning answers are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER learning_answer_immutable BEFORE UPDATE ON learning_answers
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_answer_immutable();

CREATE FUNCTION trigger_learning_completion_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.kind IN ('lesson.completed','answer.evaluated') THEN
IF NOT EXISTS (
  SELECT 1 FROM learning_answers a WHERE a.id=NEW.answer_id AND a.session_id=NEW.session_id
  AND a.workspace_id=NEW.workspace_id AND a.run=NEW.run AND (NEW.kind='answer.evaluated' OR a.correct=1)
 ) THEN RAISE EXCEPTION 'Learning event requires evaluated owned answer evidence'; END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER learning_completion_evidence BEFORE INSERT ON learning_events
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_completion_evidence();

CREATE FUNCTION trigger_learning_completion_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.state='completed' THEN
IF NOT EXISTS (
  SELECT 1 FROM learning_answers a WHERE a.session_id=NEW.id AND a.workspace_id=NEW.workspace_id
  AND a.run=NEW.run AND a.correct=1
 ) THEN RAISE EXCEPTION 'Learning completion requires correct answer'; END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER learning_completion_state BEFORE UPDATE OF state ON learning_sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_completion_state();

CREATE FUNCTION trigger_learning_event_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Learning events are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER learning_event_immutable BEFORE UPDATE ON learning_events
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_event_immutable();

CREATE FUNCTION trigger_learning_evidence_achievement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NOT (
  (NEW.id='first_interview' AND NEW.source='interview' AND EXISTS (
   SELECT 1 FROM learning_external_events e WHERE e.id=NEW.source_event
   AND e.workspace_id=NEW.workspace_id AND e.source='interview' AND e.kind='interview.completed'
  )) OR
  (NEW.id='three_study_days' AND NEW.source='learning_engine' AND EXISTS (
   SELECT 1 FROM learning_events e WHERE e.id=NEW.source_event AND e.workspace_id=NEW.workspace_id
   AND e.kind IN ('answer.evaluated','hint.requested') AND viva_date(e.created_at)=viva_date(NEW.earned_at)
  ) AND (
   SELECT count(DISTINCT viva_date(e.created_at)) FROM learning_events e
   WHERE e.workspace_id=NEW.workspace_id AND e.kind IN ('answer.evaluated','hint.requested')
   AND viva_date(e.created_at) BETWEEN viva_date(NEW.earned_at,'-2 days') AND viva_date(NEW.earned_at)
  )=3)
 ) THEN RAISE EXCEPTION 'Achievement requires verified owned evidence and threshold'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER learning_evidence_achievement_guard BEFORE INSERT ON learning_evidence_achievements
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_evidence_achievement_guard();

CREATE FUNCTION trigger_learning_evidence_achievement_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Learning evidence achievements are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER learning_evidence_achievement_immutable BEFORE UPDATE ON learning_evidence_achievements
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_evidence_achievement_immutable();

CREATE FUNCTION trigger_learning_explanation_review_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Learning explanation reviews are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER learning_explanation_review_immutable BEFORE UPDATE ON learning_explanation_reviews
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_explanation_review_immutable();

CREATE FUNCTION trigger_learning_external_badge_cascade() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
DELETE FROM learning_evidence_achievements WHERE source='interview' AND source_event=OLD.id;
RETURN OLD;
END $$;
CREATE TRIGGER learning_external_badge_cascade AFTER DELETE ON learning_external_events
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_external_badge_cascade();

CREATE FUNCTION trigger_learning_external_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'Learning external events are immutable';
RETURN NEW;
END $$;
CREATE TRIGGER learning_external_immutable BEFORE UPDATE ON learning_external_events
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_external_immutable();

CREATE FUNCTION trigger_learning_interview_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
DELETE FROM learning_external_events WHERE source='interview' AND source_id=OLD.id;
RETURN OLD;
END $$;
CREATE TRIGGER learning_interview_delete AFTER DELETE ON interview_sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_interview_delete();

CREATE FUNCTION trigger_learning_interview_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NOT EXISTS (
  SELECT 1 FROM interview_sessions s JOIN interview_reports r ON r.session_id=s.id
  JOIN interview_events e ON e.session_id=s.id AND e.event_type='interview.completed'
  WHERE s.id=NEW.source_id AND s.workspace_id=NEW.workspace_id AND s.state='completed'
  AND s.completed_at IS NOT NULL
 ) THEN RAISE EXCEPTION 'Interview completion requires durable owned report and outbox'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER learning_interview_evidence BEFORE INSERT ON learning_external_events
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_interview_evidence();

CREATE FUNCTION trigger_learning_workspace_soft_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.deleted_at IS NOT NULL THEN
DELETE FROM learning_sessions WHERE workspace_id=NEW.id;
 DELETE FROM learning_external_events WHERE workspace_id=NEW.id;
 DELETE FROM learning_evidence_achievements WHERE workspace_id=NEW.id;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER learning_workspace_soft_delete AFTER UPDATE OF deleted_at ON studio_workspaces
 FOR EACH ROW EXECUTE FUNCTION trigger_learning_workspace_soft_delete();

CREATE FUNCTION trigger_legacy_session_model_accounting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
INSERT INTO legacy_model_deleted_daily(day,request_count)
 SELECT viva_date(created_at),count(*) FROM legacy_model_usage
 WHERE session_id=OLD.id GROUP BY viva_date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=legacy_model_deleted_daily.request_count+excluded.request_count;
RETURN OLD;
END $$;
CREATE TRIGGER legacy_session_model_accounting BEFORE DELETE ON sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_legacy_session_model_accounting();

CREATE FUNCTION trigger_legacy_session_soft_delete_accounting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
INSERT INTO legacy_model_deleted_daily(day,request_count)
 SELECT viva_date(created_at),count(*) FROM legacy_model_usage
 WHERE session_id=NEW.id GROUP BY viva_date(created_at)
 ON CONFLICT(day) DO UPDATE SET request_count=legacy_model_deleted_daily.request_count+excluded.request_count;
 DELETE FROM legacy_model_usage WHERE session_id=NEW.id;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER legacy_session_soft_delete_accounting AFTER UPDATE OF deleted_at ON sessions
 FOR EACH ROW EXECUTE FUNCTION trigger_legacy_session_soft_delete_accounting();

CREATE FUNCTION trigger_module_speech_delete_accounting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN') THEN
INSERT INTO studio_speech_deleted_daily(day,request_count)
 VALUES(viva_date(OLD.created_at),OLD.request_count)
 ON CONFLICT(day) DO UPDATE SET request_count=studio_speech_deleted_daily.request_count+excluded.request_count;
END IF;
RETURN OLD;
END $$;
CREATE TRIGGER module_speech_delete_accounting AFTER DELETE ON module_speech_usage
 FOR EACH ROW EXECUTE FUNCTION trigger_module_speech_delete_accounting();

CREATE FUNCTION trigger_module_speech_delete_audio_budget() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN') THEN
INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 VALUES(viva_date(OLD.created_at),OLD.stt_seconds,OLD.tts_chars)
 ON CONFLICT(day) DO UPDATE SET
 stt_seconds=module_speech_deleted_totals.stt_seconds+excluded.stt_seconds,
 tts_chars=module_speech_deleted_totals.tts_chars+excluded.tts_chars;
END IF;
RETURN OLD;
END $$;
CREATE TRIGGER module_speech_delete_audio_budget AFTER DELETE ON module_speech_usage
 FOR EACH ROW EXECUTE FUNCTION trigger_module_speech_delete_audio_budget();

CREATE FUNCTION trigger_module_speech_soft_delete_privacy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.deleted_at IS NOT NULL THEN
DELETE FROM module_speech_usage WHERE workspace_id=NEW.id;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER module_speech_soft_delete_privacy AFTER UPDATE OF deleted_at ON studio_workspaces
 FOR EACH ROW EXECUTE FUNCTION trigger_module_speech_soft_delete_privacy();

CREATE FUNCTION trigger_recovery_workspace_deleted() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.deleted_at IS NOT NULL THEN
DELETE FROM workspace_recovery WHERE workspace_id=NEW.id;
    DELETE FROM workspace_recovery_attempts WHERE workspace_id=NEW.id;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER recovery_workspace_deleted AFTER UPDATE OF deleted_at ON studio_workspaces
 FOR EACH ROW EXECUTE FUNCTION trigger_recovery_workspace_deleted();

CREATE FUNCTION trigger_repo_chunks_delete_fts() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
DELETE FROM repo_chunks_fts WHERE chunk_id=old.id;
RETURN OLD;
END $$;
CREATE TRIGGER repo_chunks_delete_fts AFTER DELETE ON repo_chunks
 FOR EACH ROW EXECUTE FUNCTION trigger_repo_chunks_delete_fts();

CREATE FUNCTION trigger_repo_snapshot_delete_authored_prompt_events() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
DELETE FROM studio_events
 WHERE event_type='coach.action' AND viva_json_valid(payload_json)
 AND viva_json_extract(payload_json,'$.source')='authored_repo_defense'
 AND viva_json_extract(payload_json,'$.snapshot_id')=old.id;
RETURN OLD;
END $$;
CREATE TRIGGER repo_snapshot_delete_authored_prompt_events BEFORE DELETE ON repo_snapshots
 FOR EACH ROW EXECUTE FUNCTION trigger_repo_snapshot_delete_authored_prompt_events();

CREATE FUNCTION trigger_studio_speech_delete_audio_budget() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF OLD.status IN ('RESERVED','COMMITTED','UNCERTAIN') THEN
INSERT INTO module_speech_deleted_totals(day,stt_seconds,tts_chars)
 VALUES(viva_date(OLD.created_at),OLD.stt_seconds,OLD.tts_chars)
 ON CONFLICT(day) DO UPDATE SET
 stt_seconds=module_speech_deleted_totals.stt_seconds+excluded.stt_seconds,
 tts_chars=module_speech_deleted_totals.tts_chars+excluded.tts_chars;
END IF;
RETURN OLD;
END $$;
CREATE TRIGGER studio_speech_delete_audio_budget AFTER DELETE ON studio_speech_usage
 FOR EACH ROW EXECUTE FUNCTION trigger_studio_speech_delete_audio_budget();
