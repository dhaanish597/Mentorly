import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode, useState } from 'react';
import { StudioVoice, type StudioVoiceEvent } from '../StudioVoice';

const recorder = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), dispose: vi.fn() }));
vi.mock('../services/audioRecorder', () => ({
  AudioRecorder: class {
    startMicrophoneCapture = recorder.start;
    stopMicrophoneCapture = recorder.stop;
    dispose = recorder.dispose;
  },
}));
const session = { id: 's', token: 't', workspace: { id: 'w', token: 'wtoken' } };
const coach = (sequence = 1, epoch = 1) => ({ sequence, type: 'coach.action', payload: { epoch, text: 'Explain the trade-off.' } });
const feedback = (sequence = 2, epoch = 1): StudioVoiceEvent => ({ sequence, type: 'feedback.ready', payload: { epoch, question: 'What changes if a replica fails?' } });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const stt = (text: unknown = 'voice text', epoch = 1) => json({ normalized_transcript: text, epoch });
const tts = (epoch = 1) => json({ audio_base64: 'AQI=', epoch });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let request: ReturnType<typeof vi.fn>;
let play: ReturnType<typeof vi.spyOn>;
let pause: ReturnType<typeof vi.spyOn>;
let createUrl: ReturnType<typeof vi.fn<(obj: Blob | MediaSource) => string>>;
let revokeUrl: ReturnType<typeof vi.fn<(url: string) => void>>;

beforeEach(() => {
  recorder.start.mockResolvedValue(undefined);
  recorder.stop.mockResolvedValue({ wavBytes: new Uint8Array([1, 2]) });
  recorder.dispose.mockResolvedValue(undefined);
  request = vi.fn();
  vi.stubGlobal('fetch', request);
  createUrl = vi.fn<(obj: Blob | MediaSource) => string>().mockReturnValue('blob:coach-1');
  revokeUrl = vi.fn<(url: string) => void>();
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = createUrl;
    static revokeObjectURL = revokeUrl;
  });
  play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function mount(events: StudioVoiceEvent[] = [], onTranscript = vi.fn()) {
  return render(<StudioVoice session={session} epoch={1} events={events} onTranscript={onTranscript} />);
}
async function talk() {
  fireEvent.click(screen.getByRole('button', { name: /^(Enable voice and talk|Talk)$/ }));
  await screen.findByRole('button', { name: 'Stop and transcribe' });
}
async function transcribe() {
  await talk();
  fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }));
  await waitFor(() => expect(request).toHaveBeenCalled());
}
async function enableCoach() {
  fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
  await waitFor(() => expect(play).toHaveBeenCalled());
}

