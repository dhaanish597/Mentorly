import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/apiClient';
import { AudioRecorder, encodePcm16ToWavBytes } from '../services/audioRecorder';
import { DEFAULT_AUDIO_PREFERENCES, DEFAULT_SPEECH_PREFERENCES, loadAudioPreferences, saveAudioPreferences, saveSpeechPreferences } from '../voice/preferences';
import { StreamingPcmPlayer } from '../services/speechStreaming';
import type { EvidenceArtifact, ExerciseMetadata, RevisionRef } from '../types/api';
vi.mock('../components/PythonEditor', () => ({ PythonEditor: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => <textarea aria-label="Python Solution Editor" value={value} onChange={event => onChange(event.target.value)} /> }));
import App from '../App';

// Real App/store/player; recorder, API and browser audio are controlled boundaries.
// Synthetic PCM and protocol replies are not real-provider or execution evidence.
const revision: RevisionRef = { session_id: '00000000-0000-4000-8000-000000000001', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 1, code_hash: 'c'.repeat(64), turn_generation: 1 };
const exercise: ExerciseMetadata = { exercise_id: revision.exercise_id, title: 'Shortest qualifying subarray', function_name: 'shortest_subarray_ge_target', difficulty: 'intermediate', comparator: 'strict_structural', catalog_status: 'READY', description: 'Find the shortest window.', core_concepts: ['Sliding window'], starter_code: 'def shortest_subarray_ge_target(nums, target):\n    return 2\n', default_spec_version: revision.spec_version, spec_versions: [{ spec_version: revision.spec_version, label: 'Positive', min_length: 1, max_length: 20, min_value: 1, max_value: 100, sorted_required: false, constraints_summary: ['Positive integers'] }] };
const snapshot: api.SessionSnapshot = { session_id: revision.session_id, state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'VOICE', source_code: exercise.starter_code, revision, challenges: [], evidence_artifacts: [] };
const turn: api.TurnResponse = { turn_id: '00000000-0000-4000-8000-000000000010', revision: { ...revision, turn_generation: 2 }, capture_attempt_id: 1, turn_generation: 2, normalized_transcript: 'The window tracks the sum.', proposed_claim: { claim_type: 'INVARIANT_OR_MECHANISM_CLAIM', mechanism_summary: 'The window tracks the sum.', extraction_method: 'DETERMINISTIC' } };
const artifact: EvidenceArtifact = { artifact_id: '00000000-0000-4000-8000-000000000020', revision, challenge_id: '00000000-0000-4000-8000-000000000030', canonical_input: { nums: [1, 2], target: 2 }, case_hash: 'a'.repeat(64), confirmed_prediction: 2, actual_observation: { kind: 'RETURN', return_value: 2, duration_ms: 1 }, reference_output: 1, prediction_status: 'MATCH', minimization_status: 'NOT_ATTEMPTED', verification_report: { status: 'COUNTEREXAMPLE_CONFIRMED', curated_cases_run: 1, curated_cases_total: 1, generated_cases_run: 0, generated_cases_target: 0, terminal_reason: 'Protocol fixture', runtime_version: 'protocol-fixture' } };
const wav = encodePcm16ToWavBytes(new Int16Array(16000).fill(100), 16000);
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });
const audio = () => new Response(wav.slice(), { headers: { 'Content-Type': 'audio/wav', 'X-Playback-ID': 'protocol-playback' } });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
class AudioContextBoundary {
  state = 'running'; currentTime = 0; destination = {};
  sources: { playbackRate: { value: number }; onended: (() => void) | null; start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }[] = [];
  gains: { gain: { value: number }; connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }[] = [];
  constructor() { contexts.push(this); }
  resume = vi.fn(async () => { this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; });
  createGain() { const gain = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() }; this.gains.push(gain); return gain; }
  createBuffer(_channels: number, frames: number, rate: number) { return { duration: frames / rate, getChannelData: () => new Float32Array(frames) }; }
  createBufferSource() {
    const node = { buffer: null, playbackRate: { value: 1 }, onended: null as (() => void) | null, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn() };
    this.sources.push(node); return node;
  }
}
let contexts: AudioContextBoundary[];
let captureOptions: Parameters<AudioRecorder['startMicrophoneCapture']>[0];
let captureActive: boolean;
let fetcher: ReturnType<typeof vi.fn>;
let drain: ReturnType<typeof vi.spyOn>;
let dispose: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); contexts = []; captureActive = false;
  history.replaceState(null, '', `/practice/${revision.exercise_id}?spec=${revision.spec_version}`);
  saveAudioPreferences({ ...DEFAULT_AUDIO_PREFERENCES, introductions: false, autoSpeak: true });
  vi.stubGlobal('AudioContext', AudioContextBoundary);
  vi.spyOn(api.apiClient, 'getHealth').mockResolvedValue({ status: 'ok', service: 'protocol-fixture', phase: 'test', version: 'test', custom_code_execution_enabled: false, product_name: 'VIVA', product_name_status: 'TEST' });
  vi.spyOn(api.apiClient, 'getBranding').mockResolvedValue({ productName: 'VIVA', shortName: 'V', tagline: 'Practice', productNameStatus: 'TEST' });
  vi.spyOn(api.apiClient, 'getExercises').mockResolvedValue([exercise]);
  vi.spyOn(api.apiClient, 'getDemoPresets').mockResolvedValue([]);
  vi.spyOn(api, 'restoreSession').mockResolvedValue(snapshot);
  vi.spyOn(api, 'cancelSessionWork').mockResolvedValue({});
  vi.spyOn(api, 'submitTextTurn').mockResolvedValue({ ...turn });
  vi.spyOn(api, 'createSession').mockResolvedValue({ session_id: revision.session_id, session_token: 'protocol-token', starter_code: exercise.starter_code, revision, state: 'READY', learning_state: 'EXPLAINING', spec_acknowledged: true });
  vi.spyOn(api, 'sendPlaybackAck').mockResolvedValue({ session_id: revision.session_id, turn_id: 'protocol-turn', turn_generation: 1, playback_status: 'COMPLETED' });
  vi.spyOn(AudioRecorder.prototype, 'isRecording', 'get').mockImplementation(() => captureActive);
  vi.spyOn(AudioRecorder.prototype, 'capturedSamplesCount', 'get').mockReturnValue(16000);
  vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(async options => { captureOptions = options; captureActive = true; return { turnGeneration: 1, captureAttemptId: 1 }; });
  drain = vi.spyOn(AudioRecorder.prototype, 'drainMicrophoneCapture').mockReturnValue({ sessionId: revision.session_id, turnGeneration: 1, captureAttemptId: 1, wavBytes: wav, sampleRateHz: 16000, durationSec: 1, rmsNormalized: .2, peakNormalized: .4, lowEnergyWarning: false, clippedSamples: 0 });
  dispose = vi.spyOn(AudioRecorder.prototype, 'dispose').mockImplementation(async () => { captureActive = false; });
  fetcher = vi.fn(async (url: string) => url.endsWith('/turns/audio') ? json(turn) : url.endsWith('/conversation/text') ? json({ text: 'Measure the window carefully.' }) : audio());
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });
async function mount(patch: Partial<api.SessionSnapshot> = {}) {
  vi.mocked(api.restoreSession).mockResolvedValue({ ...snapshot, ...patch });
  sessionStorage.setItem('vcc-tab-sessions', JSON.stringify({ [`${revision.exercise_id}::${revision.spec_version}`]: { id: revision.session_id, token: 'protocol-token' } }));
  render(<App />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Talk to your mentor' })).toBeEnabled());
  await act(async () => Promise.resolve());
}
async function talk() {
  fireEvent.click(screen.getByRole('button', { name: 'Talk to your mentor' }));
  await screen.findByRole('button', { name: 'Done speaking' });
}
async function send() {
  fireEvent.click(screen.getByRole('button', { name: 'Transcript & text' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Editable Learner Transcript' }), { target: { value: 'The window tracks the sum.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send explanation' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/conversation/text'))).toBe(true));
}
function optOut() {
  const value = JSON.stringify({ ...DEFAULT_AUDIO_PREFERENCES, textOnly: true });
  localStorage.setItem('viva.audio-preferences.v1', value);
  fireEvent(window, new StorageEvent('storage', { key: 'viva.audio-preferences.v1', newValue: value, storageArea: localStorage }));
}
function activeConversation() { return within(screen.getByRole('region', { name: 'Mentor–student conversation' })); }
function playbackContext() { return contexts.find(context => context.sources.length)!; }
function openTools() { fireEvent.click(screen.getByText('Challenge & practice tools')); }

