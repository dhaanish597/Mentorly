"""Canonical enums for Voice Coding Coach (frozen in Phase 0, extended for Phase 1 & Phase 2)."""

from enum import IntEnum, StrEnum


class ExerciseId(StrEnum):
    EX1_SHORTEST_SUBARRAY = "ex1_shortest_subarray"
    EX2_BINARY_SEARCH = "ex2_binary_search"
    EX3_MAX_PRODUCT = "ex3_max_product"
    EX4_SUM_EVEN = "ex4_sum_even"
    EX5_COUNT_NEGATIVE = "ex5_count_negative"
    EX6_RUNNING_TOTALS = "ex6_running_totals"
    EX7_STABLE_UNIQUE = "ex7_stable_unique"
    EX8_ROTATE_RIGHT = "ex8_rotate_right"
    EX9_FIRST_PEAK = "ex9_first_peak"
    EX10_SECOND_LARGEST_DISTINCT = "ex10_second_largest_distinct"
    EX11_PAIR_SUM_EXISTS = "ex11_pair_sum_exists"
    EX12_MERGE_SORTED = "ex12_merge_sorted"
    EX13_LONGEST_INCREASING_RUN = "ex13_longest_increasing_run"
    EX14_BALANCE_POINT = "ex14_balance_point"
    EX15_REVERSE_WORDS = "ex15_reverse_words"
    EX16_NORMALIZE_SPACES = "ex16_normalize_spaces"
    EX17_IS_PALINDROME = "ex17_is_palindrome"
    EX18_COUNT_VOWELS = "ex18_count_vowels"
    EX19_FIRST_UNIQUE_CHAR = "ex19_first_unique_char"
    EX20_RUN_LENGTHS = "ex20_run_lengths"
    EX21_COMMON_PREFIX = "ex21_common_prefix"
    EX22_DIGIT_SUM = "ex22_digit_sum"
    EX23_GREATEST_COMMON_DIVISOR = "ex23_greatest_common_divisor"
    EX24_FACTORIAL = "ex24_factorial"
    EX25_IS_PRIME = "ex25_is_prime"
    EX26_COUNT_BITS = "ex26_count_bits"
    EX27_FIZZ_LABELS = "ex27_fizz_labels"
    EX28_TOGGLE = "ex28_toggle"
    EX29_ALL_TRUE = "ex29_all_true"
    EX30_INVERT_FLAGS = "ex30_invert_flags"
    EX31_BALANCED_BRACKETS = "ex31_balanced_brackets"


class SpecVersion(StrEnum):
    EX1_V1_POSITIVE_ONLY = "v1_positive_only"
    EX1_V2_NEGATIVES_ALLOWED = "v2_negatives_allowed"
    EX2_V1_SORTED_WITH_DUPLICATES = "v1_sorted_with_duplicates"
    EX3_V1_BOUNDED_INTS = "v1_bounded_ints"
    V1_TYPED_BOUNDED = "v1_typed_bounded"


class SpeechLocale(StrEnum):
    EN_IN = "en-IN"
    HI_IN = "hi-IN"
    TA_IN = "ta-IN"
    TE_IN = "te-IN"
    KN_IN = "kn-IN"
    ML_IN = "ml-IN"
    BN_IN = "bn-IN"
    GU_IN = "gu-IN"
    MR_IN = "mr-IN"
    PA_IN = "pa-IN"


class LanguageMode(StrEnum):
    EN_IN = "en-IN"
    HI_IN = "hi-IN"
    TA_IN = "ta-IN"
    TE_IN = "te-IN"
    KN_IN = "kn-IN"
    ML_IN = "ml-IN"
    BN_IN = "bn-IN"
    GU_IN = "gu-IN"
    MR_IN = "mr-IN"
    PA_IN = "pa-IN"
    TA_EN_CODEMIX = "ta-IN,en-IN"
    TA_IN_EN_IN = "ta-IN,en-IN"
    HI_IN_EN_IN = "hi-IN,en-IN"
    BN_IN_EN_IN = "bn-IN,en-IN"


class TTSVoice(StrEnum):
    AVINASH = "Avinash"
    SHIVANI = "Shivani"
    LAKSHMI = "Lakshmi"
    KALPANA = "Kalpana"
    SHUBHAM = "Shubham"
    PRAKASH = "Prakash"
    DEVANSH = "Devansh"
    YASHRAJ = "Yashraj"
    CHETANA = "Chetana"
    VASUDHA = "Vasudha"
    RIYAA = "Riyaa"
    TARIKA = "Tarika"
    HARSHAD = "Harshad"


class InteractionMode(StrEnum):
    VOICE = "VOICE"
    TYPED_FALLBACK = "TYPED_FALLBACK"
    DEMO = "DEMO"


class TransportMode(StrEnum):
    REST = "REST"
    WEBSOCKET = "WEBSOCKET"
    TEXT = "TEXT"


class SessionState(StrEnum):
    IDLE = "IDLE"
    SESSION_INITIALIZING = "SESSION_INITIALIZING"
    READY = "READY"
    SPEC_ACK_REQUIRED = "SPEC_ACK_REQUIRED"
    DELETED = "DELETED"