describe('voice-first controls and consent', () => {
  it('keeps the microphone visible with two compact controls and no duplicate draft', () => {
    const view = mount([coach()]);
    expect(screen.getByRole('button', { name: 'Enable voice and talk' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Enable coach speech' })).toBeTruthy();
    expect(screen.getAllByRole('button')).toHaveLength(2);
    expect(view.container.querySelector('details')).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByRole('status').textContent).toMatch(/idle/i);
    expect(screen.getByText(/consent.*Gnani/i)).toBeTruthy();
    expect(request).not.toHaveBeenCalled();
    expect(recorder.start).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it('requests microphone permission only after a consent gesture and never enables coach autoplay by talking', async () => {
    const permission = deferred<void>();
    recorder.start.mockReturnValue(permission.promise);
    const view = mount([coach()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    expect(screen.getByRole('status').textContent).toMatch(/requesting.*permission/i);
    expect(request).not.toHaveBeenCalled();
    await act(async () => permission.resolve());
    expect(screen.getByRole('status').textContent).toMatch(/recording/i);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), coach(2)]} onTranscript={vi.fn()} />);
    expect(request).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it('moves ASR to the sole editable parent draft, requiring review and explicit confirmation', async () => {
    request.mockResolvedValue(stt('தமிழ் 🙂 SQL \'quoted\''));
    const submit = vi.fn();
    function Parent() {
      const [draft, setDraft] = useState('');
      return <><StudioVoice session={session} epoch={1} events={[]} onTranscript={setDraft} />
        <label>Your explanation<textarea value={draft} onChange={event => setDraft(event.target.value)} /></label>
        <button onClick={() => { if (window.confirm('Submit reviewed explanation?')) submit(draft); }}>Confirm explanation</button></>;
    }
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<Parent />);
    await transcribe();
    await waitFor(() => expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('தமிழ் 🙂 SQL \'quoted\''));
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    expect(screen.getByRole('status').textContent).toMatch(/review.*confirm.*nothing.*submitted/i);
    expect(submit).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'reviewed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm explanation' }));
    expect(submit).toHaveBeenCalledWith('reviewed');
    const [url, options] = request.mock.calls[0];
    expect(url).toBe('/api/v1/studio/sessions/s/speech/stt');
    expect(options.headers.Authorization).toBe('Bearer t');
    expect(JSON.parse(options.body)).toEqual({ epoch: 1, audio_base64: 'AQI=', language_mode: 'en-IN' });
  });

  it('shows one cancel control while transcribing and aborts without applying a late result', async () => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    const apply = vi.fn();
    mount([], apply);
    await transcribe();
    expect(screen.getByRole('status').textContent).toMatch(/transcribing.*Gnani/i);
    expect(screen.getAllByRole('button', { name: 'Cancel voice' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => response.resolve(stt('cancelled')));
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toMatch(/idle.*stopped/i);
  });
});

describe('studio voice race safety', () => {
  it('disposes a microphone whose permission resolves after stop', async () => {
    const permission = deferred<void>();
    recorder.start.mockReturnValue(permission.promise);
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    await act(async () => permission.resolve());
    expect(recorder.dispose).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Stop and transcribe' })).toBeNull();
    expect(screen.getByRole('status').textContent).toMatch(/idle.*stopped/i);
  });

  it('drops a transcription that resolves after the session epoch changes', async () => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    const apply = vi.fn();
    const view = mount([], apply);
    await transcribe();
    view.rerender(<StudioVoice session={session} epoch={2} events={[]} onTranscript={apply} />);
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => response.resolve(stt('stale')));
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toMatch(/idle/i);
  });

  it('drops a recording stopped after cancellation before any provider call', async () => {
    const captured = deferred<{ wavBytes: Uint8Array }>();
    recorder.stop.mockReturnValue(captured.promise);
    mount();
    await talk();
    fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    await act(async () => captured.resolve({ wavBytes: new Uint8Array([1]) }));
    expect(request).not.toHaveBeenCalled();
    expect(recorder.dispose).toHaveBeenCalled();
  });

  it('cleans up a late microphone permission on unmount', async () => {
    const permission = deferred<void>();
    recorder.start.mockReturnValue(permission.promise);
    const view = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    view.unmount();
    await act(async () => permission.resolve());
    expect(recorder.dispose).toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });

  it('ignores stale response epochs even when the request is still current', async () => {
    request.mockResolvedValue(stt('old', 0));
    const apply = vi.fn();
    mount([], apply);
    await transcribe();
    await screen.findByRole('button', { name: 'Talk' });
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toMatch(/error.*stale/i);
  });
});

