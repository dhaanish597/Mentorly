import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/apiClient';
import { AudioPlayer } from '../services/audioPlayer';
import { AudioRecorder } from '../services/audioRecorder';
import type { Challenge, EvidenceArtifact, RevisionRef, TraceExecutionReport } from '../types/api';
vi.mock('../components/PythonEditor', () => ({ PythonEditor: ({ value, onChange }: { value: string; onChange: (s: string) => void }) => <textarea aria-label="Python Solution Editor" value={value} onChange={e => onChange(e.target.value)} /> }));
import App from '../App';

const revision: RevisionRef = { session_id: 'session-1', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 1, code_hash: 'c'.repeat(64), turn_generation: 1 };
const challenge: Challenge = { challenge_id: 'challenge-1', revision, input_args: { nums: [1, 2], target: 2 }, case_hash: 'case-1', purpose: 'DIAGNOSTIC', reveal_state: 'REVEALED', created_at: '', expires_at: '' };
const artifact: EvidenceArtifact = { artifact_id: 'failure-1', revision, challenge_id: challenge.challenge_id, canonical_input: challenge.input_args, case_hash: challenge.case_hash, confirmed_prediction: 23, actual_observation: { kind: 'RETURN', return_value: 23, duration_ms: 1 }, reference_output: 1, prediction_status: 'MATCH', minimization_status: 'SHRINK_COMPLETED', verification_report: { status: 'COUNTEREXAMPLE_CONFIRMED', curated_cases_run: 2, curated_cases_total: 10, generated_cases_run: 3, generated_cases_target: 20, completed_stages: ['prior_failure', 'curated'], terminal_reason: 'confirmed_mismatch', runtime_version: 'test', counterexample_case_hash: 'failure-case', counterexample_input: { nums: [9], target: 9 }, reference_output: 9917, student_observation: { kind: 'RETURN', return_value: 7713, duration_ms: 1 } } };
const trace: TraceExecutionReport = { trace_id: 'trace-1', revision, case_hash: 'case-1', status: 'COMPLETED', total_observed: 2, termination_reason: 'complete', runtime_version: 'test', steps: [0, 1].map(index => ({ event_id: index + 10, frame_id: 'frame', call_depth: 0, source_hash: revision.code_hash, source_line: index + 1, event_kind: 'LINE', attribution_status: 'ATTRIBUTED', locals_snapshot: { index } })) };
const snapshot = { session_id: revision.session_id, state: 'READY' as const, learning_state: 'REPAIR_REQUIRED' as const, spec_acknowledged: true, language_mode: 'en-IN' as const, interaction_mode: 'TYPED_FALLBACK' as const, source_code: 'def f(): return 23', revision, challenges: [challenge], evidence_artifacts: [artifact], trace_report: trace, coaching: { display_text: 'Inspect this transition.', hint_level: 1, pointed_event_id: 11 }, active_turn: { state: 'AWAITING_CLAIM_CONFIRMATION' as const, turn_id: 'turn-1', proposed_claim: null, capture_attempt_id: 4, turn_generation: 1, transcript: '' } };
function result(overrides: Partial<api.ResultResponse> = {}): api.ResultResponse { return { session_state: 'READY', learning_state: 'REPAIR_REQUIRED', revision, artifact, challenge, trace_report: trace, coaching: null, ...overrides }; }
async function restore(overrides = {}): Promise<void> {
  vi.spyOn(api, 'restoreSession').mockResolvedValue({ ...snapshot, ...overrides });
  sessionStorage.setItem('vcc-session', JSON.stringify({ id: revision.session_id, token: 'token' }));
  render(<App />);
  await screen.findByRole('textbox', { name: 'Python Solution Editor' });
  const transcript = screen.queryByRole('button', { name: 'Transcript & text' });
  if (transcript) fireEvent.click(transcript);
  const tools = screen.getByText('Challenge & practice tools');
  if (!tools.closest('details')?.open) fireEvent.click(tools);
}
beforeEach(() => {
  localStorage.clear(); history.replaceState(null, '', '/');
  localStorage.setItem('vcc-product-v1', JSON.stringify({ inputChoice: 'voice' }));
  vi.spyOn(api.apiClient, 'getHealth').mockResolvedValue({ status: 'ok', service: 'test', phase: 'test', version: 'test', custom_code_execution_enabled: false, product_name: 'Coach', product_name_status: 'TEST' });
  vi.spyOn(api.apiClient, 'getBranding').mockResolvedValue({ productName: 'Coach', shortName: 'C', tagline: 'Practice', productNameStatus: 'TEST' });
  vi.spyOn(api.apiClient, 'getExercises').mockResolvedValue([]);
  vi.spyOn(api.apiClient, 'getDemoPresets').mockResolvedValue([]);
  vi.spyOn(api, 'cancelSessionWork').mockResolvedValue({});
});
afterEach(() => { cleanup(); sessionStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('Reviewer lifecycle regressions', () => {
  it('keeps hidden standalone verifier output and oracle privileged even if present in payload', async () => {
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], trace_report: null, coaching: null, verification_report: artifact.verification_report });
    const comparison = screen.getByRole('region', { name: 'Execution & Prediction Comparison' });
    expect(comparison).toHaveTextContent('COUNTEREXAMPLE_CONFIRMED');
    expect(comparison).not.toHaveTextContent('9917');
    expect(comparison).not.toHaveTextContent('7713');
    expect(screen.queryByText(/Failing input:/)).not.toBeInTheDocument();
  });
  it('rejects a duplicate turn generation that disagrees with the revision', async () => {
    vi.spyOn(api, 'submitTextTurn').mockResolvedValue({ turn_id: 'bad-generation', revision, turn_generation: 99, capture_attempt_id: 1, proposed_claim: { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: 'challenge-1', predicted_output: 23, extraction_method: 'DETERMINISTIC' } });
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], active_turn: null });
    fireEvent.change(screen.getByRole('textbox', { name: 'Editable Learner Transcript' }), { target: { value: '23' } });
    fireEvent.click(screen.getByRole('button', { name: 'Propose Transcript Interpretation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Turn generation disagrees with its revision');
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Submit prediction & run' })).not.toBeInTheDocument();
  });
  it('does not retry stale terminal cancellation after an edit invalidates the pending mutation', async () => {
    let finish!: (value: Record<string, unknown>) => void;
    vi.spyOn(api, 'submitTextTurn').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], active_turn: null });
    fireEvent.change(screen.getByRole('textbox', { name: 'Editable Learner Transcript' }), { target: { value: '23' } });
    fireEvent.click(screen.getByRole('button', { name: 'Propose Transcript Interpretation' }));
    await waitFor(() => expect(api.submitTextTurn).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel / Stop Audio' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'new repair invalidates pending cancel' } });
    await act(async () => finish({ turn_id: 'late-cancelled', revision, capture_attempt_id: 1, proposed_claim: { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: 'challenge-1', predicted_output: 23, extraction_method: 'DETERMINISTIC' } }));
    expect(vi.mocked(api.cancelSessionWork).mock.calls.every(([, request]) => request.scope === 'INTERRUPT')).toBe(true);
    expect(api.restoreSession).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('new repair invalidates pending cancel');
  });
  it('renders verify-only report without an artifact and suppresses it after editing', async () => {
    const report = { ...artifact.verification_report, status: 'NO_FAILURE_FOUND' as const, terminal_reason: 'bounded_checks_completed' };
    vi.spyOn(api, 'verifyRepair').mockResolvedValue(result({ artifact: null, challenge: null, trace_report: null, verification_report: report, learning_state: 'FRESH_CASE_CHECK' }));
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Verify Saved Repair' }));
    await waitFor(() => expect(screen.getByTestId('verification-status-badge')).toHaveTextContent('NO_FAILURE_FOUND'));
    expect(screen.getByText(/bounded_checks_completed/)).toBeInTheDocument();
    expect(screen.getByText(/Curated cases: 2 \/ 10/)).toBeInTheDocument();
    expect(screen.queryByText('Reference Oracle:')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'edited after verify' } });
    expect(screen.queryByTestId('verification-status-badge')).not.toBeInTheDocument();
  });
  it('restores a standalone verification report without fabricating execution evidence', async () => {
    await restore({ challenges: [], evidence_artifacts: [], trace_report: null, coaching: null, verification_report: { ...artifact.verification_report, status: 'VERIFICATION_INCOMPLETE', terminal_reason: 'verification_budget_exhausted' } });
    expect(screen.getByTestId('verification-status-badge')).toHaveTextContent('VERIFICATION_INCOMPLETE');
    expect(screen.getByText(/verification_budget_exhausted/)).toBeInTheDocument();
    expect(screen.queryByText('Your Code Output:')).not.toBeInTheDocument();
  });
  it('does not restore a completed confirmed claim as pending but preserves retry identity', async () => {
    const proposed = { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: challenge.challenge_id, predicted_output: 23, extraction_method: 'DETERMINISTIC', confirmed_at: '2026-11-14T00:00:00Z' };
    const retry = vi.spyOn(api, 'retryExecution').mockResolvedValue(result());
    await restore({ active_turn: { state: 'COACH_PROMPT_DELIVERED', turn_id: 'completed-turn', turn_generation: 1, capture_attempt_id: 4, proposed_claim: proposed }, evidence_artifacts: [{ ...artifact, verification_report: { ...artifact.verification_report, status: 'EXECUTION_UNAVAILABLE' } }] });
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Submit prediction & run' })).not.toBeInTheDocument();
    expect(screen.queryByText('Interpretation:')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry Unavailable Execution' }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith('session-1', 'completed-turn', { revision }));
  });
  it.each(['direct', 'text-only'])('retries retained audio after %s with the authoritative revision without replacing learner speech', async mode => {
    let recording = false;
    const wavBytes = new Uint8Array(100).fill(12);
    vi.spyOn(AudioRecorder.prototype, 'isRecording', 'get').mockImplementation(() => recording);
    vi.spyOn(AudioRecorder.prototype, 'capturedSamplesCount', 'get').mockReturnValue(28);
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(async () => { recording = true; return { turnGeneration: 1, captureAttemptId: 1 }; });
    const drain = vi.spyOn(AudioRecorder.prototype, 'drainMicrophoneCapture').mockReturnValue({ sessionId: 'session-1', turnGeneration: 1, captureAttemptId: 1, wavBytes, sampleRateHz: 16000, durationSec: 1, rmsNormalized: 0.2, peakNormalized: 0.4, lowEnergyWarning: false, clippedSamples: 0 });
    const dispose = vi.spyOn(AudioRecorder.prototype, 'dispose').mockResolvedValue();
    const nextRevision = { ...revision, turn_generation: 2 };
    const upload = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ code: 'SPEECH_BUSY', message: 'Speech service is busy.', retryable: true }), { status: 503 }));
    upload.mockImplementationOnce(() => new Promise<Response>(() => undefined));
    vi.stubGlobal('fetch', upload);
    await restore({ challenges: [], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: { ...snapshot.active_turn, transcript: 'My earlier reasoning' } });
    vi.mocked(api.restoreSession).mockResolvedValue({ ...snapshot, revision: nextRevision, challenges: [], evidence_artifacts: [], active_turn: { state: 'TRANSCRIBING_AND_PARSING', turn_id: 'retry-turn', proposed_claim: null, capture_attempt_id: 1, turn_generation: 2 } });
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    await screen.findByRole('button', { name: 'Done speaking' });
    dispose.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Done speaking' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Speech service is busy');
    expect(screen.getByRole('textbox', { name: 'Editable Learner Transcript' })).toHaveValue('My earlier reasoning');
    if (mode === 'text-only') {
      fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
      fireEvent.click(screen.getByRole('checkbox', { name: /Text-only mode/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
      dispose.mockClear();
    }
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    const first = upload.mock.calls[0][1] as RequestInit;
    const second = upload.mock.calls[1][1] as RequestInit;
    expect((second.body as FormData).get('revision')).toBe(JSON.stringify(nextRevision));
    expect((second.body as FormData).get('audio')).toEqual((first.body as FormData).get('audio'));
    expect(drain).toHaveBeenCalledTimes(1);
    expect(dispose).not.toHaveBeenCalled();
    expect(api.restoreSession).toHaveBeenCalledTimes(2);
  });
  it('releases voice upload ownership when unmuting replaces an aborted upload with TTS', async () => {
    let recording = false;
    vi.spyOn(AudioRecorder.prototype, 'isRecording', 'get').mockImplementation(() => recording);
    vi.spyOn(AudioRecorder.prototype, 'capturedSamplesCount', 'get').mockReturnValue(28);
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(async () => { recording = true; return { turnGeneration: 1, captureAttemptId: 1 }; });
    vi.spyOn(AudioRecorder.prototype, 'drainMicrophoneCapture').mockReturnValue({ sessionId: 'session-1', turnGeneration: 1, captureAttemptId: 1, wavBytes: new Uint8Array(100).fill(12), sampleRateHz: 16000, durationSec: 1, rmsNormalized: 0.2, peakNormalized: 0.4, lowEnergyWarning: false, clippedSamples: 0 });
    vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: new ArrayBuffer(4), playbackId: 'intro' });
    vi.spyOn(AudioPlayer.prototype, 'playWavBytes').mockResolvedValue({ started: true, fallbackAck: null });
    const upload = vi.fn().mockImplementationOnce((_url, init: RequestInit) => new Promise<Response>((_resolve, reject) => init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))));
    upload.mockImplementationOnce(() => new Promise<Response>(() => undefined));
    vi.stubGlobal('fetch', upload);
    await restore({ challenges: [], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: null });
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Done speaking' }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Mute voice' }));
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Unmute voice' })));
    expect((upload.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Done speaking' }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
  });
  it('uses revision generation for real WebSocket proposals with no duplicate generation', async () => {
    const sockets: Socket[] = [];
    class Socket extends EventTarget {
      static OPEN = 1; readyState = 1; bufferedAmount = 0; send = vi.fn();
      constructor() { super(); sockets.push(this); }
      close(): void { this.readyState = 3; this.dispatchEvent(new Event('close')); }
    }
    vi.stubGlobal('WebSocket', Socket);
    let isRecording = false;
    vi.spyOn(AudioRecorder.prototype, 'isRecording', 'get').mockImplementation(() => isRecording);
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(async () => { isRecording = true; return { turnGeneration: 1, captureAttemptId: 1 }; });
    vi.spyOn(AudioRecorder.prototype, 'stopMicrophoneCapture').mockImplementation(async () => { isRecording = false; return {} as Awaited<ReturnType<AudioRecorder['stopMicrophoneCapture']>>; });
    const confirm = vi.spyOn(api, 'confirmTurnClaim').mockResolvedValue({ ...result() });
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: null });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Recognition transport' }), { target: { value: 'WS' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    await waitFor(() => expect(sockets).toHaveLength(1));
    await act(async () => sockets[0].dispatchEvent(new Event('open')));
    fireEvent.click(await screen.findByRole('button', { name: /^(Send voice|Done speaking)$/ }));
    await act(async () => sockets[0].dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type: 'proposal', turn_id: 'ws-turn', revision, capture_attempt_id: 1, proposed_claim: { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: 'challenge-1', predicted_output: 23, extraction_method: 'DETERMINISTIC' } }) })));
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    expect(screen.getByText(/Turn #1 \/ Attempt #1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Submit prediction & run' }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith('session-1', 'ws-turn', expect.objectContaining({ revision, capture_attempt_id: 1 })));
  });
  it('serializes terminal TURN cancel after pending text mutation and restores authoritative state', async () => {
    let finish!: (value: Record<string, unknown>) => void;
    vi.spyOn(api, 'submitTextTurn').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], active_turn: null });
    vi.mocked(api.restoreSession).mockResolvedValue({ ...snapshot, learning_state: 'FRESH_CASE_CHECK', active_turn: { state: 'CANCELLED', turn_id: 'pending-turn', proposed_claim: null, capture_attempt_id: 1, turn_generation: 1 }, challenges: [{ ...challenge, reveal_state: 'HIDDEN' }] });
    fireEvent.change(screen.getByRole('textbox', { name: 'Editable Learner Transcript' }), { target: { value: '23' } });
    fireEvent.click(screen.getByRole('button', { name: 'Propose Transcript Interpretation' }));
    await waitFor(() => expect(api.submitTextTurn).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel / Stop Audio' }));
    expect(api.cancelSessionWork).not.toHaveBeenCalled();
    await act(async () => finish({ turn_id: 'pending-turn', revision, capture_attempt_id: 1, proposed_claim: { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: 'challenge-1', predicted_output: 23, extraction_method: 'DETERMINISTIC' } }));
    await waitFor(() => expect(api.cancelSessionWork).toHaveBeenCalledWith('session-1', expect.objectContaining({ scope: 'TURN', turn_id: 'pending-turn' })));
    await waitFor(() => expect(screen.queryByTestId('challenge-input-json')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Load Held-Out Transfer Case' })).toBeEnabled();
  });
  it('stops playback without cancelling capture or replacing authoritative learning state', async () => {
    vi.spyOn(AudioRecorder.prototype, 'isRecording', 'get').mockReturnValue(true);
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockResolvedValue({ turnGeneration: 1, captureAttemptId: 1 });
    const dispose = vi.spyOn(AudioRecorder.prototype, 'dispose').mockResolvedValue();
    const stopCapture = vi.spyOn(AudioRecorder.prototype, 'stopMicrophoneCapture');
    const drain = vi.spyOn(AudioRecorder.prototype, 'drainMicrophoneCapture');
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    await screen.findByRole('button', { name: /^(Send voice|Done speaking)$/ });
    dispose.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stop audio' }));
    expect(vi.mocked(api.cancelSessionWork).mock.calls.every(([, request]) => request.scope === 'INTERRUPT')).toBe(true);
    expect(dispose).not.toHaveBeenCalled();
    expect(stopCapture).not.toHaveBeenCalled();
    expect(drain).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    expect(screen.getByRole('button', { name: /^(Send voice|Done speaking)$/ })).toBeEnabled();
    expect(api.restoreSession).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('verification-status-badge')).toHaveTextContent('COUNTEREXAMPLE_CONFIRMED');
  });
  it('explicit cancel clears active capture and reconciles authoritative turn state', async () => {
    let recording = false;
    vi.spyOn(AudioRecorder.prototype, 'isRecording', 'get').mockImplementation(() => recording);
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(async () => {
      recording = true;
      return { turnGeneration: 1, captureAttemptId: 1 };
    });
    const dispose = vi.spyOn(AudioRecorder.prototype, 'dispose').mockImplementation(async () => { recording = false; });
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    await screen.findByRole('button', { name: /^(Send voice|Done speaking)$/ });
    dispose.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel / Stop Audio' }));
    await waitFor(() => expect(api.cancelSessionWork).toHaveBeenCalledWith('session-1', expect.objectContaining({ scope: 'TURN', turn_id: 'turn-1' })));
    await waitFor(() => expect(api.restoreSession).toHaveBeenCalledTimes(2));
    expect(dispose).toHaveBeenCalled();
    expect(recording).toBe(false);
    expect(screen.queryByRole('button', { name: /^(Send voice|Done speaking)$/ })).not.toBeInTheDocument();
  });
  it('metadata retry never restores over an already dirty buffer', async () => {
    vi.spyOn(api, 'verifyRepair').mockRejectedValue(new Error('Temporary verifier error'));
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Verify Saved Repair' }));
    await screen.findByRole('alert');
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'must retain this repair' } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('must retain this repair'));
    expect(api.restoreSession).toHaveBeenCalledTimes(1);
  });
});