class LearningState(StrEnum):
    EXPLAINING = "EXPLAINING"
    AWAITING_PREDICTION = "AWAITING_PREDICTION"
    VERIFYING = "VERIFYING"
    INSPECTING_RESULT = "INSPECTING_RESULT"
    PREDICTION_REVIEW = "PREDICTION_REVIEW"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    FRESH_CASE_CHECK = "FRESH_CASE_CHECK"
    FRESH_CASE_REVIEW = "FRESH_CASE_REVIEW"
    PRACTICE_CHECKPOINT_COMPLETED = "PRACTICE_CHECKPOINT_COMPLETED"


class TurnState(StrEnum):
    CREATED = "CREATED"
    RECORDING_AUDIO = "RECORDING_AUDIO"
    TRANSCRIBING_AND_PARSING = "TRANSCRIBING_AND_PARSING"
    AWAITING_CLAIM_CONFIRMATION = "AWAITING_CLAIM_CONFIRMATION"
    CLAIM_FALLBACK_EDIT = "CLAIM_FALLBACK_EDIT"
    VERIFYING_AND_COACHING = "VERIFYING_AND_COACHING"
    AUDIO_READY = "AUDIO_READY"
    AWAITING_PLAYBACK_ACK = "AWAITING_PLAYBACK_ACK"
    COACH_PROMPT_DELIVERED = "COACH_PROMPT_DELIVERED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ChallengePurpose(StrEnum):
    DIAGNOSTIC = "DIAGNOSTIC"
    TRANSFER = "TRANSFER"


class RevealState(StrEnum):
    HIDDEN = "HIDDEN"
    REVEALED = "REVEALED"


class ClaimType(StrEnum):
    OUTPUT_PREDICTION_AND_REASON = "OUTPUT_PREDICTION_AND_REASON"
    INVARIANT_OR_MECHANISM_CLAIM = "INVARIANT_OR_MECHANISM_CLAIM"
    DOMAIN_VALIDITY_CLAIM = "DOMAIN_VALIDITY_CLAIM"
    CLARIFICATION_OR_HINT_REQUEST = "CLARIFICATION_OR_HINT_REQUEST"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"


class ClaimPolarity(StrEnum):
    AFFIRMATIVE = "AFFIRMATIVE"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class ExtractionMethod(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    MODEL_ASSISTED = "MODEL_ASSISTED"
    USER_EDITED = "USER_EDITED"


class ExecutionObservationKind(StrEnum):
    RETURN = "RETURN"
    EXCEPTION = "EXCEPTION"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INVALID_RESULT = "INVALID_RESULT"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationStatus(StrEnum):
    COUNTEREXAMPLE_CONFIRMED = "COUNTEREXAMPLE_CONFIRMED"
    NO_FAILURE_FOUND = "NO_FAILURE_FOUND"
    VERIFICATION_INCOMPLETE = "VERIFICATION_INCOMPLETE"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    EXECUTION_UNAVAILABLE = "EXECUTION_UNAVAILABLE"
    REPLAY_UNCONFIRMED = "REPLAY_UNCONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class PredictionStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_EVALUATED = "NOT_EVALUATED"


class MinimizationStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SHRINK_COMPLETED = "SHRINK_COMPLETED"
    BUDGET_LIMITED = "BUDGET_LIMITED"


class TraceEventKind(StrEnum):
    CALL = "CALL"
    LINE = "LINE"
    RETURN = "RETURN"
    EXCEPTION = "EXCEPTION"
    TRUNCATED = "TRUNCATED"


class TraceAttributionStatus(StrEnum):
    ATTRIBUTED = "ATTRIBUTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"
    TAMPERED = "TAMPERED"


class TraceExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    TRACE_TIMEOUT = "TRACE_TIMEOUT"
    TRACE_UNAVAILABLE = "TRACE_UNAVAILABLE"
    TRACE_TAMPERED = "TRACE_TAMPERED"


class SpeechMode(StrEnum):
    LIVE = "LIVE"
    CACHED = "CACHED"
    DEMO = "DEMO"


class SpeechDegradationStatus(StrEnum):
    HEALTHY = "HEALTHY"
    SPEECH_BUSY_TEXT_FALLBACK = "SPEECH_BUSY_TEXT_FALLBACK"
    STT_UNAVAILABLE_TEXT_FALLBACK = "STT_UNAVAILABLE_TEXT_FALLBACK"
    TTS_UNAVAILABLE_READ_FALLBACK = "TTS_UNAVAILABLE_READ_FALLBACK"
    QUOTA_EXHAUSTED_TEXT_ONLY = "QUOTA_EXHAUSTED_TEXT_ONLY"


class PlaybackStatus(StrEnum):
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    READ_TEXT_FALLBACK = "READ_TEXT_FALLBACK"


class HintLevel(IntEnum):
    DIAGNOSTIC_QUESTION = 1
    TRACE_STEP_POINTER = 2
    REPAIR_PRINCIPLE = 3
