-- Text JSON and UTC date semantics retained for the application contract.
CREATE FUNCTION viva_json_valid(input TEXT) RETURNS BOOLEAN LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN PERFORM input::jsonb; RETURN input IS NOT NULL;
EXCEPTION WHEN invalid_text_representation THEN RETURN FALSE; END $fn$;
CREATE FUNCTION viva_json_extract(input TEXT, path TEXT) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE result jsonb;
BEGIN
 IF path !~ '^\$\.[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$' THEN
  RAISE EXCEPTION 'Unsupported JSON path' USING ERRCODE='22023';
 END IF;
 result := input::jsonb #> string_to_array(substr(path,3),'.');
 IF result IS NULL OR result = 'null'::jsonb THEN RETURN NULL; END IF;
 IF result = 'true'::jsonb THEN RETURN '1'; END IF;
 IF result = 'false'::jsonb THEN RETURN '0'; END IF;
 RETURN result #>> '{}';
END $fn$;
CREATE FUNCTION viva_json_each(input TEXT) RETURNS TABLE(key TEXT,value TEXT)
LANGUAGE sql IMMUTABLE AS $fn$
 SELECT (ordinality-1)::text, element::text FROM jsonb_array_elements(input::jsonb) WITH ORDINALITY AS e(element,ordinality)
$fn$;
CREATE FUNCTION viva_json_number(input TEXT, path TEXT) RETURNS NUMERIC
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE result jsonb;
BEGIN
 IF path !~ '^\$\.[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$' THEN
  RAISE EXCEPTION 'Unsupported JSON path' USING ERRCODE='22023';
 END IF;
 result := input::jsonb #> string_to_array(substr(path,3),'.');
 IF result='true'::jsonb THEN RETURN 1; END IF;
 IF result='false'::jsonb THEN RETURN 0; END IF;
 IF jsonb_typeof(result)='number' THEN RETURN (result #>> '{}')::numeric; END IF;
 RETURN NULL;
END $fn$;
CREATE FUNCTION viva_date(input TEXT, modifier TEXT DEFAULT NULL) RETURNS TEXT
LANGUAGE plpgsql STABLE AS $fn$
DECLARE instant TIMESTAMPTZ;
BEGIN
 IF input IS NULL THEN RETURN NULL; END IF;
 IF input='now' THEN instant:=CURRENT_TIMESTAMP;
 ELSIF input ~ '^\d{4}-\d{2}-\d{2}([T ][0-9:.]+([Zz]|[+-][0-9:]+)?)?$' THEN instant:=input::timestamptz;
 ELSE RETURN NULL; END IF;
 IF modifier IS NOT NULL THEN
  IF modifier !~ '^[+-]?\d+ days?$' THEN RETURN NULL; END IF;
  instant := instant + modifier::interval;
 END IF;
 RETURN to_char(instant AT TIME ZONE 'UTC','YYYY-MM-DD');
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN NULL;
END $fn$;
CREATE FUNCTION viva_datetime(input TEXT, modifier TEXT DEFAULT NULL) RETURNS TEXT
LANGUAGE plpgsql STABLE AS $fn$
DECLARE instant TIMESTAMPTZ;
BEGIN
 IF input IS NULL THEN RETURN NULL; END IF;
 IF input='now' THEN instant:=CURRENT_TIMESTAMP;
 ELSIF input ~ '^\d{4}-\d{2}-\d{2}([T ][0-9:.]+([Zz]|[+-][0-9:]+)?)?$' THEN instant:=input::timestamptz;
 ELSE RETURN NULL; END IF;
 IF modifier IS NOT NULL THEN
  IF modifier !~ '^[+-]?\d+ (minutes?|seconds?|days?)$' THEN RETURN NULL; END IF;
  instant := instant + modifier::interval;
 END IF;
 RETURN to_char(instant AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS');
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN NULL;
END $fn$;


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
, latest_client_edit_sequence BIGINT NOT NULL DEFAULT 0, voice TEXT, spoken_language TEXT);

CREATE TABLE code_versions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    code_version_id BIGINT NOT NULL,
    source_code TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    ast_symbols_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (session_id, code_version_id)
);

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
, confirmed_at TEXT, latest_capture_attempt_id BIGINT NOT NULL DEFAULT 0);

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
);

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
);

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
);

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
, revision_json TEXT, challenge_id TEXT);

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
);

