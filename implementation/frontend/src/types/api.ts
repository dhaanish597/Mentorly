/**
 * Canonical TypeScript Contracts for Voice Coding Coach (`frontend/src/types/api.ts`).
 * Deterministically generated and verified by `scripts/check_schema_drift.py`.
 * DO NOT EDIT MANUALLY without updating `backend/app/models/{enums,domain,api_schemas}.py`.
 */

export type ExerciseId = 'ex1_shortest_subarray' | 'ex2_binary_search' | 'ex3_max_product' | 'ex4_sum_even' | 'ex5_count_negative' | 'ex6_running_totals' | 'ex7_stable_unique' | 'ex8_rotate_right' | 'ex9_first_peak' | 'ex10_second_largest_distinct' | 'ex11_pair_sum_exists' | 'ex12_merge_sorted' | 'ex13_longest_increasing_run' | 'ex14_balance_point' | 'ex15_reverse_words' | 'ex16_normalize_spaces' | 'ex17_is_palindrome' | 'ex18_count_vowels' | 'ex19_first_unique_char' | 'ex20_run_lengths' | 'ex21_common_prefix' | 'ex22_digit_sum' | 'ex23_greatest_common_divisor' | 'ex24_factorial' | 'ex25_is_prime' | 'ex26_count_bits' | 'ex27_fizz_labels' | 'ex28_toggle' | 'ex29_all_true' | 'ex30_invert_flags' | 'ex31_balanced_brackets';
export type SpecVersion = 'v1_positive_only' | 'v2_negatives_allowed' | 'v1_sorted_with_duplicates' | 'v1_bounded_ints' | 'v1_typed_bounded';
export type LanguageMode = 'en-IN' | 'hi-IN' | 'ta-IN' | 'te-IN' | 'kn-IN' | 'ml-IN' | 'bn-IN' | 'gu-IN' | 'mr-IN' | 'pa-IN' | 'ta-IN,en-IN' | 'hi-IN,en-IN' | 'bn-IN,en-IN';
export type SpeechLocale = 'en-IN' | 'hi-IN' | 'ta-IN' | 'te-IN' | 'kn-IN' | 'ml-IN' | 'bn-IN' | 'gu-IN' | 'mr-IN' | 'pa-IN';
export type TTSVoice = 'Avinash' | 'Shivani' | 'Lakshmi' | 'Kalpana' | 'Shubham' | 'Prakash' | 'Devansh' | 'Yashraj' | 'Chetana' | 'Vasudha' | 'Riyaa' | 'Tarika' | 'Harshad';
export type InteractionMode = 'VOICE' | 'TYPED_FALLBACK' | 'DEMO';
export type TransportMode = 'REST' | 'WEBSOCKET' | 'TEXT';
export type SessionState = 'IDLE' | 'SESSION_INITIALIZING' | 'READY' | 'SPEC_ACK_REQUIRED' | 'DELETED';
export type LearningState = 'EXPLAINING' | 'AWAITING_PREDICTION' | 'VERIFYING' | 'INSPECTING_RESULT' | 'PREDICTION_REVIEW' | 'REPAIR_REQUIRED' | 'FRESH_CASE_CHECK' | 'FRESH_CASE_REVIEW' | 'PRACTICE_CHECKPOINT_COMPLETED';
export type TurnState = 'CREATED' | 'RECORDING_AUDIO' | 'TRANSCRIBING_AND_PARSING' | 'AWAITING_CLAIM_CONFIRMATION' | 'CLAIM_FALLBACK_EDIT' | 'VERIFYING_AND_COACHING' | 'AUDIO_READY' | 'AWAITING_PLAYBACK_ACK' | 'COACH_PROMPT_DELIVERED' | 'SUPERSEDED' | 'CANCELLED';
export type JobStatus = 'QUEUED' | 'RUNNING' | 'COMPLETE' | 'FAILED' | 'CANCELLED' | 'SUPERSEDED';
export type ChallengePurpose = 'DIAGNOSTIC' | 'TRANSFER';
export type RevealState = 'HIDDEN' | 'REVEALED';
export type ClaimType = 'OUTPUT_PREDICTION_AND_REASON' | 'INVARIANT_OR_MECHANISM_CLAIM' | 'DOMAIN_VALIDITY_CLAIM' | 'CLARIFICATION_OR_HINT_REQUEST' | 'UNSUPPORTED_CLAIM';
export type ClaimPolarity = 'AFFIRMATIVE' | 'NEGATIVE' | 'UNKNOWN';
export type ExtractionMethod = 'DETERMINISTIC' | 'MODEL_ASSISTED' | 'USER_EDITED';
export type ExecutionObservationKind = 'RETURN' | 'EXCEPTION' | 'TIMEOUT' | 'RESOURCE_LIMIT' | 'INVALID_RESULT' | 'UNAVAILABLE';
export type VerificationStatus = 'COUNTEREXAMPLE_CONFIRMED' | 'NO_FAILURE_FOUND' | 'VERIFICATION_INCOMPLETE' | 'EXECUTION_ERROR' | 'TIMEOUT' | 'SYNTAX_ERROR' | 'EXECUTION_UNAVAILABLE' | 'REPLAY_UNCONFIRMED' | 'SUPERSEDED';
export type PredictionStatus = 'MATCH' | 'MISMATCH' | 'NOT_EVALUATED';
export type MinimizationStatus = 'NOT_ATTEMPTED' | 'SHRINK_COMPLETED' | 'BUDGET_LIMITED';
export type TraceEventKind = 'CALL' | 'LINE' | 'RETURN' | 'EXCEPTION' | 'TRUNCATED';
export type TraceAttributionStatus = 'ATTRIBUTED' | 'AMBIGUOUS' | 'UNAVAILABLE' | 'TAMPERED';
export type TraceExecutionStatus = 'COMPLETED' | 'PARTIAL' | 'TRACE_TIMEOUT' | 'TRACE_UNAVAILABLE' | 'TRACE_TAMPERED';
export type SpeechMode = 'LIVE' | 'CACHED' | 'DEMO';
export type SpeechDegradationStatus = 'HEALTHY' | 'SPEECH_BUSY_TEXT_FALLBACK' | 'STT_UNAVAILABLE_TEXT_FALLBACK' | 'TTS_UNAVAILABLE_READ_FALLBACK' | 'QUOTA_EXHAUSTED_TEXT_ONLY';
export type PlaybackStatus = 'COMPLETED' | 'INTERRUPTED' | 'READ_TEXT_FALLBACK';
export type HintLevel = 1 | 2 | 3;

