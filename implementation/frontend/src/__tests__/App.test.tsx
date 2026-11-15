import '@testing-library/jest-dom/vitest';
import { StrictMode } from 'react';
import { AudioPlayer } from '../services/audioPlayer';
import { AudioRecorder } from '../services/audioRecorder';
import { DEFAULT_AUDIO_PREFERENCES, saveAudioPreferences } from '../voice/preferences';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/apiClient';
import type { BrandingInfo, CreateSessionResponse, ExerciseMetadata, HealthResponse, RevisionRef } from '../types/api';
vi.mock('../components/PythonEditor', () => ({ PythonEditor: ({ value, onChange }: {value: string; onChange: (s: string) => void}) => <textarea aria-label="Python Solution Editor" value={value} onChange={e => onChange(e.target.value)} /> }));
import App from '../App';

const revision: RevisionRef = { session_id: '00000000-0000-4000-8000-000000000001', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 1, code_hash: 'c'.repeat(64), turn_generation: 1 };
const branding: BrandingInfo = { productName: 'Voice Coding Coach', productNameStatus: 'UNDECIDED_PLACEHOLDER', shortName: 'VCC', tagline: 'Explain, predict, verify, and transfer.' };
const health: HealthResponse = { status: 'ok', service: 'vcc-coordinator', phase: 'P0', version: 'test', custom_code_execution_enabled: false, product_name: branding.productName, product_name_status: branding.productNameStatus };
const exercises: ExerciseMetadata[] = [{ exercise_id: revision.exercise_id, title: 'Shortest qualifying subarray', comparator: 'strict_structural', catalog_status: 'READY', function_name: 'shortest_subarray_ge_target', difficulty: 'intermediate', core_concepts: ['bounds'], description: 'Return the shortest length.', starter_code: 'def shortest_subarray_ge_target(nums, target):\n    return 23\n', default_spec_version: revision.spec_version, spec_versions: [{ spec_version: revision.spec_version, label: 'Positive', min_length: 1, max_length: 15, min_value: 1, max_value: 50, sorted_required: false, target_bounds: [1,200], constraints_summary: ['Positive integers'] }] }];
const created: CreateSessionResponse = { session_id: revision.session_id, session_token: 'test-token', starter_code: exercises[0].starter_code, revision, state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true };
function metadata(): void {
  vi.spyOn(api.apiClient, 'getHealth').mockResolvedValue(health);
  vi.spyOn(api.apiClient, 'getBranding').mockResolvedValue(branding);
  vi.spyOn(api.apiClient, 'getExercises').mockResolvedValue(exercises);
  vi.spyOn(api.apiClient, 'getDemoPresets').mockResolvedValue([]);
  vi.spyOn(api, 'cancelSessionWork').mockResolvedValue({});
  vi.spyOn(api, 'createSession').mockImplementation(async request => ({ ...created, revision: { ...revision, spec_version: request.spec_version }, spec_acknowledged: request.spec_version !== 'v2_negatives_allowed' }));
  vi.spyOn(api, 'restoreSession').mockResolvedValue({ session_id: revision.session_id, state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'TYPED_FALLBACK', source_code: exercises[0].starter_code, revision, challenges: [], evidence_artifacts: [] });
}
async function ready(): Promise<void> {
  await waitFor(() => expect(screen.getByRole('button', { name: 'Talk to your mentor' })).toBeEnabled());
}
function openPracticeTools(): void {
  const summary = screen.getByText('Challenge & practice tools');
  if (!summary.closest('details')?.open) fireEvent.click(summary);
}
function openTranscript(): void {
  const toggle = screen.queryByRole('button', { name: 'Transcript & text' });
  if (toggle) fireEvent.click(toggle);
}
function enableVoicePreferences(): void {
  saveAudioPreferences({ ...DEFAULT_AUDIO_PREFERENCES, textOnly: false, voiceOutput: true, muted: false, introductions: false, autoSpeak: false });
}
async function start(): Promise<void> {
  enableVoicePreferences();
  metadata(); vi.spyOn(api, 'createSession').mockResolvedValue(created);
  render(<App />);
  fireEvent.click(await screen.findByRole('link', { name: exercises[0].title }));
  await ready();
  expect(api.createSession).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'Start Practice Session' })).not.toBeInTheDocument();
}
beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '/'); });
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.restoreAllMocks(); });
describe('Integrated workbench', () => {
  it('browses the library silently and greets on question opening while preserving drafts', async () => {
    metadata(); const orientation = vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: new ArrayBuffer(4), playbackId: 'intro' });
    vi.spyOn(AudioPlayer.prototype, 'playWavBytes').mockResolvedValue({ started: true, fallbackAck: null });
    const microphone = vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture');
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Bookmark Shortest qualifying subarray' }));
    expect(orientation).not.toHaveBeenCalled();
    expect(microphone).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('link', { name: exercises[0].title }));
    const editor = await screen.findByRole('textbox', { name: 'Python Solution Editor' });
    fireEvent.change(editor, { target: { value: 'my unsaved draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Problem library' }));
    expect(await screen.findByRole('button', { name: 'Remove bookmark for Shortest qualifying subarray' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('link', { name: exercises[0].title }));
    expect(await screen.findByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('my unsaved draft');
    await waitFor(() => expect(orientation).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Editable Learner Transcript' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Transcript & text' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getAllByRole('button', { name: /^(Talk to your mentor|Send voice|Done speaking|Interrupt and talk)$/ })).toHaveLength(1);
    expect(screen.queryByRole('region', { name: 'Choose your practice mode' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Text only' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Voice coach' })).not.toBeInTheDocument();
    expect(microphone).not.toHaveBeenCalled();
    orientation.mockClear();
    expect(location.pathname).toBe('/practice/ex1_shortest_subarray');
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    expect(screen.getByRole('checkbox', { name: /Problem introductions/ })).toBeChecked();
    const textOnly = screen.getByRole('checkbox', { name: /Text-only mode/ });
    expect(textOnly).not.toBeChecked();
    fireEvent.click(textOnly);
    expect(textOnly).toBeChecked();
    expect(microphone).not.toHaveBeenCalled();
    expect(orientation).not.toHaveBeenCalled();
  });
  it('uses cached local orientation replay and makes no requests while muted', async () => {
    await start();
    const orientation = vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: new ArrayBuffer(4), playbackId: 'intro-1' });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mute voice playback' }));
    expect(screen.getByRole('button', { name: 'Test voice' })).toBeDisabled();
    expect(orientation).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('combobox', { name: 'Language for next session' }), { target: { value: 'ta-IN,en-IN' } });
    expect(screen.getByText(/This session uses English/)).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('vcc-product-v1') ?? '{}').language).toBe('ta-IN,en-IN');
  });
  it('restores tab session identity underneath a persisted unsaved draft', async () => {
    metadata();
    history.replaceState(null, '', '/practice/ex1_shortest_subarray?spec=v1_positive_only');
    sessionStorage.setItem('vcc-tab-sessions', JSON.stringify({ 'ex1_shortest_subarray::v1_positive_only': { id: revision.session_id, token: 'token' } }));
    localStorage.setItem('vcc-product-v1', JSON.stringify({ drafts: { 'ex1_shortest_subarray::v1_positive_only': { sourceCode: 'persisted dirty repair', transcript: 'unsaved reasoning', updatedAt: 1, status: 'Draft' } } }));
    vi.spyOn(api, 'restoreSession').mockResolvedValue({ session_id: revision.session_id, state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'TYPED_FALLBACK', source_code: exercises[0].starter_code, revision, challenges: [], evidence_artifacts: [] });
    render(<App />);
    expect(await screen.findByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('persisted dirty repair');
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Start Practice Session' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Save Code Version' })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Editable Learner Transcript' })).toHaveValue('unsaved reasoning');
    openTranscript();
    expect(screen.getByRole('textbox', { name: 'Editable Learner Transcript' })).toHaveValue('unsaved reasoning');
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
  });
  it('recreates playable voice resources after StrictMode cleanup', async () => {
    enableVoicePreferences();
    metadata(); vi.spyOn(api, 'createSession').mockResolvedValue(created);
    vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: new ArrayBuffer(4), playbackId: 'voice-id' });
    vi.spyOn(AudioPlayer.prototype, 'unlockAudioFromGesture').mockResolvedValue(true);
    const play = vi.spyOn(AudioPlayer.prototype, 'playWavBytes').mockResolvedValue({ started: true, fallbackAck: null });
    render(<StrictMode><App /></StrictMode>);
    fireEvent.click(await screen.findByRole('link', { name: exercises[0].title }));
    await ready();
    expect(api.createSession).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Start Practice Session' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Test voice' }));
    await waitFor(() => expect(play).toHaveBeenCalled());
  });
  it('persists deliberately empty drafts and keeps them empty when starting a session', async () => {
    metadata(); vi.spyOn(api, 'createSession').mockResolvedValue(created);
    render(<App />);
    fireEvent.click(await screen.findByRole('link', { name: exercises[0].title }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Problem library' }));
    fireEvent.click(await screen.findByRole('link', { name: exercises[0].title }));
    expect(await screen.findByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('');
    await waitFor(() => expect(api.restoreSession).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Code Version' })).toBeEnabled());
    expect(screen.queryByRole('button', { name: 'Start Practice Session' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('');
  });
  it('deletes session data and its local draft rather than silently restoring it', async () => {
    await start();
    const remove = vi.spyOn(api, 'deleteSession').mockResolvedValue({ session_id: revision.session_id, deleted_at: '2026-11-14T00:00:00Z', limitations: 'Provider retention follows provider policy.' });
    vi.spyOn(api, 'restoreSession').mockResolvedValue({ session_id: revision.session_id, state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'TYPED_FALLBACK', source_code: exercises[0].starter_code, revision, challenges: [], evidence_artifacts: [] });
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'private deleted draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete Session' }));
    await waitFor(() => expect(remove).toHaveBeenCalled());
    await waitFor(() => expect(JSON.parse(localStorage.getItem('vcc-product-v1') ?? '{}').drafts['ex1_shortest_subarray::v1_positive_only']).toBeUndefined());
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    expect(screen.getByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue(exercises[0].starter_code);
  });
  it('loads configurable branding and recovers after metadata failure', async () => {
    metadata(); vi.mocked(api.apiClient.getBranding).mockRejectedValueOnce(new Error('Coordinator offline'));
    render(<App />); expect(screen.getByRole('status')).toHaveTextContent('Loading workspace metadata');
    expect(await screen.findByRole('alert')).toHaveTextContent('Coordinator offline');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByTestId('exercise-card-ex1_shortest_subarray')).toBeInTheDocument();
    expect(document.title).toBe('Voice Coding Coach');
  });
  it('preserves unsaved code separately when switching specifications and handles history navigation', async () => {
    metadata();
    vi.mocked(api.apiClient.getExercises).mockResolvedValue([{ ...exercises[0], spec_versions: [...exercises[0].spec_versions, { ...exercises[0].spec_versions[0], spec_version: 'v2_negatives_allowed', label: 'Negatives' }] }]);
    render(<App />);
    fireEvent.click(await screen.findByRole('link', { name: exercises[0].title }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'positive-only draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Negatives' }));
    expect(await screen.findByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue(exercises[0].starter_code);
    expect(screen.getByTestId('domain-ack-banner')).toBeInTheDocument();
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
    history.replaceState(null, '', '/practice/ex1_shortest_subarray?spec=v1_positive_only');
    fireEvent(window, new PopStateEvent('popstate'));
    expect(await screen.findByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('positive-only draft');
    expect(screen.queryByTestId('domain-ack-banner')).not.toBeInTheDocument();
  });
  it('saves via CAS and keeps edits made while saving dirty', async () => {
    await start();
    let resolveSave!: (value: apiReturn) => void;
    type apiReturn = Awaited<ReturnType<typeof api.updateSessionCode>>;
    const save = vi.spyOn(api, 'updateSessionCode').mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
    const editor = screen.getByRole('textbox', { name: 'Python Solution Editor' });
    fireEvent.change(editor, { target: { value: 'first edit' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Code Version' }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    fireEvent.change(editor, { target: { value: 'newer unsaved edit' } });
    resolveSave({ revision: { ...revision, code_version_id: 2 }, changed: true });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save Code Version' })).toBeEnabled());
    expect(screen.getByTestId('stale-buffer-badge')).toBeInTheDocument();
    expect(editor).toHaveValue('newer unsaved edit');
    expect(save).toHaveBeenCalledWith(revision.session_id, { code: 'first edit', expected_code_version_id: 1, client_edit_sequence: 1 });
  });
  it('uses server-owned challenge and server results, never fabricating a successful execution', async () => {
    await start();
    const challenge = { challenge_id: '00000000-0000-4000-8000-000000000010', revision, input_args: { nums: [1,2], target: 2 }, case_hash: 'd'.repeat(64), purpose: 'DIAGNOSTIC' as const, reveal_state: 'HIDDEN' as const, created_at: '2026-11-13T00:00:00Z', expires_at: '2026-11-14T00:00:00Z' };
    vi.spyOn(api, 'createChallenge').mockResolvedValue(challenge);
    vi.spyOn(api, 'restoreSession').mockResolvedValue({ session_id: revision.session_id, state: 'READY', learning_state: 'AWAITING_PREDICTION', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'TYPED_FALLBACK', source_code: exercises[0].starter_code, revision, challenges: [challenge], evidence_artifacts: [] });
    const claim = { claim_type: 'OUTPUT_PREDICTION_AND_REASON', challenge_id: challenge.challenge_id, predicted_output: 23, reason_summary: null, polarity: 'AFFIRMATIVE', extraction_method: 'DETERMINISTIC', confirmed_at: null } as const;
    vi.spyOn(api, 'submitTextTurn').mockResolvedValue({ turn_id: 'turn-1', revision, proposed_claim: claim, capture_attempt_id: 1, turn_generation: 1 });
    const confirm = vi.spyOn(api, 'confirmTurnClaim').mockRejectedValue(new Error('Genuine gVisor runtime unavailable'));
    openPracticeTools();
    fireEvent.click(screen.getByRole('button', { name: 'Issue Challenge Input' }));
    expect(await screen.findByTestId('challenge-input-json')).toHaveTextContent('"nums":[1,2]');
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Predicted Integer Output' }), { target: { value: '23' } });
    fireEvent.click(screen.getByRole('button', { name: 'Propose Claim' }));
    const submit = await screen.findByRole('button', { name: 'Submit prediction & run' });
    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.queryByTestId('confirm-claim-btn')).not.toBeInTheDocument();
    fireEvent.click(submit);
    expect(await screen.findByRole('alert')).toHaveTextContent('Genuine gVisor runtime unavailable');
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('verification-status-badge')).not.toBeInTheDocument();
    expect(screen.queryByTestId('trace-step-details')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load Held-Out Transfer Case' })).not.toBeInTheDocument();
  });
});