CREATE TABLE "legacy_traces" (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    trace_json TEXT NOT NULL,
    truncated BIGINT NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    total_observed BIGINT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE coaching_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
    hint_level BIGINT NOT NULL CHECK (hint_level IN (1, 2, 3)),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
, source_mode TEXT NOT NULL DEFAULT 'DETERMINISTIC', display_text TEXT NOT NULL DEFAULT '', speakable_text TEXT NOT NULL DEFAULT '');

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
);

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
);

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
);

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
);

CREATE TABLE session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence_no BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, sequence_no)
);

CREATE TABLE evidence_artifacts (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 challenge_id TEXT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
 code_version_id BIGINT NOT NULL, turn_generation BIGINT NOT NULL,
 case_hash TEXT NOT NULL, confirmed_prediction BIGINT, prediction_status TEXT NOT NULL,
 verification_status TEXT NOT NULL, minimization_status TEXT NOT NULL,
 trace_id TEXT, artifact_json TEXT NOT NULL, created_at TEXT NOT NULL
, confirmed_prediction_json TEXT CHECK (confirmed_prediction_json IS NULL OR viva_json_valid(confirmed_prediction_json)));

CREATE TABLE traces (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
 code_version_id BIGINT NOT NULL, turn_generation BIGINT NOT NULL,
 case_hash TEXT NOT NULL, status TEXT NOT NULL, total_observed BIGINT NOT NULL,
 trace_truncated BIGINT NOT NULL, termination_reason TEXT NOT NULL,
 runtime_version TEXT NOT NULL, steps_json TEXT NOT NULL, observation_json TEXT,
 created_at TEXT NOT NULL
, revision_json TEXT, challenge_id TEXT);

CREATE TABLE admission_counters (
    bucket TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    request_count BIGINT NOT NULL CHECK (request_count >= 0),
    PRIMARY KEY (bucket, subject_hash, window_start)
);

CREATE TABLE cleanup_obligations (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    turn_generation BIGINT NOT NULL,
    audio_pending BIGINT NOT NULL DEFAULT 1 CHECK(audio_pending IN (0,1)),
    pending_jobs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE studio_workspaces (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, deleted_at TEXT
);

CREATE TABLE studio_sessions (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id), token_hash TEXT NOT NULL,
 mode TEXT NOT NULL, posture TEXT NOT NULL, scenario_id TEXT NOT NULL, scenario_version TEXT NOT NULL,
 repo_snapshot_id TEXT, epoch BIGINT NOT NULL DEFAULT 1, diagram_revision BIGINT NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, expires_at TEXT NOT NULL, deleted_at TEXT,
 deadline_at TEXT, paused_at TEXT, remaining_seconds BIGINT, scenario_hash TEXT NOT NULL DEFAULT '', scenario_json TEXT NOT NULL DEFAULT '{}', constraint_index BIGINT NOT NULL DEFAULT 0, hint_level BIGINT NOT NULL DEFAULT 0, cleaned_at TEXT
);

CREATE TABLE studio_diagrams (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, revision BIGINT NOT NULL,
 parent_revision BIGINT, graph_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,revision)
);

CREATE TABLE studio_events (
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE, sequence BIGINT NOT NULL,
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
);

CREATE TABLE studio_idempotency (
 owner_id TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, key TEXT NOT NULL,
 digest TEXT NOT NULL, status BIGINT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,method,path,key)
);

CREATE TABLE studio_turns (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch BIGINT NOT NULL, diagram_revision BIGINT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
 created_at TEXT NOT NULL
, transcript_revision BIGINT NOT NULL DEFAULT 1 CHECK(transcript_revision >= 1), superseded_by TEXT REFERENCES studio_turns(id) ON DELETE SET NULL);

