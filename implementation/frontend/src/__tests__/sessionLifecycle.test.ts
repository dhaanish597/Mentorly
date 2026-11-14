import { describe, expect, it } from 'vitest';
import { applyServerResult, confirmedInterpretation, sameRevision, restoreWorkbench, canPublishTurn, reconcileVoiceRetry } from '../state/sessionLifecycle';
import { createInitialWorkbenchState } from '../state/useSessionStore';
import type { SessionSnapshot } from '../services/apiClient';
import type { Challenge, ClaimInterpretation, EvidenceArtifact, RevisionRef } from '../types/api';
const revision: RevisionRef = { session_id: 's', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 1, code_hash: 'h', turn_generation: 1 };
const challenge: Challenge = { challenge_id: 'c', revision, input_args: {}, case_hash: 'h', purpose: 'DIAGNOSTIC', reveal_state: 'HIDDEN', created_at: '', expires_at: '' };
const artifact: EvidenceArtifact = { artifact_id: 'a', revision, challenge_id: 'c', canonical_input: {}, case_hash: 'h', actual_observation: { kind: 'RETURN', return_value: 1, duration_ms: 1 }, reference_output: 1, prediction_status: 'MATCH', verification_report: { status: 'COUNTEREXAMPLE_CONFIRMED', curated_cases_run: 1, curated_cases_total: 1, generated_cases_run: 0, generated_cases_target: 0, terminal_reason: 'failure', runtime_version: 'v' } };
const snapshot: SessionSnapshot = { session_id: 's', state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'TYPED_FALLBACK', source_code: '', revision, challenges: [], evidence_artifacts: [] };