export interface TTSPlaybackRequest {
  revision: RevisionRef;
  artifact_id: string;
  hint_level?: HintLevel;
  language?: SpeechLocale | 'auto' | null;
  voice?: TTSVoice | null;
}

export interface HealthResponse {
  status: 'ok';
  service: string;
  phase: string;
  version: string;
  custom_code_execution_enabled: boolean;
  execution_status?: 'DISABLED' | 'BLOCKED_EXTERNAL' | 'READY';
  product_name: string;
  product_name_status: string;
}

export interface BrandingInfo {
  productName: string;
  productNameStatus: string;
  shortName: string;
  tagline: string;
}

export interface BrandingResponse {
  productName: string;
  productNameStatus: string;
  shortName: string;
  tagline: string;
}

export interface ValueSchema {
  kind: 'integer' | 'boolean' | 'string' | 'list';
  minimum?: number | null;
  maximum?: number | null;
  min_length?: number | null;
  max_length?: number | null;
  items?: ValueSchema | null;
  sorted_required?: boolean;
}

export interface ExerciseExample {
  input_args: Record<string, unknown>;
  output: number | boolean | string | (number | boolean | string)[];
  explanation: string;
}

export interface CatalogProvenance {
  source: 'original';
  status: 'ORIGINAL_AUTHORED';
  license?: string | null;
}

export interface ExerciseSpecMetadata {
  spec_version: string;
  label: string;
  min_length: number;
  max_length: number;
  min_value: number;
  max_value: number;
  target_bounds?: [number, number] | null;
  sorted_required: boolean;
  constraints_summary: string[];
  input_schema?: Record<string, ValueSchema>;
  output_schema?: ValueSchema | null;
  recommended_generated_cases?: number;
  available_fresh_cases?: number;
}

export interface ExerciseMetadata {
  exercise_id: string;
  title: string;
  function_name: string;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  core_concepts: string[];
  description: string;
  starter_code: string;
  default_spec_version: string;
  spec_versions: ExerciseSpecMetadata[];
  input_schema?: Record<string, ValueSchema>;
  output_schema?: ValueSchema | null;
  examples?: ExerciseExample[];
  tags?: string[];
  collection?: string;
  comparator: 'strict_structural';
  catalog_status: 'READY';
  provenance?: CatalogProvenance;
}

