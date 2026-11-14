import type { Challenge, ClaimInterpretation, EvidenceArtifact, HiddenEvidenceArtifactView, RevisionRef, TraceExecutionReport } from '../types/api';
import type { SessionSnapshot, ResultResponse, CoachingResponse } from '../services/apiClient';
import { parsePrediction } from '../catalog/prediction';
import { createInitialWorkbenchState, resolveActiveWorkbenchView, type WorkbenchSessionState } from './useSessionStore';

export function sameRevision(a: RevisionRef | null | undefined, b: RevisionRef | null | undefined): boolean {
  return !!a && !!b && a.session_id === b.session_id && a.exercise_id === b.exercise_id && a.spec_version === b.spec_version && a.code_version_id === b.code_version_id && a.code_hash === b.code_hash && a.turn_generation === b.turn_generation;
}
export function canPublishTurn(current: RevisionRef | null, response: RevisionRef, hasChallenge: boolean): boolean {
  if (sameRevision(current, response)) return true;
  return !!current && !hasChallenge && response.turn_generation === current.turn_generation + 1
    && sameRevision(current, { ...response, turn_generation: current.turn_generation });
}
/** Reconcile a failed voice allocation without restoring over the live learner draft. */
export function reconcileVoiceRetry(current: WorkbenchSessionState, snapshot: unknown): WorkbenchSessionState | null {
  if (!current.revision || current.editorDirty || current.saveInFlight || !snapshot || typeof snapshot !== 'object') return null;
  const data = snapshot as Record<string, unknown>;
  if (data.session_id !== current.sessionId || data.source_code !== current.persistedSourceCode || !data.revision || typeof data.revision !== 'object') return null;
  const observed = data.revision as Record<string, unknown>;
  const original = current.revision;
  if (!Number.isSafeInteger(observed.turn_generation) || (observed.turn_generation !== original.turn_generation && observed.turn_generation !== original.turn_generation + 1)) return null;
  const revision: RevisionRef = { ...original, turn_generation: observed.turn_generation as number };
  if (observed.session_id !== revision.session_id || observed.exercise_id !== revision.exercise_id || observed.spec_version !== revision.spec_version || observed.code_version_id !== revision.code_version_id || observed.code_hash !== revision.code_hash || !canPublishTurn(original, revision, !!current.activeChallenge)) return null;
  let activeTurnId: string | null = null;
  let captureAttemptId = 0;
  if (data.active_turn != null) {
    if (typeof data.active_turn !== 'object') return null;
    const turn = data.active_turn as Record<string, unknown>;
    if (turn.turn_generation !== revision.turn_generation || typeof turn.turn_id !== 'string' || !turn.turn_id || !Number.isSafeInteger(turn.capture_attempt_id) || (turn.capture_attempt_id as number) < 0) return null;
    activeTurnId = turn.state === 'CANCELLED' || turn.state === 'SUPERSEDED' ? null : turn.turn_id;
    captureAttemptId = turn.capture_attempt_id as number;
  }
  const advanced = revision.turn_generation !== original.turn_generation;
  return { ...current, revision, turnGeneration: revision.turn_generation, captureAttemptId, activeTurnId, proposedClaim: null,
    activeArtifact: advanced ? null : current.activeArtifact, activeVerificationReport: advanced ? null : current.activeVerificationReport,
    activeTrace: advanced ? null : current.activeTrace, activeView: 'EXPLAIN_APPROACH_TURN' };
}
export function coachingEntry(coaching: CoachingResponse, level = 1): WorkbenchSessionState['coachingHistory'][number] {
  return { hintLevel: coaching.hint_level ?? level, displayText: coaching.display_text ?? coaching.text ?? 'Coaching is unavailable. Inspect the observed execution outcome.', pointedLine: coaching.pointed_line ?? null, pointedEventId: coaching.pointed_event_id ?? null, sourceMode: coaching.source_mode ?? 'DETERMINISTIC', stale: false };
}
function currentHintLevel(coaching: CoachingResponse | null | undefined): WorkbenchSessionState['currentHintLevel'] {
  return coaching?.hint_level === 2 || coaching?.hint_level === 3 ? coaching.hint_level : 1;
}
function failureIdentity(artifact: EvidenceArtifact | HiddenEvidenceArtifactView | null): string | null {
  return artifact && 'verification_report' in artifact && artifact.verification_report.status === 'COUNTEREXAMPLE_CONFIRMED' ? artifact.artifact_id : null;
}
function revealedArtifact(artifact: EvidenceArtifact | HiddenEvidenceArtifactView | null, challenges: Challenge[]): EvidenceArtifact | null {
  if (!artifact || !('actual_observation' in artifact) || ('reveal_state' in artifact && artifact.reveal_state === 'HIDDEN')) return null;
  const challenge = challenges.find(item => item.challenge_id === artifact.challenge_id && sameRevision(item.revision, artifact.revision));
  // A repair-only result has no challenge. Full artifacts are themselves server-authorized;
  // an explicitly hidden challenge still takes precedence over any payload details.
  return challenge && challenge.reveal_state !== 'REVEALED' ? null : artifact;
}
function safeTrace(trace: TraceExecutionReport | null | undefined, revision: RevisionRef, hidden: boolean): TraceExecutionReport | null {
  return !hidden && sameRevision(trace?.revision, revision) ? trace ?? null : null;
}
export function restoreWorkbench(snapshot: SessionSnapshot, token: string): WorkbenchSessionState {
  const challenges = snapshot.challenges.filter(item => sameRevision(item.revision, snapshot.revision));
  const challenge = challenges.slice(-1)[0] ?? null;
  const candidate = snapshot.evidence_artifacts.filter(item => sameRevision(item.revision, snapshot.revision)).slice(-1)[0] ?? null;
  const artifact = revealedArtifact(candidate, challenges);
  const hidden = challenge?.reveal_state !== 'REVEALED' && challenge !== null;
  const turn = snapshot.active_turn?.turn_generation === snapshot.revision.turn_generation ? snapshot.active_turn : null;
  const pendingClaim = turn?.state === 'AWAITING_CLAIM_CONFIRMATION' || turn?.state === 'CLAIM_FALLBACK_EDIT' ? turn.proposed_claim : null;
  const report = snapshot.verification_report ?? artifact?.verification_report ?? null;
  const next: WorkbenchSessionState = { ...createInitialWorkbenchState(), sessionId: snapshot.session_id, sessionToken: token, revision: snapshot.revision, exerciseId: snapshot.revision.exercise_id, specVersion: snapshot.revision.spec_version, sessionState: snapshot.state, learningState: snapshot.learning_state, specAcknowledged: snapshot.spec_acknowledged, languageMode: snapshot.language_mode, interactionMode: snapshot.interaction_mode, sourceCode: snapshot.source_code, persistedSourceCode: snapshot.source_code, clientEditSequence: snapshot.latest_client_edit_sequence ?? 0, turnGeneration: turn?.turn_generation ?? snapshot.revision.turn_generation, activeTurnId: turn?.state === 'CANCELLED' || turn?.state === 'SUPERSEDED' ? null : turn?.turn_id ?? null, captureAttemptId: turn?.capture_attempt_id ?? 0, proposedClaim: pendingClaim, rawTranscript: turn?.transcript ?? '', editableTranscript: turn?.transcript ?? '', activeChallenge: challenge, activeArtifact: artifact, activeVerificationReport: report ? { revision: snapshot.revision, report } : null, priorFailureArtifactId: snapshot.prior_artifact_id ?? failureIdentity(candidate), diagnosticHidden: hidden, activeTrace: safeTrace(snapshot.trace_report, snapshot.revision, hidden), currentHintLevel: currentHintLevel(snapshot.coaching), coachingHistory: !hidden && snapshot.coaching ? [coachingEntry(snapshot.coaching)] : [] };
  return { ...next, activeView: resolveActiveWorkbenchView(next) };
}
export function applyServerResult(prev: WorkbenchSessionState, res: ResultResponse): WorkbenchSessionState {
  const challenge = res.diagnostic_challenge ?? res.challenge ?? (res.challenge === undefined ? prev.activeChallenge : null);
  const hidden = challenge !== null && challenge.reveal_state !== 'REVEALED';
  const artifact = revealedArtifact(res.artifact ?? null, challenge ? [challenge] : []);
  const newTurn = res.revision.turn_generation !== prev.turnGeneration;
  const report = res.verification_report ?? artifact?.verification_report ?? null;
  const next: WorkbenchSessionState = { ...prev, revision: res.revision, turnGeneration: res.revision.turn_generation, captureAttemptId: newTurn ? 0 : prev.captureAttemptId, activeTurnId: newTurn ? null : prev.activeTurnId, rawTranscript: newTurn ? '' : prev.rawTranscript, editableTranscript: newTurn ? '' : prev.editableTranscript, sessionState: res.session_state, learningState: res.learning_state, activeChallenge: challenge, activeArtifact: artifact, activeVerificationReport: report ? { revision: res.revision, report } : null, priorFailureArtifactId: failureIdentity(res.artifact ?? null) ?? prev.priorFailureArtifactId, diagnosticHidden: hidden, activeTrace: safeTrace(res.trace_report, res.revision, hidden), selectedTraceStepIndex: 0, proposedClaim: null, currentHintLevel: currentHintLevel(res.coaching), coachingHistory: !hidden && res.coaching ? [coachingEntry(res.coaching)] : [] };
  return { ...next, activeView: resolveActiveWorkbenchView(next) };
}
export function confirmedInterpretation(proposal: ClaimInterpretation, challenge: Challenge | null, predictedValue: string, reason: string): ClaimInterpretation {
  if (proposal.claim_type !== 'OUTPUT_PREDICTION_AND_REASON') {
    if (proposal.claim_type === 'UNSUPPORTED_CLAIM') throw new Error('This interpretation is unsupported. Edit or abstain without execution.');
    return { ...proposal, confirmed_at: new Date().toISOString() };
  }
  if (!challenge || proposal.challenge_id !== challenge.challenge_id) throw new Error('The proposal does not match this challenge. Propose your prediction again.');
  const predictedOutput = parsePrediction(predictedValue);
  return { ...proposal, predicted_output: predictedOutput, reason_summary: reason || proposal.reason_summary || null, extraction_method: 'USER_EDITED', confirmed_at: new Date().toISOString() };
}