describe('Immediate speech interruption', () => {
  it('keeps verification authoritative when muting audio while its response is pending', async () => {
    let finish!: (value: api.ResultResponse) => void;
    vi.spyOn(api, 'verifyRepair').mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Verify Saved Repair' }));
    await waitFor(() => expect(api.verifyRepair).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mute voice playback' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    await act(async () => finish(result({ artifact: null, challenge: null, trace_report: null, learning_state: 'FRESH_CASE_CHECK', verification_report: { ...artifact.verification_report, status: 'NO_FAILURE_FOUND' } })));
    expect(screen.getByTestId('verification-status-badge')).toHaveTextContent('NO_FAILURE_FOUND');
  });
  it('keeps speech stop enabled during a pending playback request', async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise(resolve => { finish = resolve; })));
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Play Coach Voice' }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    expect(screen.getByRole('button', { name: 'Stop audio' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Stop audio' }));
    expect((vi.mocked(fetch).mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
    await act(async () => finish(new Response(new Uint8Array([0, 1]), { status: 200 })));
  });
  it('closes pending WebSocket capture and never sends auth after cancellation', async () => {
    const sockets: FakeSocket[] = [];
    class FakeSocket extends EventTarget {
      static OPEN = 1;
      readyState = 0;
      bufferedAmount = 0;
      send = vi.fn();
      constructor() { super(); sockets.push(this); }
      close(): void { this.readyState = 3; this.dispatchEvent(new Event('close')); }
    }
    vi.stubGlobal('WebSocket', FakeSocket);
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: null });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Recognition transport' }), { target: { value: 'WS' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    await waitFor(() => expect(sockets).toHaveLength(1));
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'edit' } });
    expect(sockets[0].readyState).toBe(3);
    await act(async () => sockets[0].dispatchEvent(new Event('open')));
    expect(sockets[0].send).not.toHaveBeenCalled();
  });
  it('aborts an in-flight playback response and ignores late WAV data after editing', async () => {
    let resolveResponse!: (response: Response) => void;
    const fetch = vi.fn().mockImplementation(() => new Promise<Response>(resolve => { resolveResponse = resolve; }));
    vi.stubGlobal('fetch', fetch);
    const wav = vi.spyOn(AudioPlayer.prototype, 'playWavBytes').mockResolvedValue({ started: true, fallbackAck: null });
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Playback' }), { target: { value: 'WAV' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Play Coach Voice' }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const signal = (fetch.mock.calls[0][1] as RequestInit).signal!;
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'edit' } });
    expect(signal.aborted).toBe(true);
    await act(async () => resolveResponse(new Response(new Uint8Array([0, 1]), { status: 200 })));
    expect(wav).not.toHaveBeenCalled();
  });
  it('disposes microphone when permission completes after an edit', async () => {
    let resolveCapture!: (meta: { turnGeneration: number; captureAttemptId: number }) => void;
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(() => new Promise(resolve => { resolveCapture = resolve; }));
    const dispose = vi.spyOn(AudioRecorder.prototype, 'dispose').mockResolvedValue();
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: null });
    fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
    await waitFor(() => expect(AudioRecorder.prototype.startMicrophoneCapture).toHaveBeenCalled());
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'edit' } });
    await act(async () => resolveCapture({ turnGeneration: 1, captureAttemptId: 1 }));
    expect(dispose).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /^(Send voice|Done speaking)$/ })).not.toBeInTheDocument();
  });
});