export interface DemoPresetMetadata {
  preset_id: string;
  title: string;
  exercise_id: string;
  spec_version: string;
  language_mode: 'en-IN' | 'ta-IN,en-IN';
  provenance_label: 'RECORDED_DEMO' | 'LIVE_SESSION';
  description: string;
  starter_code: string;
}

export interface RevisionRef {
  session_id: string;
  exercise_id: ExerciseId;
  spec_version: SpecVersion;
  code_version_id: number;
  code_hash: string;
  turn_generation: number;
}

export interface Challenge {
  challenge_id: string;
  revision: RevisionRef;
  input_args: Record<string, unknown>;
  case_hash: string;
  purpose: ChallengePurpose;
  reveal_state?: RevealState;
  created_at: string;
  expires_at: string;
}

export interface OutputPredictionClaim {
  challenge_id: string;
  critical_tokens?: string[];
  provider_confidence?: number | null;
  extraction_method: ExtractionMethod;
  model_status?: 'MODEL_DISABLED' | 'MODEL_NOT_CONFIGURED' | 'MODEL_TIMEOUT' | 'MODEL_RATE_LIMITED' | 'MODEL_INVALID_RESPONSE' | 'MODEL_UNAVAILABLE' | 'MODEL_ASSISTED' | 'DETERMINISTIC_FALLBACK' | null;
  confirmed_at?: string | null;
  claim_type: 'OUTPUT_PREDICTION_AND_REASON';
  predicted_output: number | boolean | string | (number | boolean | string)[];
  reason_summary?: string | null;
  polarity?: ClaimPolarity;
}

export interface InvariantOrMechanismClaim {
  challenge_id?: string | null;
  critical_tokens?: string[];
  provider_confidence?: number | null;
  extraction_method: ExtractionMethod;
  model_status?: 'MODEL_DISABLED' | 'MODEL_NOT_CONFIGURED' | 'MODEL_TIMEOUT' | 'MODEL_RATE_LIMITED' | 'MODEL_INVALID_RESPONSE' | 'MODEL_UNAVAILABLE' | 'MODEL_ASSISTED' | 'DETERMINISTIC_FALLBACK' | null;
  confirmed_at?: string | null;
  claim_type: 'INVARIANT_OR_MECHANISM_CLAIM';
  mechanism_summary: string;
  polarity?: ClaimPolarity;
}

export interface DomainValidityClaim {
  challenge_id?: string | null;
  critical_tokens?: string[];
  provider_confidence?: number | null;
  extraction_method: ExtractionMethod;
  model_status?: 'MODEL_DISABLED' | 'MODEL_NOT_CONFIGURED' | 'MODEL_TIMEOUT' | 'MODEL_RATE_LIMITED' | 'MODEL_INVALID_RESPONSE' | 'MODEL_UNAVAILABLE' | 'MODEL_ASSISTED' | 'DETERMINISTIC_FALLBACK' | null;
  confirmed_at?: string | null;
  claim_type: 'DOMAIN_VALIDITY_CLAIM';
  target_spec_version: SpecVersion;
  polarity: ClaimPolarity;
}

export interface ClarificationOrHintClaim {
  challenge_id?: string | null;
  critical_tokens?: string[];
  provider_confidence?: number | null;
  extraction_method: ExtractionMethod;
  model_status?: 'MODEL_DISABLED' | 'MODEL_NOT_CONFIGURED' | 'MODEL_TIMEOUT' | 'MODEL_RATE_LIMITED' | 'MODEL_INVALID_RESPONSE' | 'MODEL_UNAVAILABLE' | 'MODEL_ASSISTED' | 'DETERMINISTIC_FALLBACK' | null;
  confirmed_at?: string | null;
  claim_type: 'CLARIFICATION_OR_HINT_REQUEST';
  question_text: string;
}

export interface UnsupportedClaim {
  challenge_id?: string | null;
  critical_tokens?: string[];
  provider_confidence?: number | null;
  extraction_method: ExtractionMethod;
  model_status?: 'MODEL_DISABLED' | 'MODEL_NOT_CONFIGURED' | 'MODEL_TIMEOUT' | 'MODEL_RATE_LIMITED' | 'MODEL_INVALID_RESPONSE' | 'MODEL_UNAVAILABLE' | 'MODEL_ASSISTED' | 'DETERMINISTIC_FALLBACK' | null;
  confirmed_at?: string | null;
  claim_type: 'UNSUPPORTED_CLAIM';
  raw_summary: string;
}