describe('DSA conversation consent, cancellation and private history', () => {
  it.each(['after-render', 'same-event'] as const)('stops capture on cross-tab text-only and rejects a late cap callback (%s)', async timing => {
    await mount(); await talk();
    const callback = captureOptions?.onBackpressureLimitReached;
    expect(callback).toBeTypeOf('function');
    if (timing === 'same-event') act(() => { optOut(); callback?.(); });
    else { act(optOut); await waitFor(() => expect(dispose).toHaveBeenCalled()); act(() => callback?.()); }
    await act(async () => Promise.resolve());
    expect(dispose).toHaveBeenCalled();
    expect(captureActive).toBe(false);
    expect(drain).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('independently gates upload when opt-out arrives during capture draining', async () => {
    const segment = drain.getMockImplementation()!;
    drain.mockImplementationOnce((...args: unknown[]) => { optOut(); return segment(...args); });
    await mount(); await talk();
    act(() => captureOptions?.onBackpressureLimitReached?.());
    await act(async () => Promise.resolve());
    expect(drain).toHaveBeenCalledOnce();
    expect(dispose).toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(['empty', 'low-energy', 'header-only'] as const)('does not upload a %s capture', async mode => {
    if (mode === 'empty') vi.mocked(Object.getOwnPropertyDescriptor(AudioRecorder.prototype, 'capturedSamplesCount')!.get!).mockReturnValue(0);
    else {
      const segment = drain.getMockImplementation()!();
      drain.mockReturnValue({ ...segment, lowEnergyWarning: mode === 'low-energy', wavBytes: mode === 'header-only' ? new Uint8Array(44) : wav });
    }
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await act(async () => Promise.resolve());
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('serializes a capped second recording against the newly persisted turn revision', async () => {
    const first = deferred<Response>(); const nextTurn = { ...turn, turn_id: 'next-turn', revision: { ...turn.revision, turn_generation: 3 }, turn_generation: 3, normalized_transcript: 'My second explanation' };
    let uploads = 0;
    fetcher.mockImplementation(async (url: string) => url.endsWith('/turns/audio') ? (++uploads === 1 ? first.promise : json(nextTurn)) : url.endsWith('/conversation/text') ? json({ text: 'Consider the next boundary.' }) : audio());
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(uploads).toBe(1));
    captureActive = false;
    act(() => captureOptions?.onBackpressureLimitReached?.());
    await act(async () => first.resolve(json(turn)));
    await waitFor(() => expect(uploads).toBe(2));
    const requests = fetcher.mock.calls.filter(([url]) => url.endsWith('/turns/audio'));
    expect(JSON.parse((requests[0][1].body as FormData).get('revision') as string)).toEqual(revision);
    expect(JSON.parse((requests[1][1].body as FormData).get('revision') as string)).toEqual(turn.revision);
    expect(drain).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/conversation/text'))).toHaveLength(1));
  });
  it('drops a queued cap flush when opt-out arrives as the accepted capture is advanced', async () => {
    const first = deferred<Response>(); fetcher.mockReturnValue(first.promise);
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    act(() => captureOptions?.onBackpressureLimitReached?.());
    vi.spyOn(AudioRecorder.prototype, 'setTurnGeneration').mockImplementation(() => { optOut(); });
    await act(async () => first.resolve(json(turn)));
    expect(fetcher).toHaveBeenCalledOnce(); expect(captureActive).toBe(false);
  });
  it.each([null, {}, { message: 'Protocol recognition unavailable' }])('retains a failed recording without inventing a transcript for error payload %j', async detail => {
    fetcher.mockResolvedValue(new Response(JSON.stringify(detail), { status: 503, headers: { 'Content-Type': 'application/json' } }));
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    expect(await screen.findByRole('alert')).toHaveTextContent('Your audio is retained');
    expect(api.restoreSession).toHaveBeenCalledTimes(2);
    expect(activeConversation().getByText('Your completed exchanges will appear here.')).toBeInTheDocument();
  });
  it.each(['raw', 'missing'] as const)('does not invent ASR words when the normalized transcript is %s', async mode => {
    const returned = { ...turn, normalized_transcript: undefined, transcript: mode === 'raw' ? 'Raw recognized words' : undefined };
    fetcher.mockImplementation(async (url: string) => url.endsWith('/turns/audio') ? json(returned) : url.endsWith('/conversation/text') ? json({ text: 'Measure the window carefully.' }) : audio());
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    fireEvent.click(screen.getByRole('button', { name: 'Transcript & text' }));
    expect(screen.getByRole('textbox', { name: 'Editable Learner Transcript' })).toHaveValue(mode === 'raw' ? 'Raw recognized words' : '');
  });
  it('binds a hidden-challenge recording to its current revision without confirming or revealing it', async () => {
    const challenge = { challenge_id: artifact.challenge_id, revision, input_args: artifact.canonical_input, case_hash: artifact.case_hash, purpose: 'DIAGNOSTIC' as const, reveal_state: 'HIDDEN' as const, created_at: '2026-11-15T00:00:00Z', expires_at: '2026-11-16T00:00:00Z' };
    const returned = { ...turn, revision, turn_generation: revision.turn_generation };
    fetcher.mockImplementation(async (url: string) => url.endsWith('/turns/audio') ? json(returned) : url.endsWith('/conversation/text') ? json({ text: 'Explain the boundary before running.' }) : audio());
    const confirm = vi.spyOn(api, 'confirmTurnClaim');
    await mount({ challenges: [challenge], learning_state: 'AWAITING_PREDICTION' }); await talk();
    act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    const body = fetcher.mock.calls[0][1].body as FormData;
    expect(body.get('challenge_id')).toBe(challenge.challenge_id);
    expect(JSON.parse(body.get('revision') as string)).toEqual(revision);
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.queryByText('Reference Oracle:')).not.toBeInTheDocument();
  });
  it('preserves earlier learner words when a new recording continues an interrupted explanation', async () => {
    await mount({ active_turn: { state: 'AWAITING_CLAIM_CONFIRMATION', turn_id: 'earlier-turn', turn_generation: 1, capture_attempt_id: 1, proposed_claim: null, transcript: 'My earlier reasoning.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stop audio' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(api.submitTextTurn).toHaveBeenCalledOnce());
    expect(api.submitTextTurn).toHaveBeenCalledWith(revision.session_id, expect.objectContaining({ text: 'My earlier reasoning. The window tracks the sum.', revision: turn.revision }));
  });
  it('aborts an uploaded voice turn on cross-tab opt-out and ignores its late transcript', async () => {
    const pending = deferred<Response>(); fetcher.mockReturnValue(pending.promise);
    await mount(); await talk();
    fireEvent.click(screen.getByRole('button', { name: 'Done speaking' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    act(optOut);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => pending.resolve(json(turn)));
    expect(fetcher).toHaveBeenCalledOnce();
    expect(screen.queryByText(turn.normalized_transcript!)).not.toBeInTheDocument();
  });
  it('tracks Stop audio while the mentor text request is pending and never synthesizes its late reply', async () => {
    const pending = deferred<Response>(); fetcher.mockReturnValue(pending.promise);
    await mount(); await send();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stop audio' }));
    expect(fetcher.mock.calls[0][1].signal?.aborted).toBe(true);
    await act(async () => pending.resolve(json({ text: 'Late mentor reply' })));
    expect(fetcher).toHaveBeenCalledOnce();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('shows mentor text transport failure without dispatching synthesis or leaking the response body', async () => {
    fetcher.mockResolvedValue(new Response('private upstream payload', { status: 503 }));
    await mount(); await send();
    expect(await screen.findByRole('alert')).toHaveTextContent('mentor reply could not be loaded');
    expect(screen.getByRole('alert')).not.toHaveTextContent('private upstream payload');
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it('Stop audio rejects a late response body even after the TTS headers have arrived', async () => {
    const body = deferred<ArrayBuffer>();
    const response = audio(); vi.spyOn(response, 'arrayBuffer').mockReturnValue(body.promise);
    fetcher.mockImplementation(async (url: string) => url.endsWith('/conversation/text') ? json({ text: 'Measure the window carefully.' }) : response);
    await mount(); await send();
    await waitFor(() => expect(response.arrayBuffer).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stop audio' }));
    await act(async () => body.resolve(wav.buffer.slice(0) as ArrayBuffer));
    expect(contexts.flatMap(context => context.sources)).toHaveLength(0);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('uses real telemetry only while its capture is current and ignores frames after opt-out', async () => {
    await mount(); await talk(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    const frame = { pcm16: new Int16Array([100, 100]), rmsNormalized: .4, peakNormalized: .4, clippedSamples: 0 };
    act(() => captureOptions?.onFrameTelemetry?.(frame));
    expect(screen.getByRole('meter', { name: 'Microphone energy' })).toHaveAttribute('value', '0.4');
    act(optOut); act(() => captureOptions?.onFrameTelemetry?.(frame));
    expect(screen.getByRole('meter', { name: 'Microphone energy' })).toHaveAttribute('value', '0');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('validates imported conversation entries without displaying invalid or oversized history', async () => {
    sessionStorage.setItem(`viva.conversation.${revision.session_id}`, JSON.stringify([
      null, 'invalid entry', {}, { id: 'number', text: 123, speaker: 'mentor' },
      { id: 'oversized', text: 'OVERSIZED'.repeat(1000), speaker: 'mentor' },
      { id: 'wrong-speaker', text: 'Invalid speaker text', speaker: 'outsider' },
      { id: 'valid', text: 'தமிழ் 🙂 retained explanation', speaker: 'mentor' },
    ]));
    await mount();
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('தமிழ் 🙂 retained explanation');
    fireEvent.click(activeConversation().getByText('Conversation history'));
    expect(activeConversation().getByRole('list')).toHaveTextContent('தமிழ் 🙂 retained explanation');
    expect(screen.queryByText(/OVERSIZED|Invalid speaker text/)).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('aborts pending mentor text on unmount without starting synthesis', async () => {
    const pending = deferred<Response>(); fetcher.mockReturnValue(pending.promise);
    await mount(); await send();
    cleanup();
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => pending.resolve(json({ text: 'Late after unmount' })));
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it.each([null, {}, { text: null }, { text: '' }, { text: '   ' }])('rejects invalid mentor text %j without dispatching voice', async reply => {
    fetcher.mockResolvedValue(json(reply));
    await mount(); await send();
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid text response');
    expect(fetcher).toHaveBeenCalledOnce();
    expect(contexts.flatMap(context => context.sources)).toHaveLength(0);
  });
  it('rejects late conversation audio after a code edit invalidates the full revision', async () => {
    const pending = deferred<Response>();
    fetcher.mockImplementation(async (url: string) => url.endsWith('/conversation/text') ? json({ text: 'Measure the window carefully.' }) : pending.promise);
    await mount(); await send();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'new code revision' } });
    await act(async () => pending.resolve(audio()));
    expect(contexts.flatMap(context => context.sources)).toHaveLength(0);
    expect(screen.getByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('new code revision');
  });
  it.each([false, true])('removes conversation history only on successful deletion (delete failure %s)', async failed => {
    const historyKey = `viva.conversation.${revision.session_id}`;
    sessionStorage.setItem(historyKey, JSON.stringify([{ id: 'private-mentor', speaker: 'mentor', text: 'Private saved explanation' }]));
    const remove = vi.spyOn(api, 'deleteSession');
    if (failed) remove.mockRejectedValue(new Error('Deletion unavailable'));
    else remove.mockResolvedValue({ session_id: revision.session_id, deleted_at: '2026-11-15T00:00:00Z', limitations: 'Provider retention is separate.' });
    await mount();
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Private saved explanation');
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete Session' }));
    await waitFor(() => expect(remove).toHaveBeenCalledOnce());
    if (failed) { await screen.findByRole('alert'); expect(sessionStorage.getItem(historyKey)).toContain('Private saved explanation'); }
    else { await waitFor(() => expect(sessionStorage.getItem(historyKey)).toBeNull()); expect(screen.queryByText('Private saved explanation')).not.toBeInTheDocument(); }
  });
  it.each([['ta-IN,en-IN', 'ta-IN'], ['en-IN', 'en-IN']])('connects next-session %s to the actual speech payload without changing the selected voice', async (language, locale) => {
    saveSpeechPreferences({ ...DEFAULT_SPEECH_PREFERENCES, voice: 'Lakshmi' });
    history.replaceState(null, '', '/library'); render(<App />);
    await screen.findByRole('link', { name: exercise.title });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Language for next session' }), { target: { value: language } });
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('link', { name: exercise.title }));
    await waitFor(() => expect(api.createSession).toHaveBeenCalledOnce());
    expect(api.createSession).toHaveBeenCalledWith(expect.objectContaining({ language_mode: language, spoken_language: locale, voice: 'Lakshmi' }));
  });
});

describe('actual final STT source controls visual reveal', () => {
  it('starts visual reveal only after final recognition, preserves full history, and does not delay typed edits', async () => {
    const recognition = deferred<Response>(); const reply = deferred<Response>();
    fetcher.mockImplementation(async (url: string) => url.endsWith('/turns/audio') ? recognition.promise : reply.promise);
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    expect(screen.queryByText('Final transcript — visual reveal, not live recognition')).not.toBeInTheDocument();
    await act(async () => recognition.resolve(json(turn)));
    expect(screen.getByText('Final transcript — visual reveal, not live recognition')).toBeInTheDocument();
    expect(activeConversation().getByLabelText('Current speaker transcript')).not.toHaveTextContent(turn.normalized_transcript!);
    fireEvent.click(activeConversation().getByText('Conversation history'));
    expect(within(activeConversation().getByRole('list')).getByText(turn.normalized_transcript!)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Transcript & text' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Editable Learner Transcript' }), { target: { value: 'Typed correction appears immediately.' } });
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Typed correction appears immediately.');
    expect(screen.queryByText('Final transcript — visual reveal, not live recognition')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Problem library' }));
    await act(async () => reply.resolve(json({ text: 'Late cancelled reply' })));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe('capture consent never overrides output preferences', () => {
  it.each(['muted', 'autoSpeak', 'voiceOutput'] as const)('Send voice preserves the changed %s preference and makes no unsolicited TTS request', async preference => {
    await mount(); await talk(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    const label = preference === 'muted' ? 'Mute voice playback' : preference === 'autoSpeak' ? 'Automatically speak new coach replies' : 'Voice output enabled';
    fireEvent.click(screen.getByRole('checkbox', { name: label }));
    const saved = loadAudioPreferences();
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done speaking' }));
    fireEvent.click(screen.getByRole('button', { name: 'Transcript & text' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send explanation' })).toBeEnabled());
    expect(loadAudioPreferences()).toEqual(saved);
    expect(fetcher.mock.calls.map(([url]) => url.split('/').slice(-2).join('/'))).toEqual(['turns/audio', 'conversation/text']);
    expect(contexts.flatMap(context => context.sources)).toHaveLength(0);
  });
  it('a deliberate capture gesture clears only text-only consent, not mute, automatic replies or voice output', async () => {
    const preferences = { ...DEFAULT_AUDIO_PREFERENCES, textOnly: true, muted: true, voiceOutput: false, autoSpeak: false };
    saveAudioPreferences(preferences); await mount(); await talk();
    expect(loadAudioPreferences()).toEqual({ ...preferences, textOnly: false });
    expect(captureActive).toBe(true); expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('continuous capture device loss', () => {
  it.each([false, true])('retains unsent audio for explicit retry after device loss (turn already advanced %s)', async advanced => {
    const unsent = encodePcm16ToWavBytes(new Int16Array(16000).fill(2222), 16000);
    await mount(); await talk();
    if (advanced) {
      act(() => captureOptions?.onSilenceTimeout?.());
      await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
      await waitFor(() => expect(screen.queryByText('Working…')).not.toBeInTheDocument());
    }
    const segment = drain.getMockImplementation()!(); drain.mockReturnValue({ ...segment, wavBytes: unsent });
    const before = fetcher.mock.calls.length;
    captureActive = false; act(() => captureOptions?.onDeviceLost?.('Device disappeared'));
    expect(screen.queryByRole('button', { name: 'Done speaking' })).not.toBeInTheDocument();
    expect(screen.getByText(/Microphone disconnected.*recording.*retained/i)).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(before);
    const retry = screen.getByRole('button', { name: 'Send retained recording' }); expect(retry).toBeEnabled();
    const currentRevision = advanced ? turn.revision : revision;
    const next = { ...turn, revision: { ...currentRevision, turn_generation: currentRevision.turn_generation + 1 }, turn_generation: currentRevision.turn_generation + 1 };
    fetcher.mockImplementation(async (url: string) => url.endsWith('/turns/audio') ? json(next) : url.endsWith('/conversation/text') ? json({ text: 'Continue with the saved explanation.' }) : audio());
    fireEvent.click(retry);
    await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/turns/audio'))).toHaveLength(advanced ? 2 : 1));
    const request = fetcher.mock.calls[before][1];
    expect(JSON.parse((request.body as FormData).get('revision') as string)).toEqual(currentRevision);
    const uploaded = await new Promise<ArrayBuffer>(resolve => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.readAsArrayBuffer((request.body as FormData).get('audio') as Blob);
    });
    expect(new Uint8Array(uploaded)).toEqual(unsent);
    expect(AudioRecorder.prototype.startMicrophoneCapture).toHaveBeenCalledOnce();
  });
  it('device loss during an accepted upload retains the next segment without automatically flushing it', async () => {
    const first = deferred<Response>(); fetcher.mockReturnValue(first.promise);
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    const segment = drain.getMockImplementation()!();
    drain.mockReturnValue({ ...segment, wavBytes: encodePcm16ToWavBytes(new Int16Array(16000).fill(2222), 16000) });
    captureActive = false; act(() => captureOptions?.onDeviceLost?.('Device disappeared during upload'));
    await act(async () => first.resolve(json(turn)));
    expect(fetcher).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Send retained recording' })).toBeEnabled();
    expect(screen.getByText(/Microphone disconnected.*recording.*retained/i)).toBeInTheDocument();
  });
  it.each(['empty', 'quiet'] as const)('device loss with %s remaining audio stops capture without inventing a retained recording', async mode => {
    await mount(); await talk();
    if (mode === 'empty') vi.mocked(Object.getOwnPropertyDescriptor(AudioRecorder.prototype, 'capturedSamplesCount')!.get!).mockReturnValue(0);
    else drain.mockReturnValue({ ...drain.getMockImplementation()!(), lowEnergyWarning: true });
    captureActive = false; act(() => captureOptions?.onDeviceLost?.('Device disappeared'));
    expect(screen.getByText('Microphone disconnected. Start a new recording or continue with text.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send retained recording' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Talk to your mentor' })).toBeEnabled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('ignores a previous recorder device-loss callback after opt-out and a fresh deliberate capture', async () => {
    await mount(); await talk(); const old = captureOptions;
    act(optOut); await talk(); dispose.mockClear();
    act(() => old?.onDeviceLost?.('Late old-device callback'));
    expect(screen.getByRole('button', { name: 'Done speaking' })).toBeInTheDocument();
    expect(captureActive).toBe(true); expect(dispose).not.toHaveBeenCalled();
  });
});

describe('DSA device persistence boundaries', () => {
  it('reports speech preference storage failure and does not silently change the next session language', async () => {
    history.replaceState(null, '', '/library'); render(<App />);
    await screen.findByRole('link', { name: exercise.title });
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
      if (key === 'viva.speech-preferences.v1') throw new Error('Storage unavailable');
      return original.call(this, key, value);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Language for next session' }), { target: { value: 'ta-IN,en-IN' } });
    expect(screen.getByText('Language preferences could not be saved. Retry before starting another session.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('link', { name: exercise.title }));
    await waitFor(() => expect(api.createSession).toHaveBeenCalledOnce());
    expect(api.createSession).toHaveBeenCalledWith(expect.objectContaining({ language_mode: 'en-IN' }));
  });
  it('reports audio preference persistence failure while retaining usable local controls', async () => {
    await mount();
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
      if (key === 'viva.audio-preferences.v1') throw new Error('Storage unavailable');
      return original.call(this, key, value);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Playback speed' }), { target: { value: '1.25' } });
    expect(await screen.findByText('Audio preferences could not be saved on this device.')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Playback speed' })).toHaveValue('1.25');
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('stream playback clock getters', () => {
  it('distinguishes unscheduled, queued, audible, completed and stopped PCM without changing scheduling', async () => {
    const context = new AudioContextBoundary();
    const stream = new StreamingPcmPlayer(revision, () => context as unknown as AudioContext);
    expect(stream.isPlaying).toBe(false); expect(stream.playbackProgress).toBe(0);
    await stream.append({ event_type: 'chunk', request_id: 'protocol-clock', chunk_index: 0, sample_rate: 8000, audio_b64: btoa(String.fromCharCode(...new Uint8Array(new Int16Array(8000).buffer))) });
    expect(stream.isPlaying).toBe(false); expect(stream.playbackProgress).toBe(0);
    context.currentTime = .53;
    expect(stream.isPlaying).toBe(true); expect(stream.playbackProgress).toBeCloseTo(.5);
    context.state = 'suspended'; expect(stream.isPlaying).toBe(false);
    context.state = 'running'; context.currentTime = 2;
    expect(stream.isPlaying).toBe(false); expect(stream.playbackProgress).toBe(.99);
    const finish = stream.finish(); context.sources[0].onended?.(); await finish;
    expect(stream.playbackProgress).toBe(1);
    await stream.stop(); expect(stream.isPlaying).toBe(false); expect(context.close).toHaveBeenCalledOnce();
  });
});

describe('actual audio source controls the current speaker and caption', () => {
  it('shows the audible mentor and its audio-clock caption while continuous capture stays open', async () => {
    await mount(); await talk();
    act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(contexts.some(context => context.sources.length)).toBe(true));
    playbackContext().currentTime = .5;
    await waitFor(() => expect(activeConversation().getByRole('status')).toHaveTextContent('Mentor speaking'));
    expect(captureActive).toBe(true);
    expect(activeConversation().getByText('Your mentor')).toBeInTheDocument();
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Measure the');
    expect(activeConversation().getByLabelText('Current speaker transcript')).not.toHaveTextContent('The window tracks');
    act(() => playbackContext().sources[0].onended?.());
    await waitFor(() => expect(activeConversation().getByRole('status')).toHaveTextContent('Listening to you'));
  });
  it.each([
    ['Test voice', 'Voice is ready.'],
    ['Play problem introduction', "Let's explore Shortest qualifying subarray."],
  ])('uses the fixed %s caption rather than a previous conversational reply and preserves it on replay', async (button, expected) => {
    sessionStorage.setItem(`viva.conversation.${revision.session_id}`, JSON.stringify([{ id: 'old', speaker: 'mentor', text: 'Different old mentor response' }]));
    vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: wav.buffer.slice(0) as ArrayBuffer, playbackId: 'orientation-test' });
    await mount(); openTools();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: button }));
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    playbackContext().currentTime = .5;
    await waitFor(() => expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent(expected));
    act(() => playbackContext().sources[0].onended?.());
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay last voice' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Replay last voice' }));
    await waitFor(() => expect(playbackContext().sources.length).toBe(2));
    playbackContext().currentTime = 1;
    await waitFor(() => {
      expect(activeConversation().getByRole('status')).toHaveTextContent('Mentor speaking');
      expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent(expected);
    });
    expect(api.requestVoiceOrientation).toHaveBeenCalledOnce();
  });
  it('barge-in stops audible mentor audio without closing continuous capture or discarding the transcript', async () => {
    await mount(); await talk(); act(() => captureOptions?.onSilenceTimeout?.());
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    playbackContext().currentTime = .5;
    await waitFor(() => expect(activeConversation().getByRole('status')).toHaveTextContent('Mentor speaking'));
    act(() => captureOptions?.onSpeechActivity?.());
    expect(playbackContext().sources[0].stop).toHaveBeenCalled();
    expect(captureActive).toBe(true);
    await waitFor(() => expect(activeConversation().getByRole('status')).toHaveTextContent('Listening to you'));
    fireEvent.click(activeConversation().getByText('Conversation history'));
    expect(activeConversation().getByText('The window tracks the sum.')).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it('local gain and speed propagate to active audio without requesting new synthesis', async () => {
    vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: wav.buffer.slice(0) as ArrayBuffer, playbackId: 'settings-audio' });
    await mount(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Test voice' }));
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    fireEvent.change(screen.getByRole('slider', { name: 'Voice volume' }), { target: { value: '.4' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Playback speed' }), { target: { value: '1.5' } });
    expect(playbackContext().gains[0].gain.value).toBe(.4);
    expect(playbackContext().sources[0].playbackRate.value).toBe(1.5);
    expect(api.requestVoiceOrientation).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mute voice playback' }));
    expect(playbackContext().sources[0].stop).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Test voice' })).toBeDisabled();
  });
  it.each(['autoSpeak', 'voiceOutput'] as const)('keeps a completed mentor text reply without synthesis when %s is disabled', async preference => {
    saveAudioPreferences({ ...DEFAULT_AUDIO_PREFERENCES, autoSpeak: true, [preference]: false });
    await mount(); await send();
    await waitFor(() => expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Measure the window carefully.'));
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it('blocked autoplay does not show a speaking mentor and leaves text and cached replay available', async () => {
    const context = new AudioContextBoundary(); context.state = 'suspended';
    context.resume.mockImplementation(async () => undefined);
    vi.stubGlobal('AudioContext', class { constructor() { return context; } });
    await mount(); await send();
    await waitFor(() => expect(screen.getByText('Tap the microphone to enable audio. Your explanation is saved.')).toBeInTheDocument());
    expect(activeConversation().getByRole('status')).not.toHaveTextContent('Mentor speaking');
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Measure the window carefully.');
    expect(context.sources).toHaveLength(0);
  });
  it('mentor voice transport failure preserves the completed text and never implies playback', async () => {
    fetcher.mockImplementation(async (url: string) => url.endsWith('/conversation/text') ? json({ text: 'Measure the window carefully.' }) : new Response('private upstream payload', { status: 503 }));
    await mount(); await send();
    expect(await screen.findByRole('alert')).toHaveTextContent('Mentor voice is unavailable');
    expect(screen.getByRole('alert')).not.toHaveTextContent('private upstream payload');
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Measure the window carefully.');
    expect(contexts.flatMap(context => context.sources)).toHaveLength(0);
  });
  it('audio settings change device consent without automatically starting the microphone', async () => {
    await mount(); await talk();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Automatically speak new coach replies' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Voice output enabled' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Problem introductions when you start a session' }));
    expect(screen.getByRole('button', { name: 'Test voice' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /Text-only mode/ }));
    expect(captureActive).toBe(false); expect(dispose).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox', { name: /Always voice-on mode/ }));
    expect(screen.getByRole('checkbox', { name: /Text-only mode/ })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Voice output enabled' })).toBeChecked();
    expect(captureActive).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Use Typed Input' }));
    expect(screen.getByRole('checkbox', { name: /Text-only mode/ })).toBeChecked();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('checks microphone locally and discards the setup capture instead of uploading it', async () => {
    vi.spyOn(AudioRecorder.prototype, 'stopMicrophoneCapture').mockResolvedValue(drain.getMockImplementation()!());
    await mount(); vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check Microphone' }));
    await act(async () => Promise.resolve());
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(screen.getByText('Microphone opened and audio frames were captured. You can now record a prediction.')).toBeInTheDocument();
    expect(dispose).toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('explicit code submission shows the unavailable server report without confirming an explanation or inventing execution', async () => {
    const verify = vi.spyOn(api, 'verifyRepair').mockResolvedValue({ revision, session_state: 'READY', learning_state: 'INSPECTING_RESULT', artifact: null, challenge: null, trace_report: null, verification_report: { status: 'EXECUTION_UNAVAILABLE', curated_cases_run: 0, curated_cases_total: 1, generated_cases_run: 0, generated_cases_target: 20, terminal_reason: 'Protocol fixture; worker unavailable', runtime_version: 'protocol-fixture' } });
    const confirm = vi.spyOn(api, 'confirmTurnClaim');
    await mount(); fireEvent.click(screen.getByRole('button', { name: 'Submit code' }));
    await waitFor(() => expect(verify).toHaveBeenCalledOnce());
    expect(screen.getByTestId('verification-status-badge')).toHaveTextContent('EXECUTION_UNAVAILABLE');
    expect(confirm).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('binds the Unicode caption to the speech response rather than a different text reply', async () => {
    fetcher.mockImplementation(async (url: string) => url.endsWith('/conversation/text') ? json({ text: 'Different text reply' }) : new Response(wav.slice(), { headers: { 'X-Coach-Text': encodeURIComponent('Actual தமிழ் 🙂 words') } }));
    await mount(); await send();
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    playbackContext().currentTime = .5;
    await waitFor(() => {
      expect(activeConversation().getByRole('status')).toHaveTextContent('Mentor speaking');
      expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Actual தமிழ்');
    });
    expect(activeConversation().getByLabelText('Current speaker transcript')).not.toHaveTextContent('Different text reply');
  });
  it('a late completion of stopped audio cannot clear a replacement playback', async () => {
    vi.spyOn(api, 'requestVoiceOrientation').mockResolvedValue({ audio: wav.buffer.slice(0) as ArrayBuffer, playbackId: 'same-cached-playback' });
    await mount(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Test voice' }));
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    const oldCompletion = playbackContext().sources[0].onended;
    await waitFor(() => expect(screen.getByRole('button', { name: 'Test voice' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Test voice' }));
    await waitFor(() => expect(playbackContext().sources.length).toBe(2));
    playbackContext().currentTime = .5;
    act(() => oldCompletion?.());
    await waitFor(() => {
      expect(activeConversation().getByRole('status')).toHaveTextContent('Mentor speaking');
      expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Voice is ready.');
    });
  });
  it('shows the exact grounded hint being played and replayed, not the latest chat text', async () => {
    await mount({ learning_state: 'REPAIR_REQUIRED', evidence_artifacts: [artifact], coaching: { display_text: 'Inspect the shrinking boundary.', hint_level: 1 }, active_turn: { state: 'COACH_PROMPT_DELIVERED', turn_id: 'grounded-turn', turn_generation: 1, capture_attempt_id: 1, proposed_claim: null } });
    openTools(); fireEvent.click(screen.getByRole('button', { name: 'Play Coach Voice' }));
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    playbackContext().currentTime = .5;
    await waitFor(() => expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Inspect the'));
    act(() => playbackContext().sources[0].onended?.());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Play Coach Voice' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Play Coach Voice' }));
    await waitFor(() => expect(playbackContext().sources.length).toBe(2));
    playbackContext().currentTime = 1;
    await waitFor(() => expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Inspect the'));
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it('tracks streaming playback while WAV player is idle and clears it only after audio drains', async () => {
    const pcm = btoa(String.fromCharCode(...new Uint8Array(new Int16Array(8000).buffer)));
    fetcher.mockResolvedValue(new Response(`data: ${JSON.stringify({ event_type: 'chunk', request_id: 'protocol-stream', chunk_index: 0, sample_rate: 8000, audio_b64: pcm })}\n\ndata: ${JSON.stringify({ event_type: 'complete', request_id: 'protocol-stream' })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }));
    await mount({ learning_state: 'REPAIR_REQUIRED', evidence_artifacts: [artifact], coaching: { display_text: 'Inspect the shrinking boundary.', hint_level: 1 }, active_turn: { state: 'COACH_PROMPT_DELIVERED', turn_id: 'grounded-turn', turn_generation: 1, capture_attempt_id: 1, proposed_claim: null } });
    openTools(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Playback' }), { target: { value: 'STREAM' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Play Coach Voice' }));
    await waitFor(() => expect(playbackContext()?.sources.length).toBe(1));
    expect(activeConversation().getByRole('status')).not.toHaveTextContent('Mentor speaking');
    playbackContext().currentTime = .53;
    await waitFor(() => expect(activeConversation().getByRole('status')).toHaveTextContent('Mentor speaking'));
    expect(activeConversation().getByLabelText('Current speaker transcript')).toHaveTextContent('Inspect the');
    act(() => playbackContext().sources[0].onended?.());
    await waitFor(() => expect(activeConversation().getByRole('status')).toHaveTextContent('Ready when you are'));
  });
});

it('keeps guided-coaching source with its reply and clears the notice for an introduction', async () => {
  fetcher.mockImplementation(async (url: string) => url.endsWith('/conversation/text')
    ? json({ text: 'Which window boundary would you consider next?', source: 'authored_adaptive_fallback' }) : audio());
  await mount(); await send();
  const notice = 'AI mentor is temporarily unavailable. This response uses guided coaching based on your explanation.';
  expect(await screen.findByText(notice)).toBeInTheDocument();
  const saved = JSON.parse(sessionStorage.getItem(`viva.conversation.${revision.session_id}`)!);
  expect(saved[saved.length - 1].source).toBe('authored_adaptive_fallback');
  fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
  fireEvent.click(screen.getByRole('button', { name: 'Play problem introduction' }));
  await waitFor(() => expect(screen.queryByText(notice)).not.toBeInTheDocument());
});