describe('Full revision and proposal authority', () => {
  it('accepts one server-owned explanation turn advance but no source or challenge drift', () => {
    const advanced = { ...revision, turn_generation: revision.turn_generation + 1 };
    expect(canPublishTurn(revision, advanced, false)).toBe(true);
    expect(canPublishTurn(revision, advanced, true)).toBe(false);
    expect(canPublishTurn(revision, { ...advanced, code_hash: 'different' }, false)).toBe(false);
    expect(canPublishTurn(revision, { ...advanced, turn_generation: 9 }, false)).toBe(false);
    expect(canPublishTurn(revision, { ...revision, turn_generation: 0 }, false)).toBe(false);
  });
  it('reconciles failed audio allocation without overwriting the learner transcript', () => {
    const current = { ...createInitialWorkbenchState(), sessionId: 's', revision, editableTranscript: 'Keep my reasoning', activeArtifact: artifact };
    const advanced = { ...snapshot, revision: { ...revision, turn_generation: 2 }, active_turn: { state: 'TRANSCRIBING_AND_PARSING' as const, turn_id: 'retry', turn_generation: 2, capture_attempt_id: 3, proposed_claim: null } };
    const next = reconcileVoiceRetry(current, advanced);
    expect(next).toMatchObject({ revision: advanced.revision, turnGeneration: 2, captureAttemptId: 3, activeTurnId: 'retry', editableTranscript: 'Keep my reasoning', proposedClaim: null, activeArtifact: null });
    expect(current.revision).toBe(revision);
  });
  it('rejects unsafe voice retry reconciliation instead of rebinding audio to other code', () => {
    const current = { ...createInitialWorkbenchState(), sessionId: 's', revision };
    for (const invalid of [null, {}, { ...snapshot, session_id: 'other' }, { ...snapshot, revision: { ...revision, code_hash: 'different' } }, { ...snapshot, revision: { ...revision, turn_generation: 0 } }, { ...snapshot, revision: { ...revision, turn_generation: 3 } }, { ...snapshot, active_turn: { turn_id: 'bad', turn_generation: 1, capture_attempt_id: -1 } }]) {
      expect(reconcileVoiceRetry(current, invalid)).toBeNull();
    }
    expect(reconcileVoiceRetry({ ...current, editorDirty: true }, snapshot)).toBeNull();
    expect(reconcileVoiceRetry({ ...current, saveInFlight: true }, snapshot)).toBeNull();
  });
  it('keeps the hidden challenge guard during audio retry reconciliation', () => {
    const current = { ...createInitialWorkbenchState(), sessionId: 's', revision, activeChallenge: challenge };
    expect(reconcileVoiceRetry(current, { ...snapshot, revision: { ...revision, turn_generation: 2 } })).toBeNull();
    expect(reconcileVoiceRetry(current, snapshot)?.revision).toEqual(revision);
  });
  it('matches every revision field, not only version or history position', () => {
    expect(sameRevision(revision, { ...revision })).toBe(true);
    expect(sameRevision(null, revision)).toBe(false);
    for (const [key, value] of Object.entries(revision)) expect(sameRevision(revision, { ...revision, [key]: typeof value === 'number' ? value + 1 : `${value}-different` })).toBe(false);
  });
  it.each<ClaimInterpretation>([
    { claim_type: 'INVARIANT_OR_MECHANISM_CLAIM', mechanism_summary: 'window grows', extraction_method: 'DETERMINISTIC' },
    { claim_type: 'DOMAIN_VALIDITY_CLAIM', target_spec_version: 'v2_negatives_allowed', polarity: 'NEGATIVE', extraction_method: 'DETERMINISTIC' },
    { claim_type: 'CLARIFICATION_OR_HINT_REQUEST', question_text: 'What about negatives?', extraction_method: 'DETERMINISTIC' },
  ])('retains $claim_type instead of manufacturing a numeric claim', proposal => {
    const claim = confirmedInterpretation(proposal, null, '17', 'ignored');
    expect(claim).toMatchObject(proposal);
    expect(claim.claim_type).toBe(proposal.claim_type);
    expect(claim).not.toHaveProperty('predicted_output');
    expect(proposal.confirmed_at).toBeUndefined();
  });
  it('validates exact integer and matching challenge before execution', () => {
    const proposal: ClaimInterpretation = { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: 'c', predicted_output: 3, reason_summary: 'count', extraction_method: 'DETERMINISTIC' };
    expect(() => confirmedInterpretation(proposal, { ...challenge, challenge_id: 'other' }, '3', '')).toThrow(/does not match/);
    expect(() => confirmedInterpretation(proposal, null, '3', '')).toThrow(/does not match/);
    for (const value of ['1.2', '1e4', '9007199254740992', '']) expect(() => confirmedInterpretation(proposal, challenge, value, '')).toThrow(/exact integer/);
    expect(confirmedInterpretation(proposal, challenge, '-4', 'revised')).toMatchObject({ claim_type: proposal.claim_type, predicted_output: -4, reason_summary: 'revised', extraction_method: 'USER_EDITED' });
    expect(confirmedInterpretation(proposal, challenge, '3', '')).toMatchObject({ reason_summary: 'count' });
  });
  it('requires revision of unsupported interpretation or abstention', () => {
    expect(() => confirmedInterpretation({ claim_type: 'UNSUPPORTED_CLAIM', raw_summary: 'unclear', extraction_method: 'DETERMINISTIC' }, challenge, '3', '')).toThrow(/unsupported/);
  });
  it('rejects privileged artifact/trace when the server still marks its challenge hidden', () => {
    const restored = restoreWorkbench({ ...snapshot, challenges: [challenge], evidence_artifacts: [artifact], trace_report: { trace_id: 't', revision, case_hash: 'h', status: 'COMPLETED', total_observed: 0, termination_reason: '', runtime_version: 'v' }, coaching: { text: 'hidden hint' } }, 'token');
    expect(restored.activeArtifact).toBeNull();
    expect(restored.activeTrace).toBeNull();
    expect(restored.coachingHistory).toEqual([]);
    expect(restored.priorFailureArtifactId).toBe('a');
  });
  it('restores only prior failure identity after save without stale evidence', () => {
    const restored = restoreWorkbench({ ...snapshot, prior_artifact_id: 'prior-failure', evidence_artifacts: [{ ...artifact, revision: { ...revision, code_version_id: 0 } }] }, 'token');
    expect(restored.priorFailureArtifactId).toBe('prior-failure');
    expect(restored.activeArtifact).toBeNull();
  });
  it('accepts hidden evidence views without reading nonexistent privileged fields', () => {
    const hidden = { artifact_id: 'hidden', revision, challenge_id: 'c', canonical_input: {}, case_hash: 'h', reveal_state: 'HIDDEN' as const };
    expect(restoreWorkbench({ ...snapshot, evidence_artifacts: [hidden] }, 'token').activeArtifact).toBeNull();
  });
  it('resets capture identity when the server advances to a new diagnostic turn', () => {
    const prev = { ...createInitialWorkbenchState(), revision, activeTurnId: 'previous-turn', captureAttemptId: 9, editableTranscript: 'old prediction' };
    const nextRevision = { ...revision, turn_generation: 2 };
    const next = applyServerResult(prev, { revision: nextRevision, session_state: 'READY', learning_state: 'AWAITING_PREDICTION', diagnostic_challenge: { ...challenge, revision: nextRevision } });
    expect(next.captureAttemptId).toBe(0);
    expect(next.activeTurnId).toBeNull();
    expect(next.editableTranscript).toBe('');
  });
  it('uses only authoritative returned reveal state and allows artifact-less explanation', () => {
    const prev = { ...createInitialWorkbenchState(), revision, activeChallenge: challenge };
    const base = { session_state: 'READY' as const, learning_state: 'EXPLAINING' as const, revision };
    expect(applyServerResult(prev, { ...base, artifact }).activeArtifact).toBeNull();
    const revealed = applyServerResult(prev, { ...base, challenge: { ...challenge, reveal_state: 'REVEALED' }, artifact, coaching: { text: 'hint', hint_level: 2 } });
    expect(revealed.activeArtifact).toEqual(artifact);
    expect(revealed.coachingHistory[0].hintLevel).toBe(2);
    expect(revealed.currentHintLevel).toBe(2);
    expect(applyServerResult(prev, { ...base, challenge: null, executed: false }).activeArtifact).toBeNull();
    expect(applyServerResult(prev, { ...base, challenge: null, artifact }).activeArtifact).toEqual(artifact);
  });
});