export interface ExecutionObservation {
  kind: ExecutionObservationKind;
  return_value?: number | boolean | string | (number | boolean | string)[] | null;
  error_type?: string | null;
  error_message?: string | null;
  stdout_excerpt?: string;
  stderr_excerpt?: string;
  duration_ms: number;
}

export interface HypothesisStatistics {
  engine: 'hypothesis';
  version: string;
  seed: number;
  requested_cases: number;
  accepted_cases: number;
  attempts: number;
  invalid: number;
  duplicates: number;
  excluded: number;
  executed_cases: number;
  max_attempts: number;
  generation_wall_ms: number;
  stop_reason: 'empty_request' | 'hypothesis_exhausted' | 'cancelled' | 'wall_time_limit' | 'attempt_limit' | 'target_reached';
}

export interface VerificationReport {
  hypothesis_stats?: HypothesisStatistics | null;
  status: VerificationStatus;
  curated_cases_run: number;
  curated_cases_total: number;
  generated_cases_run: number;
  generated_cases_target: number;
  requested_generated_cases_target?: number | null;
  completed_stages?: string[];
  terminal_reason: string;
  seed?: number | null;
  runtime_version: string;
  minimization_status?: MinimizationStatus;
  executed_case_hashes?: string[];
  counterexample_input?: Record<string, unknown> | null;
  counterexample_case_hash?: string | null;
  student_observation?: ExecutionObservation | null;
  reference_output?: number | boolean | string | (number | boolean | string)[] | null;
}

export interface TraceStep {
  event_id: number;
  frame_id: string;
  parent_frame_id?: string | null;
  call_depth: number;
  source_hash: string;
  source_line: number;
  event_kind: TraceEventKind;
  attribution_status: TraceAttributionStatus;
  locals_snapshot?: Record<string, unknown>;
  truncated_values?: string[];
}

export interface TraceExecutionReport {
  trace_id: string;
  revision: RevisionRef;
  case_hash: string;
  status: TraceExecutionStatus;
  steps?: TraceStep[];
  total_observed: number;
  trace_truncated?: boolean;
  termination_reason: string;
  observation?: ExecutionObservation | null;
  runtime_version: string;
}

export interface ExecutionBudgetConfig {
  startup_deadline_ms?: number;
  invocation_wall_ms?: number;
  invocation_cpu_seconds?: number;
  memory_limit_mb?: number;
  pids_limit?: number;
  tmpfs_size_mb?: number;
  max_stdout_bytes?: number;
  max_stderr_bytes?: number;
  max_result_bytes?: number;
  max_trace_bytes?: number;
  max_trace_steps?: number;
  max_trace_snapshots_work?: number;
  job_wall_ms?: number;
  shrink_wall_ms?: number;
  replay_reserve_ms?: number;
}

export interface ExecutionRequest {
  job_id: string;
  revision: RevisionRef;
  challenge_id?: string | null;
  source_code: string;
  input_args: Record<string, unknown>;
  case_hash: string;
  budget?: ExecutionBudgetConfig;
}

export interface VerifyJobRequest {
  job_id: string;
  revision: RevisionRef;
  challenge_id?: string | null;
  source_code: string;
  prior_failing_input?: Record<string, unknown> | null;
  target_input?: Record<string, unknown> | null;
  run_curated_suite?: boolean;
  generated_cases_target?: number;
  seed?: number | null;
  budget?: ExecutionBudgetConfig;
}

export interface TraceRequest {
  job_id: string;
  trace_id: string;
  revision: RevisionRef;
  challenge_id?: string | null;
  source_code: string;
  input_args: Record<string, unknown>;
  case_hash: string;
  budget?: ExecutionBudgetConfig;
}

export interface JobHandle {
  job_id: string;
  revision: RevisionRef;
  status: JobStatus;
  observation?: ExecutionObservation | null;
  verification_report?: VerificationReport | null;
  trace_report?: TraceExecutionReport | null;
}

