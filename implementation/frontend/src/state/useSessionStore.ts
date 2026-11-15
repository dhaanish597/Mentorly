/**
 * Authoritative Frontend Session & 13-View State Store (`frontend/src/state/useSessionStore.ts`).
 *
 * Implements Plan §7 & §11 (Phases P3, P4, P5, P7):
 * - Covers all 13 UI views/states:
 *   1. `ONBOARDING_MIC_CHECK`
 *   2. `EXERCISE_BRIEF_SPEC`
 *   3. `DOMAIN_SHIFT_ACK_GATE`
 *   4. `EXPLAIN_APPROACH_TURN`
 *   5. `PREDICT_CHALLENGE_OUTPUT`
 *   6. `TRANSCRIPT_CLAIM_CONFIRMATION`
 *   7. `ISOLATED_VERIFICATION_PROGRESS`
 *   8. `REVEALED_COMPARISON_VIEW`
 *   9. `TRACE_SCRUBBER_INSPECTION`
 *   10. `SOCRATIC_HINT_PROGRESSION`
 *   11. `FRESH_TRANSFER_CHALLENGE`
 *   12. `PRACTICE_CHECKPOINT_SUMMARY`
 *   13. `QUEUE_DEGRADATION_RECOVERY`
 * - Enforces serialized client code saves, immediate stale-feedback suppression (`editorDirty = true`
 *   marks prior counterexamples/traces/hints as `STALE_BUFFER`), and logical-turn `captureAttemptId`
 *   incrementing on re-record without incrementing `turnGeneration`.
 */

import type {
  Challenge,
  ClaimInterpretation,
  EvidenceArtifact,
  ExerciseId,
  HintLevel,
  InteractionMode,
  LanguageMode,
  LearningState,
  RevisionRef,
  SessionState,
  SpecVersion,
  SpeechDegradationStatus,
  TraceExecutionReport,
  VerificationReport,
} from '../types/api';

export type WorkbenchViewId =
  | 'ONBOARDING_MIC_CHECK'
  | 'EXERCISE_BRIEF_SPEC'
  | 'DOMAIN_SHIFT_ACK_GATE'
  | 'EXPLAIN_APPROACH_TURN'
  | 'PREDICT_CHALLENGE_OUTPUT'
  | 'TRANSCRIPT_CLAIM_CONFIRMATION'
  | 'ISOLATED_VERIFICATION_PROGRESS'
  | 'REVEALED_COMPARISON_VIEW'
  | 'TRACE_SCRUBBER_INSPECTION'
  | 'SOCRATIC_HINT_PROGRESSION'
  | 'FRESH_TRANSFER_CHALLENGE'
  | 'PRACTICE_CHECKPOINT_SUMMARY'
  | 'QUEUE_DEGRADATION_RECOVERY';

export const ALL_WORKBENCH_VIEWS: readonly WorkbenchViewId[] = [
  'ONBOARDING_MIC_CHECK',
  'EXERCISE_BRIEF_SPEC',
  'DOMAIN_SHIFT_ACK_GATE',
  'EXPLAIN_APPROACH_TURN',
  'PREDICT_CHALLENGE_OUTPUT',
  'TRANSCRIPT_CLAIM_CONFIRMATION',
  'ISOLATED_VERIFICATION_PROGRESS',
  'REVEALED_COMPARISON_VIEW',
  'TRACE_SCRUBBER_INSPECTION',
  'SOCRATIC_HINT_PROGRESSION',
  'FRESH_TRANSFER_CHALLENGE',
  'PRACTICE_CHECKPOINT_SUMMARY',
  'QUEUE_DEGRADATION_RECOVERY',
] as const;

export interface WorkbenchSessionState {
  readonly sessionId: string | null;
  readonly sessionToken: string | null;
  readonly exerciseId: ExerciseId;
  readonly specVersion: SpecVersion;
  readonly specAcknowledged: boolean;
  readonly languageMode: LanguageMode;
  readonly interactionMode: InteractionMode;
  readonly sessionState: SessionState;
  readonly learningState: LearningState;
  readonly revision: RevisionRef | null;
  readonly sourceCode: string;
  readonly persistedSourceCode: string;
  readonly editorDirty: boolean;
  readonly clientEditSequence: number;
  readonly saveInFlight: boolean;
  readonly astSymbols: string[];
  readonly syntaxError: string | null;
  readonly activeChallenge: Challenge | null;
  readonly activeTurnId: string | null;
  readonly turnGeneration: number;
  readonly captureAttemptId: number;
  readonly rawTranscript: string;
  readonly editableTranscript: string;
  readonly proposedClaim: ClaimInterpretation | null;
  readonly activeArtifact: EvidenceArtifact | null;
  readonly activeVerificationReport: { revision: RevisionRef; report: VerificationReport } | null;
  readonly priorFailureArtifactId: string | null;
  readonly diagnosticHidden: boolean;
  readonly activeTrace: TraceExecutionReport | null;
  readonly selectedTraceStepIndex: number;
  readonly currentHintLevel: HintLevel;
  readonly coachingHistory: Array<{
    hintLevel: number;
    displayText: string;
    pointedLine: number | null;
    pointedEventId: number | null;
    sourceMode: string;
    modelStatus?: string;
    stale: boolean;
  }>;
  readonly speechDegradation: SpeechDegradationStatus;
  readonly micChecked: boolean;
  readonly activeView: WorkbenchViewId;
  readonly diagnosticsOpen: boolean;
  readonly summaryModalOpen: boolean;
}