describe('real Gnani coach audio and bounded replay', () => {
  it('requires a separate speech gesture, authenticates TTS, and replays without repeated provider costs', async () => {
    request.mockImplementation(() => Promise.resolve(tts()));
    mount([coach()]);
    await enableCoach();
    expect(screen.getByRole('status').textContent).toMatch(/speaking/i);
    expect(screen.getAllByRole('button', { name: 'Stop voice' })).toHaveLength(1);
    const [url, options] = request.mock.calls[0];
    expect(url).toBe('/api/v1/studio/sessions/s/speech/tts');
    expect(options.headers.Authorization).toBe('Bearer t');
    expect(JSON.parse(options.body)).toEqual({ epoch: 1, event_sequence: 1 });
    fireEvent.click(screen.getByRole('button', { name: 'Stop voice' }));
    fireEvent.click(screen.getByRole('button', { name: 'Replay coach' }));
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(request).toHaveBeenCalledTimes(1);
    expect(createUrl).toHaveBeenCalledTimes(1);
  });

  it('autoplays only fresh coach events after speech is enabled and ignores repeated snapshots', async () => {
    request.mockImplementation(() => Promise.resolve(tts()));
    const view = mount([coach()]);
    await enableCoach();
    fireEvent.ended(view.container.querySelector('audio')!);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), coach(2)]} onTranscript={vi.fn()} />);
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    fireEvent.ended(view.container.querySelector('audio')!);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), coach(2)]} onTranscript={vi.fn()} />);
    expect(request).toHaveBeenCalledTimes(2);
    expect(play).toHaveBeenCalledTimes(2);
  });

  it('can enable speech before a coach event exists without calling the provider', async () => {
    request.mockResolvedValue(tts());
    const view = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    expect(request).not.toHaveBeenCalled();
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} />);
    await waitFor(() => expect(play).toHaveBeenCalledOnce());
  });

  it('pauses previous playback for a fresh event and revokes all cached URLs on epoch change', async () => {
    createUrl.mockReturnValueOnce('blob:one').mockReturnValueOnce('blob:two');
    request.mockImplementation(() => Promise.resolve(tts()));
    const view = mount([coach()]);
    await enableCoach();
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), coach(2)]} onTranscript={vi.fn()} />);
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(pause).toHaveBeenCalled();
    view.rerender(<StudioVoice session={session} epoch={2} events={[]} onTranscript={vi.fn()} />);
    expect(revokeUrl).toHaveBeenCalledWith('blob:one');
    expect(revokeUrl).toHaveBeenCalledWith('blob:two');
    expect(request).toHaveBeenCalledTimes(2);
  });

  it.each(['cancel', 'epoch', 'session', 'unmount'] as const)('never plays late TTS after %s', async change => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    const view = mount([coach()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    await waitFor(() => expect(request).toHaveBeenCalled());
    if (change === 'cancel') fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    if (change === 'epoch') view.rerender(<StudioVoice session={session} epoch={2} events={[coach(2, 2)]} onTranscript={vi.fn()} />);
    if (change === 'session') view.rerender(<StudioVoice session={{ ...session, id: 'other' }} epoch={1} events={[coach()]} onTranscript={vi.fn()} />);
    if (change === 'unmount') view.unmount();
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => response.resolve(tts()));
    expect(play).not.toHaveBeenCalled();
    expect(createUrl).not.toHaveBeenCalled();
  });

  it('recovers autoplay rejection with an explicit cached replay gesture', async () => {
    request.mockResolvedValue(tts());
    play.mockRejectedValueOnce(new DOMException('Gesture required', 'NotAllowedError'));
    mount([coach()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*replay/i));
    fireEvent.click(screen.getByRole('button', { name: 'Replay coach' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/speaking/i));
    expect(request).toHaveBeenCalledOnce();
  });

  it('revokes cached URLs and pauses audio on unmount', async () => {
    request.mockResolvedValue(tts());
    const view = mount([coach()]);
    await enableCoach();
    view.unmount();
    expect(revokeUrl).toHaveBeenCalledWith('blob:coach-1');
    expect(pause).toHaveBeenCalled();
  });

  it('ignores non-coach, wrong-epoch and out-of-order events', async () => {
    request.mockResolvedValue(tts());
    const view = mount([coach(5)]);
    await enableCoach();
    fireEvent.ended(view.container.querySelector('audio')!);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(4), coach(8, 2), { ...coach(9), type: 'learner.turn' }, coach(5)]} onTranscript={vi.fn()} />);
    expect(request).toHaveBeenCalledOnce();
  });
});

