import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../services/apiClient';
import { AudioPlayer } from '../services/audioPlayer';
import { CoachingHintFeed, ExecutionComparisonCard, VoiceTurnPanel } from '../components/WorkbenchComponents';
import { createInitialWorkbenchState } from '../state/useSessionStore';
import type { EvidenceArtifact, RevisionRef } from '../types/api';
vi.mock('../components/PythonEditor', () => ({ PythonEditor: ({ value, onChange }: { value: string; onChange: (s: string) => void }) => <textarea aria-label="Python Solution Editor" value={value} onChange={e => onChange(e.target.value)} /> }));
import App from '../App';
const editorBoundary = vi.hoisted(() => ({ set: vi.fn(), reveal: vi.fn(), configure: vi.fn() }));
vi.mock('@monaco-editor/react', () => ({ loader: { config: editorBoundary.configure }, default: ({ value, onChange, onMount, theme }: { value: string; theme: string; onChange: (next: string | undefined) => void; onMount: (editor: unknown) => void }) => <><span>{theme}</span><button onClick={() => onMount({ createDecorationsCollection: () => ({ set: editorBoundary.set }), revealLineInCenterIfOutsideViewport: editorBoundary.reveal })}>Mount local editor</button><button onClick={() => onChange(undefined)}>Clear Monaco value</button><textarea aria-label="Monaco boundary editor" value={value} onChange={e => onChange(e.target.value)} /></> }));
vi.mock('monaco-editor/editor/editor.api.js', () => ({ Range: class { constructor(public startLineNumber: number, public startColumn: number, public endLineNumber: number, public endColumn: number) {} } }));
vi.mock('monaco-editor/languages/definitions/python/register.js', () => ({}));
vi.mock('monaco-editor/editor/editor.worker.js?worker', () => ({ default: class {} }));