CREATE TABLE studio_proposals (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 base_revision BIGINT NOT NULL, graph_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE studio_review_cards (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 prompt TEXT NOT NULL, evidence_json TEXT NOT NULL, fsrs_json TEXT NOT NULL, due_at TEXT NOT NULL
);

CREATE TABLE repo_snapshots (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL, source_locator TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_hash TEXT,
 total_files BIGINT NOT NULL DEFAULT 0, files_indexed BIGINT NOT NULL DEFAULT 0,
 coverage_json TEXT NOT NULL DEFAULT '{}', failure_code TEXT
);

CREATE TABLE repo_files (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 path TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, language TEXT NOT NULL,
 parse_status TEXT NOT NULL, imports_json TEXT NOT NULL, calls_json TEXT NOT NULL,
 symbols_json TEXT NOT NULL, rank DOUBLE PRECISION NOT NULL DEFAULT 0, UNIQUE(snapshot_id,path)
);

CREATE TABLE repo_chunks (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL REFERENCES repo_files(id) ON DELETE CASCADE, path TEXT NOT NULL,
 symbol TEXT NOT NULL, start_line BIGINT NOT NULL, end_line BIGINT NOT NULL,
 chunk_hash TEXT NOT NULL, text TEXT NOT NULL
);

CREATE TABLE repo_evidence_cards (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, origin TEXT NOT NULL
);

CREATE TABLE repo_defense_sessions (
 id TEXT PRIMARY KEY, studio_session_id TEXT NOT NULL UNIQUE REFERENCES studio_sessions(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 phase TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE repo_defense_answers (
 id TEXT PRIMARY KEY, defense_id TEXT NOT NULL REFERENCES repo_defense_sessions(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL, phase TEXT NOT NULL, answer TEXT NOT NULL, citations_json TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(defense_id,sequence)
);

CREATE TABLE repo_decisions (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, rationale TEXT NOT NULL,
 learner_alternative TEXT, created_at TEXT NOT NULL
);

CREATE TABLE studio_speech_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES studio_sessions(id), epoch BIGINT NOT NULL,
 operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0, tts_chars BIGINT NOT NULL DEFAULT 0,
 request_count BIGINT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(session_id,operation,idempotency_key)
);

CREATE TABLE studio_speech_deleted_daily (day TEXT PRIMARY KEY, request_count BIGINT NOT NULL);

CREATE TABLE studio_model_usage (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
 epoch BIGINT NOT NULL,
 idempotency_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNCERTAIN')),
 created_at TEXT NOT NULL,
 UNIQUE(session_id,idempotency_key)
);

CREATE TABLE studio_model_deleted_daily (
 day TEXT PRIMARY KEY,
 request_count BIGINT NOT NULL CHECK(request_count >= 0)
);

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
);

CREATE TABLE repo_defense_answer_evidence (
 answer_id TEXT PRIMARY KEY REFERENCES repo_defense_answers(id) ON DELETE CASCADE,
 evidence_links_json TEXT NOT NULL DEFAULT '[]',
 changed_requirement TEXT, learner_alternative TEXT,
 unknowns_json TEXT NOT NULL DEFAULT '[]'
);

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
);

CREATE TABLE daily_quiz_attempts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  quiz_id TEXT NOT NULL REFERENCES daily_quizzes(id) ON DELETE CASCADE,
  selected_option_index BIGINT NOT NULL,
  is_correct BIGINT NOT NULL,
  xp_awarded BIGINT NOT NULL DEFAULT 0,
  attempted_at TEXT NOT NULL,
  UNIQUE(user_id, quiz_id)
);

CREATE TABLE user_xp_ledger (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  amount BIGINT NOT NULL,
  reason TEXT NOT NULL,
  reference_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE user_streaks (
  user_id TEXT PRIMARY KEY,
  current_streak BIGINT NOT NULL DEFAULT 1,
  max_streak BIGINT NOT NULL DEFAULT 1,
  last_activity_date TEXT NOT NULL
);

CREATE TABLE user_goals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  date TEXT NOT NULL,
  target_xp BIGINT NOT NULL DEFAULT 100,
  current_xp BIGINT NOT NULL DEFAULT 0,
  completed BIGINT NOT NULL DEFAULT 0,
  UNIQUE(user_id, date)
);

CREATE TABLE weekly_missions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  target_count BIGINT NOT NULL,
  reward_xp BIGINT NOT NULL DEFAULT 150,
  mission_type TEXT NOT NULL,
  week_key TEXT NOT NULL
);

CREATE TABLE user_mission_progress (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  mission_id TEXT NOT NULL REFERENCES weekly_missions(id) ON DELETE CASCADE,
  current_count BIGINT NOT NULL DEFAULT 0,
  completed BIGINT NOT NULL DEFAULT 0,
  completed_at TEXT,
  UNIQUE(user_id, mission_id)
);

CREATE TABLE achievements (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  icon TEXT NOT NULL,
  category TEXT NOT NULL,
  xp_reward BIGINT NOT NULL DEFAULT 100
);

CREATE TABLE user_achievements (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  achievement_slug TEXT NOT NULL REFERENCES achievements(slug) ON DELETE CASCADE,
  unlocked_at TEXT NOT NULL,
  UNIQUE(user_id, achievement_slug)
);

CREATE TABLE user_profiles (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  avatar_initials TEXT NOT NULL,
  total_xp BIGINT NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

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
);