describe('eligible feedback questions share Gnani coach speech', () => {
  it('chooses the newest eligible feedback question and caches replay without sending arbitrary text', async () => {
    request.mockImplementation(() => Promise.resolve(tts()));
    mount([feedback(3), coach(1), feedback(2)]);
    await enableCoach();
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ epoch: 1, event_sequence: 3 });
    expect(request.mock.calls[0][1].headers.Authorization).toBe('Bearer t');
    fireEvent.click(screen.getByRole('button', { name: 'Stop voice' }));
    fireEvent.click(screen.getByRole('button', { name: 'Replay coach' }));
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(request).toHaveBeenCalledOnce();
  });

  it('requires a speech gesture for feedback and autoplays only newer eligible questions after it', async () => {
    request.mockImplementation(() => Promise.resolve(tts()));
    const view = mount([coach()]);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), feedback(2)]} onTranscript={vi.fn()} />);
    expect(request).not.toHaveBeenCalled();
    await enableCoach();
    expect(JSON.parse(request.mock.calls[0][1].body).event_sequence).toBe(2);
    fireEvent.ended(view.container.querySelector('audio')!);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), feedback(2), feedback(3)]} onTranscript={vi.fn()} />);
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(JSON.parse(request.mock.calls[1][1].body).event_sequence).toBe(3);
    fireEvent.ended(view.container.querySelector('audio')!);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), feedback(2), feedback(3)]} onTranscript={vi.fn()} />);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it.each([undefined, null, '', '   ', 123, {}, []])('ignores a feedback question with invalid text %j', async question => {
    request.mockResolvedValue(tts());
    const invalid = { ...feedback(), payload: { epoch: 1, question } } as unknown as StudioVoiceEvent;
    mount([coach(), invalid]);
    await enableCoach();
    expect(JSON.parse(request.mock.calls[0][1].body).event_sequence).toBe(1);
  });

  it('ignores missing payloads, wrong epochs, feedback text-only events, and arbitrary event questions', async () => {
    request.mockResolvedValue(tts());
    mount([coach(), { sequence: 2, type: 'feedback.ready' }, feedback(3, 2),
      { ...coach(4), type: 'feedback.ready' }, { ...feedback(5), type: 'learner.turn' }]);
    await enableCoach();
    expect(JSON.parse(request.mock.calls[0][1].body).event_sequence).toBe(1);
  });

  it('drops a feedback TTS response after the epoch changes', async () => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    const view = mount([coach(), feedback()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    expect(JSON.parse(request.mock.calls[0][1].body).event_sequence).toBe(2);
    view.rerender(<StudioVoice session={session} epoch={2} events={[feedback(3, 2)]} onTranscript={vi.fn()} />);
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => response.resolve(tts()));
    expect(play).not.toHaveBeenCalled();
    expect(createUrl).not.toHaveBeenCalled();
  });
});