describe('Revision-bound learning lifecycle', () => {
  it('reports blocked execution without implying a runtime was accepted', async () => {
    const blocked = { status: 'ok' as const, service: 'test', phase: 'test', version: 'test', custom_code_execution_enabled: false, product_name: 'Coach', product_name_status: 'TEST', execution_status: 'BLOCKED_EXTERNAL' as const };
    vi.mocked(api.apiClient.getHealth).mockResolvedValue(blocked);
    await restore();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    expect(screen.getByTestId('phase-status-banner')).toHaveTextContent('Execution blocked by external isolation readiness');
    expect(screen.getByTestId('phase-status-banner')).not.toHaveTextContent('Accepted isolated runtime');
  });
  it('restores only full-revision challenge/evidence and active trace pointer', async () => {
    const staleRevision = { ...revision, code_hash: 'stale', turn_generation: 9 };
    await restore({ challenges: [challenge, { ...challenge, revision: staleRevision, input_args: { secret: 'STALE_INPUT' } }], evidence_artifacts: [artifact, { ...artifact, revision: staleRevision, reference_output: 55555 }] });
    expect(screen.getByTestId('challenge-input-json')).not.toHaveTextContent('STALE_INPUT');
    expect(screen.getByText('Reference Oracle:').parentElement).not.toHaveTextContent('55555');
    expect(screen.getByRole('button', { name: /Inspect trace event 11/i })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: /Inspect trace event 11/i }));
    expect(screen.getByTestId('trace-step-details')).toHaveTextContent('Event #11');
  });
  it('confirms the matching output proposal with its capture identity and uses server reveal', async () => {
    const proposal = { claim_type: 'OUTPUT_PREDICTION_AND_REASON' as const, challenge_id: challenge.challenge_id, predicted_output: 23, extraction_method: 'DETERMINISTIC' as const };
    const confirm = vi.spyOn(api, 'confirmTurnClaim').mockResolvedValue({ ...result() });
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: { state: 'AWAITING_CLAIM_CONFIRMATION' as const, turn_id: 'output-turn', proposed_claim: proposal, capture_attempt_id: 9, turn_generation: 1, transcript: 'It returns 23' } });
    expect(screen.queryByTestId('verification-status-badge')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Submit prediction & run' }));
    await waitFor(() => expect(screen.getByTestId('challenge-reveal-badge')).toHaveTextContent('REVEALED'));
    expect(confirm).toHaveBeenCalledWith('session-1', 'output-turn', expect.objectContaining({ challenge_id: 'challenge-1', capture_attempt_id: 9, claim: expect.objectContaining({ claim_type: 'OUTPUT_PREDICTION_AND_REASON', predicted_output: 23 }) }));
    expect(screen.getByTestId('verification-status-badge')).toHaveTextContent('COUNTEREXAMPLE_CONFIRMED');
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
  });
  it('restores explanation without inventing an integer claim or auto-confirming it', async () => {
    const claim = { claim_type: 'INVARIANT_OR_MECHANISM_CLAIM' as const, mechanism_summary: 'The window only grows', extraction_method: 'DETERMINISTIC' as const };
    const confirm = vi.spyOn(api, 'confirmTurnClaim').mockResolvedValue({ ...result({ artifact: null, challenge: null, trace_report: null, learning_state: 'EXPLAINING' }) });
    await restore({ challenges: [], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: { state: 'AWAITING_CLAIM_CONFIRMATION' as const, turn_id: 'turn-explanation', proposed_claim: claim, capture_attempt_id: 7, turn_generation: 1, transcript: 'The window only grows' } });
    expect(screen.getByRole('textbox', { name: 'Editable Learner Transcript' })).toHaveValue('The window only grows');
    expect(screen.getByRole('button', { name: 'Confirm Explanation (No Execution)' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Submit prediction & run' })).not.toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'Execution & Prediction Comparison' })).not.toBeInTheDocument();
  });
  it('aborts speech immediately on edits, cancels once, and ignores late typed proposals', async () => {
    let resolveTurn!: (res: Record<string, unknown>) => void;
    vi.spyOn(api, 'submitTextTurn').mockImplementation(() => new Promise(resolve => { resolveTurn = resolve; }));
    const stopAudio = vi.spyOn(AudioPlayer.prototype, 'bargeInStop');
    await restore({ challenges: [{ ...challenge, reveal_state: 'HIDDEN' }], evidence_artifacts: [], trace_report: null, coaching: null, active_turn: null });
    fireEvent.change(screen.getByRole('textbox', { name: 'Editable Learner Transcript' }), { target: { value: 'I think it returns one' } });
    fireEvent.click(screen.getByRole('button', { name: 'Propose Transcript Interpretation' }));
    await waitFor(() => expect(api.submitTextTurn).toHaveBeenCalled());
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'edit one' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'edit two' } });
    expect(stopAudio).toHaveBeenCalled();
    await waitFor(() => expect(api.cancelSessionWork).toHaveBeenCalledTimes(1));
    await act(async () => resolveTurn({ turn_id: 'late', revision, proposed_claim: { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: challenge.challenge_id, predicted_output: 1, extraction_method: 'DETERMINISTIC' }, capture_attempt_id: 1, turn_generation: 1 }));
    expect(screen.queryByText('Interpretation:')).not.toBeInTheDocument();
  });
  it('preserves prior failure through save and explicitly verifies the repair', async () => {
    const nextRevision = { ...revision, code_version_id: 2, code_hash: 'e'.repeat(64), turn_generation: 2 };
    vi.spyOn(api, 'updateSessionCode').mockResolvedValue({ revision: nextRevision, changed: true });
    const verify = vi.spyOn(api, 'verifyRepair').mockResolvedValue(result({ revision: nextRevision, artifact: { ...artifact, revision: nextRevision }, challenge: null }));
    await restore();
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'def f(): return 1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Code Version' }));
    const button = await screen.findByRole('button', { name: 'Verify Saved Repair' });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(verify).toHaveBeenCalledWith('session-1', { revision: nextRevision, prior_artifact_id: 'failure-1', run_curated_suite: true, generated_cases_target: 100 }));
  });
  it('retries unavailable execution and permits next unseen transfer after a wrong prediction', async () => {
    const retry = vi.spyOn(api, 'retryExecution').mockResolvedValue(result({ learning_state: 'FRESH_CASE_REVIEW', artifact: { ...artifact, prediction_status: 'MISMATCH', verification_report: { ...artifact.verification_report, status: 'NO_FAILURE_FOUND' } } }));
    const next = vi.spyOn(api, 'createChallenge').mockResolvedValue({ ...challenge, challenge_id: 'unseen', purpose: 'TRANSFER', reveal_state: 'HIDDEN' });
    await restore({ evidence_artifacts: [{ ...artifact, actual_observation: { kind: 'UNAVAILABLE', duration_ms: 0 }, verification_report: { ...artifact.verification_report, status: 'EXECUTION_UNAVAILABLE' } }] });
    fireEvent.click(screen.getByRole('button', { name: 'Retry Unavailable Execution' }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith('session-1', 'turn-1', { revision }));
    fireEvent.click(screen.getByRole('button', { name: 'Load Held-Out Transfer Case' }));
    await waitFor(() => expect(next).toHaveBeenCalledWith('session-1', { revision, purpose: 'TRANSFER' }));
  });
  it('shows verifier process but hides failing outputs and oracle behind hidden diagnostic', async () => {
    const diagnostic = { ...challenge, challenge_id: 'hidden-failure', case_hash: 'failure-case', reveal_state: 'HIDDEN' as const };
    await restore({ challenges: [challenge, diagnostic] });
    const comparison = screen.getByRole('region', { name: 'Execution & Prediction Comparison' });
    expect(within(comparison).getByText(/Curated cases: 2 \/ 10/)).toBeInTheDocument();
    expect(within(comparison).getByText(/Generated cases: 3 \/ 20/)).toBeInTheDocument();
    expect(within(comparison).getByText(/confirmed_mismatch/)).toBeInTheDocument();
    expect(within(comparison).getByText(/SHRINK_COMPLETED/)).toBeInTheDocument();
    expect(comparison).not.toHaveTextContent('9917');
    expect(comparison).not.toHaveTextContent('7713');
    expect(screen.queryByTestId('trace-step-details')).not.toBeInTheDocument();
  });
  it('requests hints sequentially and suppresses stale coaching after save', async () => {
    await restore();
    expect(screen.getByRole('button', { name: 'Level 2 Hint' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Level 3 Hint' })).toBeDisabled();
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'repair' } });
    expect(screen.queryByText('Inspect this transition.')).not.toBeInTheDocument();
  });
});