export function createInitialWorkbenchState(): WorkbenchSessionState {
  return {
    sessionId: null,
    sessionToken: null,
    exerciseId: 'ex1_shortest_subarray',
    specVersion: 'v1_positive_only',
    specAcknowledged: true,
    languageMode: 'en-IN',
    interactionMode: 'TYPED_FALLBACK',
    sessionState: 'READY',
    learningState: 'EXPLAINING',
    revision: null,
    sourceCode: '',
    persistedSourceCode: '',
    editorDirty: false,
    clientEditSequence: 0,
    saveInFlight: false,
    astSymbols: [],
    syntaxError: null,
    activeChallenge: null,
    activeTurnId: null,
    turnGeneration: 1,
    captureAttemptId: 0,
    rawTranscript: '',
    editableTranscript: '',
    proposedClaim: null,
    activeArtifact: null,
    activeVerificationReport: null,
    priorFailureArtifactId: null,
    diagnosticHidden: false,
    activeTrace: null,
    selectedTraceStepIndex: 0,
    currentHintLevel: 1,
    coachingHistory: [],
    speechDegradation: 'HEALTHY',
    micChecked: false,
    activeView: 'EXERCISE_BRIEF_SPEC',
    diagnosticsOpen: false,
    summaryModalOpen: false,
  };
}

/**
 * Map authoritative backend `SessionState`, `LearningState`, and degradation state
 * to the canonical 13 UI views.
 */
export function resolveActiveWorkbenchView(state: WorkbenchSessionState): WorkbenchViewId {
  if (state.speechDegradation !== 'HEALTHY' && state.activeView === 'QUEUE_DEGRADATION_RECOVERY') {
    return 'QUEUE_DEGRADATION_RECOVERY';
  }
  if (!state.specAcknowledged || state.sessionState === 'SPEC_ACK_REQUIRED') {
    return 'DOMAIN_SHIFT_ACK_GATE';
  }
  if (state.proposedClaim !== null) {
    return 'TRANSCRIPT_CLAIM_CONFIRMATION';
  }
  switch (state.learningState) {
    case 'EXPLAINING':
      return state.activeChallenge ? 'PREDICT_CHALLENGE_OUTPUT' : 'EXPLAIN_APPROACH_TURN';
    case 'AWAITING_PREDICTION':
      return 'PREDICT_CHALLENGE_OUTPUT';
    case 'VERIFYING':
      return 'ISOLATED_VERIFICATION_PROGRESS';
    case 'INSPECTING_RESULT':
    case 'PREDICTION_REVIEW':
      return 'REVEALED_COMPARISON_VIEW';
    case 'REPAIR_REQUIRED':
      return state.activeTrace && state.activeTrace.steps && state.activeTrace.steps.length > 0
        ? 'TRACE_SCRUBBER_INSPECTION'
        : 'SOCRATIC_HINT_PROGRESSION';
    case 'FRESH_CASE_CHECK':
    case 'FRESH_CASE_REVIEW':
      return 'FRESH_TRANSFER_CHALLENGE';
    case 'PRACTICE_CHECKPOINT_COMPLETED':
      return 'PRACTICE_CHECKPOINT_SUMMARY';
    default:
      return 'EXERCISE_BRIEF_SPEC';
  }
}

/**
 * Apply an editor buffer change: marks `editorDirty = true` immediately so any prior
 * counterexample, trace step pointer, or coaching feedback is visually marked stale (`SUPERSEDED`)
 * before the debounced CAS save completes (§5.5 / §7.3).
 */
export function applyEditorBufferChange(
  prev: WorkbenchSessionState,
  nextCode: string,
): WorkbenchSessionState {
  const dirty = nextCode !== prev.persistedSourceCode;
  return {
    ...prev,
    sourceCode: nextCode,
    editorDirty: dirty,
    clientEditSequence: prev.clientEditSequence + 1,
    coachingHistory: dirty
      ? prev.coachingHistory.map((item) => ({ ...item, stale: true }))
      : prev.coachingHistory,
  };
}

/**
 * Record a re-record capture attempt on the current challenge without incrementing `turnGeneration`.
 */
export function applyRerecordCaptureAttempt(
  prev: WorkbenchSessionState,
): WorkbenchSessionState {
  return {
    ...prev,
    captureAttemptId: prev.captureAttemptId + 1,
    rawTranscript: '',
    editableTranscript: '',
    proposedClaim: null,
  };
}