CREATE TABLE learning_answers (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 run BIGINT NOT NULL CHECK(run>=1), epoch BIGINT NOT NULL CHECK(epoch>=1),
 question_id TEXT NOT NULL, answer TEXT NOT NULL CHECK(length(answer) BETWEEN 1 AND 2000),
 correct BIGINT NOT NULL CHECK(correct IN (0,1)), evaluation_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,workspace_id) REFERENCES learning_sessions(id,workspace_id) ON DELETE CASCADE,
 UNIQUE(session_id,epoch)
);

CREATE TABLE learning_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL, run BIGINT NOT NULL CHECK(run>=1),
 kind TEXT NOT NULL CHECK(kind IN ('session.started','session.restarted','answer.evaluated','hint.requested','lesson.completed')),
 source TEXT NOT NULL CHECK(source='learning_engine'), answer_id TEXT REFERENCES learning_answers(id) ON DELETE CASCADE,
 study_seconds BIGINT NOT NULL DEFAULT 0 CHECK(study_seconds BETWEEN 0 AND 300), created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,workspace_id) REFERENCES learning_sessions(id,workspace_id) ON DELETE CASCADE
);

CREATE TABLE learning_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL, title TEXT NOT NULL, earned_at TEXT NOT NULL,
 source_event TEXT NOT NULL REFERENCES learning_events(id) ON DELETE CASCADE,
 PRIMARY KEY(workspace_id,id)
);

CREATE TABLE learning_external_events (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 source TEXT NOT NULL CHECK(source='interview'), source_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='interview.completed'), created_at TEXT NOT NULL, UNIQUE(source,source_id,kind)
);

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
);

CREATE TABLE interview_questions (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL, epoch BIGINT NOT NULL,
 question_json TEXT NOT NULL, asked_at TEXT NOT NULL,
 UNIQUE(session_id,sequence), UNIQUE(session_id,epoch), UNIQUE(session_id,id)
);

CREATE TABLE interview_answers (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 question_id TEXT NOT NULL UNIQUE, epoch BIGINT NOT NULL, answer TEXT NOT NULL,
 code TEXT, created_at TEXT NOT NULL,
 FOREIGN KEY(session_id,question_id) REFERENCES interview_questions(session_id,id),
 UNIQUE(session_id,epoch)
);

CREATE TABLE interview_reports (
 session_id TEXT PRIMARY KEY REFERENCES interview_sessions(id) ON DELETE CASCADE,
 report_json TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE interview_events (
 session_id TEXT NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL, event_type TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence)
);

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
);

CREATE TABLE repo_learning_attempts (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL CHECK(sequence >= 1),
 step_id TEXT NOT NULL,
 answer TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
);

CREATE TABLE repo_learning_evidence_events (
 id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES repo_learning_plans(id) ON DELETE CASCADE,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES repo_learning_attempts(id) ON DELETE CASCADE,
 sequence BIGINT NOT NULL,
 evidence_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(plan_id,sequence)
);

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
);

CREATE TABLE learning_evidence_achievements (
 workspace_id TEXT NOT NULL REFERENCES studio_workspaces(id) ON DELETE CASCADE,
 id TEXT NOT NULL CHECK(id IN ('first_interview','three_study_days')),
 title TEXT NOT NULL, earned_at TEXT NOT NULL, source_event TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('learning_engine','interview')),
 PRIMARY KEY(workspace_id,id)
);

CREATE TABLE module_speech_deleted_totals (
 day TEXT PRIMARY KEY,
 stt_seconds DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK(stt_seconds>=0),
 tts_chars BIGINT NOT NULL DEFAULT 0 CHECK(tts_chars>=0)
);

-- Native full-text search replaces SQLite FTS5 shadow tables.
CREATE TABLE repo_chunks_fts (
 chunk_id TEXT PRIMARY KEY REFERENCES repo_chunks(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 text TEXT NOT NULL,
 search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple',text)) STORED
);
CREATE INDEX repo_chunks_fts_search ON repo_chunks_fts USING GIN(search_vector);
CREATE INDEX repo_chunks_fts_snapshot ON repo_chunks_fts(snapshot_id);
-- Read-only metadata adapter for legacy table-presence checks.
CREATE VIEW sqlite_master AS
 SELECT 'table'::text AS type,table_name::text AS name,table_name::text AS tbl_name,NULL::text AS sql
 FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE';

CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);

CREATE INDEX idx_sessions_created_at ON sessions (created_at);

CREATE INDEX idx_code_versions_session_created ON code_versions (session_id, created_at);

CREATE INDEX idx_turns_session_created ON turns (session_id, created_at);

CREATE INDEX idx_turns_status_created ON turns (state, created_at);