export interface EvidenceArtifact {
  schema_version?: string;
  artifact_id: string;
  revision: RevisionRef;
  challenge_id: string;
  canonical_input: Record<string, unknown>;
  case_hash: string;
  confirmed_prediction?: number | boolean | string | (number | boolean | string)[] | null;
  actual_observation: ExecutionObservation;
  reference_output: number | boolean | string | (number | boolean | string)[];
  prediction_status: PredictionStatus;
  verification_report: VerificationReport;
  trace_id?: string | null;
  minimization_status?: MinimizationStatus;
  timings_ms?: Record<string, number>;
}

export interface HiddenEvidenceArtifactView {
  schema_version?: string;
  artifact_id: string;
  revision: RevisionRef;
  challenge_id: string;
  canonical_input: Record<string, unknown>;
  case_hash: string;
  reveal_state: 'HIDDEN';
  confirmed_prediction?: number | boolean | string | (number | boolean | string)[] | null;
  prediction_status?: PredictionStatus;
}

export interface SpeechJob {
  speech_job_id: string;
  playback_id: string;
  revision: RevisionRef;
  turn_id: string;
  coaching_message_id: string;
  normalized_text_hash: string;
  status: string;
  mode: SpeechMode;
  audio_url?: string | null;
  expires_at: string;
}

export interface ApiError {
  code: string;
  message: string;
  request_id: string;
  retryable?: boolean;
  turn_id?: string | null;
  job_id?: string | null;
}

export interface CreateSessionRequest {
  exercise_id: ExerciseId;
  spec_version: SpecVersion;
  language_mode?: LanguageMode;
  interaction_mode?: InteractionMode;
  voice?: TTSVoice | null;
  spoken_language?: SpeechLocale | null;
}

export interface CreateSessionResponse {
  session_id: string;
  session_token: string;
  starter_code: string;
  revision: RevisionRef;
  state: SessionState;
  learning_state: LearningState;
  spec_acknowledged: boolean;
  voice?: TTSVoice | null;
  spoken_language?: SpeechLocale | null;
}

export interface CodeUpdateRequest {
  code: string;
  expected_code_version_id: number;
  client_edit_sequence: number;
}

export interface CodeUpdateResponse {
  revision: RevisionRef;
  changed: boolean;
  ast_symbols?: string[];
  syntax_error?: string | null;
}

export interface SpecUpdateRequest {
  target_spec_version: SpecVersion;
  expected_revision: RevisionRef;
}

export interface SpecAckRequest {
  spec_version: SpecVersion;
  revision: RevisionRef;
}

export interface CreateChallengeRequest {
  purpose: ChallengePurpose;
  revision: RevisionRef;
  requested_input?: Record<string, unknown> | null;
}

export interface TextTurnRequest {
  text: string;
  revision: RevisionRef;
  challenge_id?: string | null;
}

export interface ConfirmClaimRequest {
  challenge_id?: string | null;
  revision: RevisionRef;
  capture_attempt_id?: number | null;
  claim: OutputPredictionClaim | InvariantOrMechanismClaim | DomainValidityClaim | ClarificationOrHintClaim | UnsupportedClaim;
}

export interface VerifyRequest {
  revision: RevisionRef;
  prior_artifact_id?: string | null;
  run_curated_suite?: boolean;
  generated_cases_target?: number;
}

export interface RetryExecutionRequest {
  revision: RevisionRef;
}

export interface FreshCaseCheckRequest {
  challenge_id: string;
  revision: RevisionRef;
  confirmed_prediction: number | boolean | string | (number | boolean | string)[];
}

export interface HintRequest {
  artifact_id: string;
  requested_level: HintLevel;
  revision: RevisionRef;
}

export interface PlaybackAckRequest {
  playback_id: string;
  revision: RevisionRef;
  playback_status: PlaybackStatus;
  played_duration_ms: number;
}

export interface CancelRequest {
  scope?: 'INTERRUPT' | 'TURN';
  turn_id?: string | null;
  job_id?: string | null;
  playback_id?: string | null;
  reason: string;
}

export interface CancelResponse {
  unconfirmed_job_ids?: string[];
  cancelled_turn_ids?: string[];
  cancelled_job_ids?: string[];
  cancelled_playback_ids?: string[];
}

export interface JobAcceptedResponse {
  job_id: string;
  turn_id?: string | null;
  status?: JobStatus;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
}