describe('25-second capture deadline uses the editable-draft workflow', () => {
  async function startTimedCapture() {
    fireEvent.click(screen.getByRole('button', { name: /^(Enable voice and talk|Talk)$/ }));
    await act(async () => Promise.resolve());
    expect(screen.getByRole('button', { name: 'Stop and transcribe' })).toBeTruthy();
  }

  it('automatically stops at 25 seconds, transcribes once, and preserves the draft for explicit review', async () => {
    vi.useFakeTimers();
    request.mockResolvedValue(stt('captured explanation'));
    const submit = vi.fn();
    function Parent() {
      const [draft, setDraft] = useState('');
      return <><StudioVoice session={session} epoch={1} events={[]} onTranscript={setDraft} />
        <label>Your explanation<textarea value={draft} onChange={event => setDraft(event.target.value)} /></label>
        <button onClick={() => submit(draft)}>Confirm explanation</button></>;
    }
    render(<Parent />);
    await startTimedCapture();
    expect(screen.getByRole('status').textContent).toMatch(/25 seconds/i);
    await act(async () => vi.advanceTimersByTimeAsync(24_999));
    expect(recorder.stop).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(recorder.stop).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledOnce();
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('captured explanation');
    expect(screen.getByRole('status').textContent).toMatch(/review.*confirm.*nothing.*submitted/i);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'reviewed timed draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm explanation' }));
    expect(submit).toHaveBeenCalledWith('reviewed timed draft');
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(request).toHaveBeenCalledOnce();
  });

  it('starts the deadline after permission resolves, not while waiting for permission', async () => {
    vi.useFakeTimers();
    const permission = deferred<void>();
    recorder.start.mockReturnValue(permission.promise);
    request.mockResolvedValue(stt());
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    await act(async () => vi.advanceTimersByTimeAsync(40_000));
    expect(recorder.stop).not.toHaveBeenCalled();
    await act(async () => permission.resolve());
    await act(async () => vi.advanceTimersByTimeAsync(24_999));
    expect(recorder.stop).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(recorder.stop).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledOnce();
  });

  it.each(['cancel', 'epoch', 'disabled', 'unmount'] as const)('clears the capture deadline after %s', async change => {
    vi.useFakeTimers();
    const view = mount();
    await startTimedCapture();
    expect(vi.getTimerCount()).toBe(1);
    if (change === 'cancel') fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    if (change === 'epoch') view.rerender(<StudioVoice session={session} epoch={2} events={[]} onTranscript={vi.fn()} />);
    if (change === 'disabled') view.rerender(<StudioVoice session={session} epoch={1} events={[]} onTranscript={vi.fn()} disabled />);
    if (change === 'unmount') view.unmount();
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(recorder.stop).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });

  it('clears the deadline on a manual stop without a duplicate stop or STT call', async () => {
    vi.useFakeTimers();
    request.mockResolvedValue(stt());
    mount();
    await startTimedCapture();
    fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }));
    await act(async () => Promise.resolve());
    expect(vi.getTimerCount()).toBe(0);
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(recorder.stop).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledOnce();
  });
});

describe('latest delivery callback and fresh epoch replies', () => {
  it('delivers ASR to the latest callback when the parent changes it during transcription', async () => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    const original = vi.fn();
    const current = vi.fn();
    const view = mount([], original);
    await transcribe();
    view.rerender(<StudioVoice session={session} epoch={1} events={[]} onTranscript={current} />);
    await act(async () => response.resolve(stt('new speech')));
    expect(original).not.toHaveBeenCalled();
    expect(current).toHaveBeenCalledExactlyOnceWith('new speech');
    expect(request).toHaveBeenCalledOnce();
  });

  it('uses the current callback even when automatic capture stop closes over an earlier render', async () => {
    vi.useFakeTimers();
    request.mockResolvedValue(stt('timed speech'));
    const original = vi.fn();
    const current = vi.fn();
    const view = mount([], original);
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    await act(async () => Promise.resolve());
    view.rerender(<StudioVoice session={session} epoch={1} events={[]} onTranscript={current} />);
    await act(async () => vi.advanceTimersByTimeAsync(25_000));
    expect(original).not.toHaveBeenCalled();
    expect(current).toHaveBeenCalledExactlyOnceWith('timed speech');
    expect(recorder.stop).toHaveBeenCalledOnce();
  });

  it.each(['coach', 'feedback'] as const)('autoplays one unseen %s reply on a same-session epoch transition after speech consent', async kind => {
    request.mockResolvedValue(tts(2));
    const view = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    expect(request).not.toHaveBeenCalled();
    const next = kind === 'coach' ? coach(1, 2) : feedback(1, 2);
    view.rerender(<StudioVoice session={session} epoch={2} events={[next]} onTranscript={vi.fn()} />);
    await waitFor(() => expect(play).toHaveBeenCalledOnce());
    expect(request).toHaveBeenCalledOnce();
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ epoch: 2, event_sequence: 1 });
    fireEvent.ended(view.container.querySelector('audio')!);
    view.rerender(<StudioVoice session={session} epoch={2} events={[{ ...next }]} onTranscript={vi.fn()} />);
    expect(request).toHaveBeenCalledOnce();
    expect(play).toHaveBeenCalledOnce();
  });

  it('does not autoplay historical replies on initial session load or reuse consent in another session', async () => {
    request.mockImplementation(() => Promise.resolve(tts(2)));
    const view = render(<StudioVoice session={session} epoch={2} events={[coach(7, 2), feedback(8, 2)]} onTranscript={vi.fn()} />);
    expect(request).not.toHaveBeenCalled();
    await enableCoach();
    expect(JSON.parse(request.mock.calls[0][1].body).event_sequence).toBe(8);
    view.rerender(<StudioVoice session={{ ...session, id: 'another' }} epoch={3} events={[feedback(9, 3)]} onTranscript={vi.fn()} />);
    expect(request).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Enable coach speech' })).toBeTruthy();
  });

  it('does not autoplay a reply already present in initial history when its epoch is revisited', async () => {
    request.mockResolvedValue(tts(2));
    const knownHistory = [coach(9, 2)];
    const view = mount(knownHistory);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    expect(request).not.toHaveBeenCalled();
    view.rerender(<StudioVoice session={session} epoch={2} events={knownHistory} onTranscript={vi.fn()} />);
    await act(async () => Promise.resolve());
    expect(request).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it('keeps historical lower-sequence replies silent across epoch transitions', async () => {
    request.mockResolvedValue(tts());
    const view = mount([coach(10)]);
    await enableCoach();
    view.rerender(<StudioVoice session={session} epoch={2} events={[coach(9, 2)]} onTranscript={vi.fn()} />);
    expect(request).toHaveBeenCalledOnce();
    expect(play).toHaveBeenCalledOnce();
    expect(revokeUrl).toHaveBeenCalledWith('blob:coach-1');
  });
});