const revision: RevisionRef = { session_id: 'message-session', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 1, code_hash: 'c'.repeat(64), turn_generation: 1 };
const artifact: EvidenceArtifact = { artifact_id: 'message-artifact', revision, challenge_id: 'challenge', canonical_input: {}, case_hash: 'case', confirmed_prediction: 2, actual_observation: { kind: 'RETURN', return_value: 2, duration_ms: 1 }, reference_output: 1, prediction_status: 'MATCH', minimization_status: 'NOT_ATTEMPTED', verification_report: { status: 'COUNTEREXAMPLE_CONFIRMED', curated_cases_run: 1, curated_cases_total: 1, generated_cases_run: 0, generated_cases_target: 0, terminal_reason: 'mismatch', runtime_version: 'test' } };
const snapshot: api.SessionSnapshot = { session_id: revision.session_id, state: 'READY', learning_state: 'REPAIR_REQUIRED', spec_acknowledged: true, language_mode: 'en-IN', interaction_mode: 'VOICE', source_code: 'def f(): return 2', revision, challenges: [], evidence_artifacts: [artifact], coaching: { display_text: 'Inspect the boundary — தமிழ்', hint_level: 1 }, active_turn: { state: 'COACH_PROMPT_DELIVERED', turn_id: 'turn', capture_attempt_id: 1, turn_generation: 1, proposed_claim: null } };
function response(level = 1): Response { return new Response(new Uint8Array([level, 2, 3]), { headers: { 'X-Playback-ID': `play-${level}` } }); }
async function restore(patch: Partial<api.SessionSnapshot> = {}): Promise<void> {
  vi.spyOn(api, 'restoreSession').mockResolvedValue({ ...snapshot, ...patch });
  sessionStorage.setItem('vcc-session', JSON.stringify({ id: revision.session_id, token: 'test-token' }));
  render(<App />);
  await screen.findByRole('textbox', { name: 'Python Solution Editor' });
  const transcript = screen.queryByRole('button', { name: 'Transcript & text' });
  if (transcript) fireEvent.click(transcript);
  const tools = screen.getByText('Challenge & practice tools');
  if (!tools.closest('details')?.open) fireEvent.click(tools);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Play Coach Voice' })).toBeEnabled());
}
async function idle(): Promise<void> { await waitFor(() => expect(screen.getByRole('button', { name: 'Play Coach Voice' })).toBeEnabled()); }
function row(level: number) { return within(screen.getByText(new RegExp(`\\[Level ${level} —`)).closest('li')!); }
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); history.replaceState(null, '', '/');
  localStorage.setItem('vcc-product-v1', JSON.stringify({ inputChoice: 'voice' }));
  vi.spyOn(api.apiClient, 'getHealth').mockResolvedValue({ status: 'ok', service: 'test', phase: 'test', version: 'test', custom_code_execution_enabled: false, product_name: 'Coach', product_name_status: 'TEST' });
  vi.spyOn(api.apiClient, 'getBranding').mockResolvedValue({ productName: 'Coach', shortName: 'C', tagline: 'Practice', productNameStatus: 'TEST' });
  vi.spyOn(api.apiClient, 'getExercises').mockResolvedValue([]);
  vi.spyOn(api.apiClient, 'getDemoPresets').mockResolvedValue([]);
  vi.spyOn(api, 'cancelSessionWork').mockResolvedValue({});
  vi.spyOn(api, 'sendPlaybackAck').mockResolvedValue({ session_id: revision.session_id, turn_id: 'turn', turn_generation: 1, playback_status: 'COMPLETED' });
  vi.spyOn(AudioPlayer.prototype, 'playWavBytes').mockResolvedValue({ started: true, fallbackAck: null });
  vi.spyOn(AudioPlayer.prototype, 'unlockAudioFromGesture').mockResolvedValue(true);
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_url, init) => response(JSON.parse(init.body).hint_level)));
});
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('per-message coach playback acceptance', () => {
  it('keeps the real editor accessible, reflects theme changes and clears trace highlights', async () => {
    const { PythonEditor } = await vi.importActual<typeof import('../components/PythonEditor')>('../components/PythonEditor');
    const change = vi.fn();
    document.documentElement.dataset.theme = 'light';
    const { rerender, unmount } = render(<PythonEditor value="private code" onChange={change} highlightedLine={null} />);
    fireEvent.click(screen.getByRole('button', { name: 'Mount local editor' }));
    rerender(<PythonEditor value="private code" onChange={change} highlightedLine={2} />);
    expect(editorBoundary.reveal).toHaveBeenCalledWith(2);
    expect(editorBoundary.set).toHaveBeenLastCalledWith([expect.objectContaining({ options: expect.objectContaining({ className: 'active-trace-line' }) })]);
    fireEvent.click(screen.getByRole('button', { name: 'Clear Monaco value' })); expect(change).toHaveBeenCalledWith('');
    fireEvent.change(screen.getByRole('textbox', { name: 'Monaco boundary editor' }), { target: { value: 'new code' } }); expect(change).toHaveBeenCalledWith('new code');
    await act(async () => { document.documentElement.dataset.theme = 'dark'; });
    expect(screen.getByText('vs-dark')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use Accessible Plain Text Editor' }));
    expect(screen.getByRole('textbox', { name: 'Python Solution Editor' })).toHaveValue('private code');
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'accessible repair' } }); expect(change).toHaveBeenCalledWith('accessible repair');
    fireEvent.click(screen.getByRole('button', { name: 'Use Monaco Editor' }));
    rerender(<PythonEditor value="private code" onChange={change} highlightedLine={null} />);
    expect(editorBoundary.set).toHaveBeenLastCalledWith([]);
    unmount(); document.documentElement.dataset.theme = 'light';
  });
  it.each([false, true])('plays or degrades server-cached streams without caller text (provider error %s)', async providerError => {
    const closed = vi.fn().mockResolvedValue(undefined); const sourceStarted = vi.fn();
    class Context {
      state = 'running'; currentTime = 0; destination = {}; close = closed;
      createBuffer(_channels: number, frames: number, rate: number) { return { duration: frames / rate, getChannelData: () => new Float32Array(frames) }; }
      createBufferSource() { const node = { buffer: null, onended: null as (() => void) | null, connect: vi.fn(), disconnect: vi.fn(), stop: vi.fn(), start: () => { sourceStarted(); queueMicrotask(() => node.onended?.()); } }; return node; }
    }
    vi.stubGlobal('AudioContext', Context);
    const events = providerError ? [{ event_type: 'start', playback_id: 'stream-1' }, { event_type: 'error' }] : [{ event_type: 'chunk', playback_id: 'stream-1', audio_b64: 'AQACAAMA', sample_rate: 16000, chunk_index: 0 }, { event_type: 'complete' }];
    vi.mocked(fetch).mockResolvedValue(new Response(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream', 'X-Playback-ID': 'stream-1' } }));
    await restore(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByText('Technical diagnostics'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Playback' }), { target: { value: 'STREAM' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(row(1).getByRole('button', { name: 'Play message' }));
    if (providerError) expect(await screen.findByRole('alert')).toHaveTextContent('Voice provider stopped the stream');
    else { await idle(); expect(sourceStarted).toHaveBeenCalledOnce(); expect(closed).toHaveBeenCalledOnce(); }
    expect(api.sendPlaybackAck).toHaveBeenCalledWith(revision.session_id, expect.objectContaining({ playback_status: providerError ? 'READ_TEXT_FALLBACK' : 'COMPLETED', revision }));
    expect(vi.mocked(fetch).mock.calls[0][0]).toContain('/speech/tts-stream');
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual({ revision, artifact_id: artifact.artifact_id, hint_level: 1 });
    expect(row(1).getByRole('button', { name: 'Play message' })).toBeEnabled();
  });
  it('keeps audio settings keyboard-contained and restores focus when dismissed', async () => {
    await restore(); const settings = screen.getByRole('button', { name: 'Settings' }); settings.focus(); fireEvent.click(settings);
    const close = screen.getByRole('button', { name: 'Close settings' }); expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: 'Delete Session' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Delete Session' }), { key: 'Tab' }); expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: 'Escape' }); expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(settings).toHaveFocus();
  });
  it('uses learner-readable claim names and keeps raw evidence identity in advanced details', () => {
    const state = { ...createInitialWorkbenchState(), proposedClaim: { claim_type: 'DOMAIN_VALIDITY_CLAIM' as const, target_spec_version: 'v1_positive_only' as const, polarity: 'AFFIRMATIVE' as const, extraction_method: 'DETERMINISTIC' as const } };
    render(<><VoiceTurnPanel state={state} onSubmitTranscript={vi.fn()} onStartOrRerecordVoice={vi.fn()} onBargeInStop={vi.fn()} onChangeEditableTranscript={vi.fn()} onConfirmClaimAndExecute={vi.fn()} /><ExecutionComparisonCard artifact={artifact} isStale={false} /></>);
    expect(screen.getByLabelText('Editable claim interpretation')).toHaveTextContent('Domain assumption');
    expect(screen.getByLabelText('Editable claim interpretation')).not.toHaveTextContent('DOMAIN_VALIDITY_CLAIM');
    expect(screen.getByText(/Case identity:/).closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(/Completed stages:/).closest('details')).not.toHaveAttribute('open');
  });
  it('ignores an old playback acknowledgement rejection after navigation', async () => {
    let reject!: (err: Error) => void;
    vi.mocked(api.sendPlaybackAck).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    vi.mocked(AudioPlayer.prototype.playWavBytes).mockImplementationOnce(async p => {
      p.onEnded?.({ session_id: p.sessionId, turn_id: p.turnId, turn_generation: p.turnGeneration, playback_id: p.playbackId, playback_status: 'COMPLETED', played_duration_ms: 20 });
      return { started: true, fallbackAck: null };
    });
    await restore(); fireEvent.click(row(1).getByRole('button', { name: 'Play message' })); await idle();
    expect(api.sendPlaybackAck).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Problem library' }));
    await act(async () => reject(new Error('Old private playback failed')));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('plays unlocked hints by authorized identity, replays earlier WAVs locally, and preserves hint sequence', async () => {
    const hint = vi.spyOn(api, 'requestCoachingHint').mockImplementation(async (_id, req) => ({ display_text: `Hint ${req.requested_level}`, hint_level: req.requested_level }));
    await restore();
    expect(row(1).getByRole('button', { name: 'Play message' })).toBeEnabled();
    fireEvent.click(row(1).getByRole('button', { name: 'Play message' })); await idle();
    expect(row(1).getByRole('button', { name: 'Replay message' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Level 2 Hint' }));
    await screen.findByText(/Hint 2/);
    fireEvent.click(row(2).getByRole('button', { name: 'Play message' })); await idle();
    fireEvent.click(row(1).getByRole('button', { name: 'Replay message' })); await idle();
    expect(fetch).toHaveBeenCalledTimes(2);
    const requests = vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(String(init?.body)));
    expect(requests).toEqual([1, 2].map(hint_level => ({ revision, artifact_id: artifact.artifact_id, hint_level })));
    const calls = vi.mocked(AudioPlayer.prototype.playWavBytes).mock.calls;
    expect(new Uint8Array(calls[2][0].wavBytes as ArrayBuffer)).toEqual(new Uint8Array([1, 2, 3]));
    expect(screen.getByRole('button', { name: 'Level 3 Hint' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Level 1 Hint' })).toBeDisabled();
    expect(hint).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Play Coach Voice' })); await idle();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each(['Mute voice playback', 'Text-only mode (no microphone or voice requests)', 'Voice output enabled', 'zero volume'])('makes no TTS requests with %s', async label => {
    await restore(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    if (label === 'zero volume') fireEvent.change(screen.getByRole('slider', { name: 'Voice volume' }), { target: { value: '0' } });
    else fireEvent.click(screen.getByRole('checkbox', { name: label }));
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    expect(row(1).getByRole('button', { name: 'Play message' })).toBeDisabled();
    fireEvent.click(row(1).getByRole('button', { name: 'Play message' }));
    expect(fetch).not.toHaveBeenCalled();
  });
  it('surfaces provider errors without falsely marking the message replayable', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('', { status: 503 }));
    await restore(); fireEvent.click(row(1).getByRole('button', { name: 'Play message' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Voice playback unavailable (HTTP 503)');
    expect(row(1).getByRole('button', { name: 'Play message' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Replay message' })).not.toBeInTheDocument();
  });
  it('rejects late audio and aborts the request when code becomes stale', async () => {
    let resolve!: (response: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await restore(); fireEvent.click(row(1).getByRole('button', { name: 'Play message' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByRole('textbox', { name: 'Python Solution Editor' }), { target: { value: 'def f(): return 3' } });
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
    await act(async () => resolve(response()));
    expect(AudioPlayer.prototype.playWavBytes).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Replay last voice' })).toBeDisabled();
  });
  it('retains blocked WAVs for honest local replay and completes acknowledgements', async () => {
    vi.mocked(AudioPlayer.prototype.playWavBytes).mockImplementationOnce(async p => {
      const ack = AudioPlayer.buildReadTextFallbackAck(p.sessionId, p.turnId, p.turnGeneration, p.playbackId, p.revision);
      p.onAutoplayBlocked?.(ack); return { started: false, fallbackAck: ack };
    }).mockImplementation(async p => {
      p.onEnded?.({ session_id: p.sessionId, turn_id: p.turnId, turn_generation: p.turnGeneration, playback_id: p.playbackId, playback_status: 'COMPLETED', played_duration_ms: 20 });
      return { started: true, fallbackAck: null };
    });
    await restore(); fireEvent.click(row(1).getByRole('button', { name: 'Play message' })); await idle();
    fireEvent.click(row(1).getByRole('button', { name: 'Replay message' })); await idle();
    expect(fetch).toHaveBeenCalledOnce();
    expect(api.sendPlaybackAck).toHaveBeenCalledOnce();
    expect(api.sendPlaybackAck).toHaveBeenCalledWith(revision.session_id, expect.objectContaining({ playback_status: 'READ_TEXT_FALLBACK', revision }));
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    expect(screen.getByText(/Playback blocked/)).toBeInTheDocument();
  });
  it('auto-speaks only the newly unlocked current hint and replays it without generation', async () => {
    vi.spyOn(api, 'requestCoachingHint').mockResolvedValue({ display_text: 'Auto hint 2', hint_level: 2 });
    await restore(); fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Automatically speak new coach replies' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Level 2 Hint' }));
    await waitFor(() => expect(row(2).getByRole('button', { name: 'Replay message' })).toBeEnabled());
    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toContain('"hint_level":2');
    fireEvent.click(row(2).getByRole('button', { name: 'Replay message' })); await idle();
    expect(fetch).toHaveBeenCalledOnce();
  });
  it('discards message audio on navigation rather than reusing it after restore', async () => {
    await restore(); fireEvent.click(row(1).getByRole('button', { name: 'Play message' })); await idle();
    fireEvent.click(screen.getByRole('button', { name: 'Problem library' }));
    history.replaceState(null, '', '/');
    cleanup(); render(<App />);
    await screen.findByRole('textbox', { name: 'Python Solution Editor' });
    expect(row(1).getByRole('button', { name: 'Play message' })).toBeEnabled();
    fireEvent.click(row(1).getByRole('button', { name: 'Play message' })); await idle();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('clears audio when deleting practice and never replays private deleted messages', async () => {
    const remove = vi.spyOn(api, 'deleteSession').mockResolvedValue({ session_id: revision.session_id, deleted_at: '', limitations: '' });
    await restore(); fireEvent.click(row(1).getByRole('button', { name: 'Play message' })); await idle();
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete Session' }));
    await waitFor(() => expect(remove).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay last voice' })).toBeDisabled());
    expect(screen.queryByRole('button', { name: 'Replay message' })).not.toBeInTheDocument();
  });
  it('keeps stale feed entries noninteractive without unlocking another hint', () => {
    const state = { ...createInitialWorkbenchState(), sessionId: revision.session_id, revision, activeTurnId: 'turn', activeArtifact: artifact, coachingHistory: [{ hintLevel: 1, displayText: 'Old hint', sourceMode: 'SERVER', pointedLine: null, pointedEventId: null, stale: true }] };
    const onPlayMessage = vi.fn();
    render(<CoachingHintFeed state={state} onRequestHintLevel={vi.fn()} onPlayMessage={onPlayMessage} />);
    expect(screen.getByRole('button', { name: 'Play message' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Play message' }));
    expect(onPlayMessage).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Level 2 Hint' })).toBeDisabled();
  });
});