CREATE INDEX idx_capture_attempts_session_created ON capture_attempts (session_id, created_at);

CREATE INDEX idx_capture_attempts_status_created ON capture_attempts (status, created_at);

CREATE INDEX idx_challenges_session_created ON challenges (session_id, created_at);

CREATE INDEX idx_challenges_expires_at ON challenges (expires_at);

CREATE INDEX idx_case_history_session_seen ON case_history (session_id, first_seen_at);

CREATE INDEX idx_jobs_session_created ON jobs (session_id, created_at);

CREATE INDEX idx_jobs_status_created ON jobs (status, created_at);

CREATE INDEX idx_artifacts_session_created ON artifacts (session_id, created_at);

CREATE INDEX idx_traces_session_created ON "legacy_traces" (session_id, created_at);

CREATE INDEX idx_coaching_messages_session_created ON coaching_messages (session_id, created_at);

CREATE INDEX idx_speech_jobs_session_created ON speech_jobs (session_id, created_at);

CREATE INDEX idx_speech_jobs_status_created ON speech_jobs (status, created_at);

CREATE INDEX idx_speech_jobs_expires_at ON speech_jobs (expires_at);

CREATE INDEX idx_idempotency_session_created ON idempotency_records (session_id, created_at);

CREATE INDEX idx_idempotency_status_created ON idempotency_records (status, created_at);

CREATE INDEX idx_idempotency_expires_at ON idempotency_records (expires_at);

CREATE INDEX idx_usage_reservations_session_created ON usage_reservations (session_id, created_at);

CREATE INDEX idx_usage_reservations_status_created ON usage_reservations (status, created_at);

CREATE INDEX idx_usage_ledger_session_created ON usage_ledger (session_id, created_at);

CREATE INDEX idx_usage_ledger_status_created ON usage_ledger (status, created_at);

CREATE INDEX idx_session_events_session_created ON session_events (session_id, created_at);

CREATE INDEX idx_evidence_session ON evidence_artifacts(session_id,created_at);

CREATE INDEX idx_trace_session_v2 ON traces(session_id,created_at);

CREATE INDEX idx_jobs_session_active ON jobs(session_id,status);

CREATE INDEX idx_admission_counters_expiry ON admission_counters (window_start);

CREATE INDEX idx_cleanup_obligations_updated ON cleanup_obligations(updated_at);

CREATE INDEX studio_session_workspace ON studio_sessions(workspace_id);

CREATE INDEX studio_review_due ON studio_review_cards(workspace_id,due_at);

CREATE INDEX idx_repo_snapshots_workspace ON repo_snapshots(workspace_id,id);

CREATE INDEX studio_speech_usage_daily ON studio_speech_usage(created_at,status);

CREATE INDEX studio_model_daily ON studio_model_usage(created_at,status);

CREATE INDEX studio_turns_current ON studio_turns(session_id,superseded_by,created_at);

CREATE INDEX idx_repo_idempotency_snapshot ON repo_idempotency(snapshot_id);

CREATE INDEX idx_repo_idempotency_defense ON repo_idempotency(defense_id);

CREATE INDEX idx_daily_quizzes_date ON daily_quizzes(date);

CREATE INDEX idx_daily_quiz_attempts_user ON daily_quiz_attempts(user_id);

CREATE INDEX idx_user_xp_ledger_user ON user_xp_ledger(user_id);

CREATE INDEX learning_session_workspace ON learning_sessions(workspace_id,state,updated_at);

CREATE INDEX learning_answer_session ON learning_answers(session_id,run);

CREATE INDEX learning_event_workspace ON learning_events(workspace_id,created_at);

CREATE UNIQUE INDEX learning_run_completion ON learning_events(session_id,run) WHERE kind='lesson.completed';

CREATE UNIQUE INDEX learning_answer_event ON learning_events(answer_id,kind) WHERE answer_id IS NOT NULL;

CREATE INDEX learning_external_workspace ON learning_external_events(workspace_id,created_at);

CREATE INDEX interview_workspace ON interview_sessions(workspace_id,started_at);

CREATE INDEX interview_deadline ON interview_sessions(state,deadline_at);

CREATE UNIQUE INDEX interview_single_completion ON interview_events(session_id)
 WHERE event_type='interview.completed';

CREATE INDEX idx_repo_learning_attempts_rate ON repo_learning_attempts(created_at,plan_id);

CREATE INDEX module_speech_daily ON module_speech_usage(created_at,status);

CREATE INDEX module_speech_source ON module_speech_usage(workspace_id,module,source_id,status);