export interface OperationsReadinessResponse {
  status: 'READY' | 'BLOCKED_EXTERNAL';
  checked_at: string;
  database_ready: boolean;
  execution_ready: boolean;
  canary_status: 'NOT_RUN' | 'PASSED' | 'FAILED';
  canary_duration_ms?: number | null;
  speech_status: 'UNAVAILABLE' | 'CONFIGURED_UNVERIFIED';
}

export interface CapacityResponse {
  speech_queue_depth: number;
  custom_code_execution_enabled: boolean;
  mode: 'LIVE' | 'CACHED' | 'DEMO';
}

export interface SessionExportResponse {
  export_version?: string;
  exported_at: string;
  session_id: string;
  revision: RevisionRef;
  challenges?: Challenge[];
  evidence_artifacts?: EvidenceArtifact[];
}

export interface DeleteSessionResponse {
  session_id: string;
  deleted_at: string;
  limitations: string;
}

export interface STTRequest {
  session_id: string;
  turn_generation?: number;
  capture_attempt_id?: number;
  revision?: RevisionRef | null;
  exercise_id?: ExerciseId;
  spec_version?: SpecVersion;
  language_mode?: LanguageMode;
  source_code?: string;
  previous_audio_transcript?: string | null;
  topic_override?: string | null;
  request_id?: string;
}

export interface STTResult {
  request_id: string;
  client_request_id: string;
  provider_request_id?: string | null;
  configured_model?: string;
  provider_model?: string | null;
  truncated?: boolean;
  transport?: 'REST_V3' | 'WS_V3';
  language_mode: LanguageMode;
  observed_format: 'transcribe' | 'codemix';
  raw_transcript: string;
  normalized_transcript: string;
  normalization_notes?: string[];
  contains_self_correction?: boolean;
  requires_confirmation?: boolean;
  provider_confidence?: number | null;
  detected_language_code?: string | null;
  audio_duration_sec: number;
  low_energy_warning?: boolean;
  latency_ms: number;
}

export interface TTSAudioConfig {
  encoding: 'linear_pcm';
  container?: 'raw' | 'wav';
  sample_rate?: number;
  num_channels?: number;
  sample_width?: number;
}

export interface TTSRequest {
  session_id: string;
  turn_generation?: number;
  turn_id?: string | null;
  playback_id?: string | null;
  revision?: RevisionRef | null;
  text: string;
  model: 'timbre-v3.0';
  voice?: TTSVoice;
  language?: SpeechLocale | 'auto';
  speed?: number;
  audio_config?: TTSAudioConfig;
  cache_scope?: 'PUBLIC_GENERIC' | 'SESSION_SCOPED';
  request_id?: string;
}

export interface AudioEvent {
  event_type: 'start' | 'chunk' | 'complete' | 'error';
  request_id: string;
  client_request_id?: string | null;
  provider_request_id?: string | null;
  playback_id?: string | null;
  segment_index?: number;
  chunk_index?: number | null;
  audio_b64?: string | null;
  wav_bytes_b64?: string | null;
  sample_rate?: number;
  duration_ms?: number | null;
  cache_hit?: boolean;
  error_code?: string | null;
  error_message?: string | null;
}

export interface SpeechCapacityStatus {
  deployment_topology: 'SINGLE_PROCESS_LOCAL_SEMAPHORE';
  max_concurrency?: number;
  active_requests: number;
  queued_requests: number;
  max_waiting: number;
  degradation_status?: SpeechDegradationStatus;
  stt_seconds_used: number;
  stt_seconds_reserved?: number;
  stt_seconds_uncertain?: number;
  tts_chars_used: number;
  tts_chars_reserved?: number;
  tts_chars_uncertain?: number;
  stt_requests_count: number;
  tts_requests_count: number;
  uncertain_requests_count?: number;
  credit_remaining_status?: string;
}

export interface VoicePlaybackAckRequest {
  playback_id?: string;
  session_id: string;
  turn_id: string;
  turn_generation: number;
  revision?: RevisionRef | null;
  playback_status: PlaybackStatus;
  played_duration_ms: number;
}

export interface VoicePlaybackAckResponse {
  playback_id?: string;
  session_id: string;
  turn_id: string;
  turn_generation: number;
  playback_status: PlaybackStatus;
  acknowledged?: boolean;
}

export type ClaimInterpretation =
  | OutputPredictionClaim
  | InvariantOrMechanismClaim
  | DomainValidityClaim
  | ClarificationOrHintClaim
  | UnsupportedClaim;