describe('additional concurrency and resource regression evals', () => {
  it('does not touch browser playback when no audio source has ever been requested', () => {
    const view = mount();
    view.unmount();
    expect(pause).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });

  it('does not duplicate consent or provider calls under StrictMode effect replay', async () => {
    request.mockResolvedValue(tts());
    render(<StrictMode><StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} /></StrictMode>);
    expect(request).not.toHaveBeenCalled();
    await enableCoach();
    expect(request).toHaveBeenCalledOnce();
    expect(play).toHaveBeenCalledOnce();
  });

  it('fences late permissions after an epoch change and permits a fresh capture', async () => {
    const permission = deferred<void>();
    recorder.start.mockReturnValueOnce(permission.promise);
    const view = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    view.rerender(<StudioVoice session={session} epoch={2} events={[]} onTranscript={vi.fn()} />);
    await talk();
    await act(async () => permission.resolve());
    expect(screen.getByRole('status').textContent).toMatch(/recording/i);
    expect(recorder.start).toHaveBeenCalledTimes(2);
    expect(recorder.dispose).toHaveBeenCalled();
  });

  it('fences capability-token changes and requires speech consent again', async () => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    const view = mount([coach()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    view.rerender(<StudioVoice session={{ ...session, token: 'new' }} epoch={1} events={[coach(), coach(2)]} onTranscript={vi.fn()} />);
    await act(async () => response.resolve(tts()));
    expect(play).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Enable coach speech' })).toBeTruthy();
    expect(request).toHaveBeenCalledOnce();
  });

  it.each(['resolve', 'reject'] as const)('ignores a late media-play promise %s after stopping', async outcome => {
    const playback = deferred<void>();
    play.mockReturnValue(playback.promise);
    request.mockResolvedValue(tts());
    mount([coach()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    await act(async () => { if (outcome === 'resolve') playback.resolve(); else playback.reject(new Error('late playback failure')); });
    expect(screen.getByRole('status').textContent).toMatch(/idle.*stopped/i);
    expect(pause).toHaveBeenCalled();
    expect(request).toHaveBeenCalledOnce();
  });

  it('waits to autoplay a fresh coach event until the microphone draft is transcribed', async () => {
    request.mockImplementation((path: string) => Promise.resolve(path.endsWith('/stt') ? stt() : tts()));
    const apply = vi.fn();
    const view = mount([coach()], apply);
    await enableCoach();
    fireEvent.ended(view.container.querySelector('audio')!);
    await talk();
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach(), coach(2)]} onTranscript={apply} />);
    expect(request).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }));
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(apply).toHaveBeenCalledWith('voice text');
    expect(request.mock.calls.map(call => call[0].split('/').at(-1))).toEqual(['tts', 'stt', 'tts']);
  });

  it('does not turn an aborted fetch rejection into an error', async () => {
    const response = deferred<Response>();
    request.mockReturnValue(response.promise);
    mount();
    await transcribe();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel voice' }));
    await act(async () => response.reject(new DOMException('Cancelled', 'AbortError')));
    expect(screen.getByRole('status').textContent).toMatch(/idle.*stopped/i);
  });

  it.each(['onDeviceLost', 'onBackpressureLimitReached'] as const)('releases capture on %s and ignores stale device callbacks', async name => {
    mount();
    await talk();
    const options = recorder.start.mock.calls[0][0];
    act(() => options[name]());
    expect(screen.getByRole('status').textContent).toMatch(/error/i);
    expect(recorder.dispose).toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
    await talk();
    act(() => options[name]());
    expect(screen.getByRole('status').textContent).toMatch(/recording/i);
  });

  it('selects the newest valid coach in a 10,000-event history without mutating the input', async () => {
    request.mockResolvedValue(tts());
    const events = Array.from({ length: 10_000 }, (_, index) => Object.freeze(coach(index)));
    events.push(Object.freeze(coach(Number.NaN)));
    Object.freeze(events);
    mount(events);
    await enableCoach();
    expect(JSON.parse(request.mock.calls[0][1].body).event_sequence).toBe(9999);
    expect(events[0].sequence).toBe(0);
  });

  it.each([0, 1_048_577])('rejects a recording with %i bytes before the provider boundary', async length => {
    recorder.stop.mockResolvedValue({ wavBytes: new Uint8Array(length) });
    mount();
    await talk();
    fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*transcription/i));
    expect(request).not.toHaveBeenCalled();
  });

  it('encodes the maximum supported capture in chunks without changing its bytes', async () => {
    const bytes = new Uint8Array(1_048_576).fill(128);
    recorder.stop.mockResolvedValue({ wavBytes: bytes });
    request.mockResolvedValue(stt('long recording'));
    const apply = vi.fn();
    mount([], apply);
    await transcribe();
    await waitFor(() => expect(apply).toHaveBeenCalledWith('long recording'));
    const encoded = JSON.parse(request.mock.calls[0][1].body).audio_base64;
    expect(atob(encoded)).toHaveLength(bytes.length);
    expect(atob(encoded).charCodeAt(bytes.length - 1)).toBe(128);
    expect(bytes[0]).toBe(128);
  });

  it('keeps the microphone idle after a cached audio element error and ignores late media events', async () => {
    request.mockResolvedValue(tts());
    const view = mount([coach()]);
    await enableCoach();
    const player = view.container.querySelector('audio')!;
    fireEvent.error(player);
    expect(screen.getByRole('status').textContent).toMatch(/error.*playback/i);
    fireEvent.click(screen.getByRole('button', { name: 'Replay coach' }));
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('button', { name: 'Stop voice' }));
    fireEvent.error(player);
    fireEvent.ended(player);
    expect(screen.getByRole('status').textContent).toMatch(/idle.*stopped/i);
    expect(request).toHaveBeenCalledOnce();
  });

  it('fences a new permission request if earlier microphone cleanup fails', async () => {
    const oldDisposal = deferred<void>();
    const newPermission = deferred<void>();
    recorder.dispose.mockReturnValueOnce(oldDisposal.promise).mockRejectedValueOnce(new Error('cleanup failed'));
    recorder.start.mockResolvedValueOnce(undefined).mockReturnValueOnce(newPermission.promise);
    request.mockResolvedValue(stt());
    const apply = vi.fn();
    mount([], apply);
    await transcribe();
    await waitFor(() => expect(apply).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Talk' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*cleanup/i));
    await act(async () => newPermission.resolve());
    expect(screen.getByRole('status').textContent).toMatch(/error.*cleanup/i);
    expect(screen.queryByRole('button', { name: 'Stop and transcribe' })).toBeNull();
    await act(async () => oldDisposal.resolve());
  });

  it.each([-1, 0, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])('ignores invalid coach event sequence %s before the provider boundary', async sequence => {
    mount([coach(sequence)]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    await act(async () => Promise.resolve());
    expect(request).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it('detaches the previous media source when its epoch is invalidated', async () => {
    request.mockResolvedValue(tts());
    const view = mount([coach()]);
    await enableCoach();
    const player = view.container.querySelector('audio')!;
    expect(player.getAttribute('src')).toBe('blob:coach-1');
    view.rerender(<StudioVoice session={session} epoch={2} events={[]} onTranscript={vi.fn()} />);
    expect(player.getAttribute('src')).toBeNull();
    expect(revokeUrl).toHaveBeenCalledWith('blob:coach-1');
  });

  it('does not relabel a fresh-epoch cached event as a replay of old audio', async () => {
    request.mockImplementation(() => Promise.resolve(tts(request.mock.calls.length === 1 ? 1 : 2)));
    const view = mount([coach()]);
    await enableCoach();
    view.rerender(<StudioVoice session={session} epoch={2} events={[coach(1, 2)]} onTranscript={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Play coach' }));
    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ epoch: 2, event_sequence: 1 });
    expect(request).toHaveBeenCalledTimes(2);
  });
});

describe('voice error and availability boundaries', () => {
  it('handles denied microphone permission without a provider request', async () => {
    recorder.start.mockRejectedValue(new DOMException('Denied', 'NotAllowedError'));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*microphone.*text/i));
    expect(request).not.toHaveBeenCalled();
    expect(recorder.dispose).toHaveBeenCalled();
  });

  it.each([null, undefined, '', '   ', 123, {}, []])('rejects invalid or empty ASR text %j without changing the draft', async text => {
    request.mockResolvedValue(json({ normalized_transcript: text, epoch: 1 }));
    const apply = vi.fn();
    mount([], apply);
    await transcribe();
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*transcript/i));
    expect(apply).not.toHaveBeenCalled();
  });

  it('handles empty microphone capture without calling STT', async () => {
    recorder.stop.mockRejectedValue(new Error('No samples'));
    mount();
    await talk();
    fireEvent.click(screen.getByRole('button', { name: 'Stop and transcribe' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*transcription/i));
    expect(request).not.toHaveBeenCalled();
  });

  it.each(['network', 'http', 'null'])('handles an STT %s error without leaking server detail', async mode => {
    if (mode === 'network') request.mockRejectedValue(new Error('private detail'));
    else request.mockResolvedValue(mode === 'http' ? json({ detail: 'private detail' }, 503) : json(null));
    mount();
    await transcribe();
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*transcription/i));
    expect(screen.getByRole('status').textContent).not.toContain('private detail');
  });

  it.each([null, '', 'not base64!', 123])('rejects invalid TTS audio %j', async audio_base64 => {
    request.mockResolvedValue(json({ audio_base64, epoch: 1 }));
    mount([coach()]);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/error.*coach audio/i));
    expect(play).not.toHaveBeenCalled();
    expect(createUrl).not.toHaveBeenCalled();
  });

  it.each(['disabled', 'voiceEnabled'] as const)('gates provider requests using %s without granting consent', async prop => {
    const unavailable = prop === 'disabled' ? { disabled: true } : { voiceEnabled: false };
    const available = prop === 'disabled' ? { disabled: false } : { voiceEnabled: true };
    const view = render(<StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} {...unavailable} />);
    expect((screen.getByRole('button', { name: 'Enable voice and talk' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Enable coach speech' }) as HTMLButtonElement).disabled).toBe(true);
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} {...available} />);
    expect(request).not.toHaveBeenCalled();
    await talk();
    view.rerender(<StudioVoice session={session} epoch={1} events={[coach()]} onTranscript={vi.fn()} {...unavailable} />);
    expect(recorder.dispose).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Cancel voice' })).toBeNull();
  });
});
