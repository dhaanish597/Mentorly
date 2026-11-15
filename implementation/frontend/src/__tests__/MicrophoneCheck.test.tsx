import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MicrophoneCheck } from '../features/settings/MicrophoneCheck';
import { AudioRecorder } from '../services/audioRecorder';
import { saveInputDeviceId } from '../voice/inputDevices';

const KEY = 'viva.microphone-input.v1';
const device = (deviceId: string, label = '', kind = 'audioinput') => ({ deviceId, label, kind, groupId: '', toJSON: () => ({}) } as MediaDeviceInfo);
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
class TrackBoundary {
  readyState = 'live';
  onended: (() => void) | null = null;
  stop = vi.fn(() => { this.readyState = 'ended'; });
}
class ContextBoundary {
  state = 'running'; sampleRate = 16000;
  audioWorklet = { addModule: vi.fn(() => graphReady ?? Promise.resolve()) };
  source = { connect: vi.fn(), disconnect: vi.fn() };
  createMediaStreamSource = vi.fn(() => this.source);
  close = vi.fn(async () => { this.state = 'closed'; });
  constructor() { contexts.push(this); }
}
class WorkletBoundary {
  port = { onmessage: null as ((event: MessageEvent) => void) | null, postMessage: vi.fn() };
  disconnect = vi.fn();
  constructor() { worklets.push(this); }
}
let contexts: ContextBoundary[];
let worklets: WorkletBoundary[];
let tracks: TrackBoundary[];
let devices: MediaDevices;
let enumerate: ReturnType<typeof vi.fn>;
let getUserMedia: ReturnType<typeof vi.fn>;
let fetcher: ReturnType<typeof vi.fn>;
let graphReady: Promise<void> | null;
function stream() {
  const track = new TrackBoundary(); tracks.push(track);
  return { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
}
// Flush promise work and fake-clock microtasks without advancing a capture deadline.
async function settle() { await act(async () => { await Promise.resolve(); await vi.advanceTimersByTimeAsync(0); }); }
async function mount() { const view = render(<MicrophoneCheck />); await settle(); return view; }
async function start() { fireEvent.click(screen.getByRole('button', { name: 'Check microphone' })); await settle(); }
async function finish(level = .25, samples = 32000) {
  act(() => worklets[worklets.length - 1]?.port.onmessage?.({ data: { type: 'AUDIO_FRAME', samples: new Float32Array(samples).fill(level), sampleRate: 16000 } } as MessageEvent));
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
}
beforeEach(() => {
  vi.useFakeTimers(); localStorage.clear(); sessionStorage.clear();
  contexts = []; worklets = []; tracks = []; graphReady = null;
  enumerate = vi.fn(async () => [device('default', 'OS microphone'), device('opaque-1'), device('opaque-2', 'Desk 🎙'), device('speaker', 'speaker', 'audiooutput'), device('camera', 'camera', 'videoinput')]);
  getUserMedia = vi.fn(async () => stream());
  const events = new EventTarget();
  devices = Object.assign(events, { enumerateDevices: enumerate, getUserMedia }) as unknown as MediaDevices;
  vi.spyOn(devices, 'addEventListener'); vi.spyOn(devices, 'removeEventListener');
  vi.stubGlobal('navigator', { mediaDevices: devices });
  vi.stubGlobal('AudioContext', ContextBoundary); vi.stubGlobal('AudioWorkletNode', WorkletBoundary);
  fetcher = vi.fn(() => { throw new Error('network forbidden'); }); vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });

describe('local-only settings microphone flow', () => {
  it('restores keyboard focus to Check microphone after cancellation', async () => {
    await mount(); await start();
    const cancel = screen.getByRole('button', { name: 'Cancel microphone check' });
    cancel.focus();
    fireEvent.click(cancel); await settle();
    expect(screen.getByRole('button', { name: 'Check microphone' })).toHaveFocus();
    expect(tracks[0].stop).toHaveBeenCalledOnce();
  });
  it('does not steal focus after the user moves outside during cancellation', async () => {
    const released = deferred<void>();
    const dispose = AudioRecorder.prototype.dispose;
    vi.spyOn(AudioRecorder.prototype, 'dispose').mockImplementation(async function (this: AudioRecorder) {
      await dispose.call(this); await released.promise;
    });
    render(<><button type="button">Outside control</button><MicrophoneCheck /></>); await settle(); await start();
    const cancel = screen.getByRole('button', { name: 'Cancel microphone check' });
    cancel.focus(); fireEvent.click(cancel); await settle();
    screen.getByRole('button', { name: 'Outside control' }).focus();
    await act(async () => { released.resolve(); }); await settle();
    expect(screen.getByRole('button', { name: 'Outside control' })).toHaveFocus();
  });
  it('enumerates input devices without permission, saves only IDs, refreshes manually, and removes listeners', async () => {
    const view = await mount();
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(screen.getByRole('combobox', { name: 'Microphone input' })).toHaveValue('');
    expect(screen.getByRole('option', { name: 'System default' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /microphone 1.*unlabelled/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Desk 🎙' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'speaker' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'camera' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'opaque-2' } });
    expect(localStorage.getItem(KEY)).toBe('"opaque-2"');
    expect(localStorage.length).toBe(1);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } });
    expect(localStorage.getItem(KEY)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh microphones' })); await settle();
    expect(enumerate).toHaveBeenCalledTimes(2); expect(getUserMedia).not.toHaveBeenCalled();
    expect(screen.getByText(/local-only/i)).toHaveTextContent(/no recording retention/i);
    expect(screen.getByText(/no voice preview/i)).toBeInTheDocument();
    view.unmount();
    expect(devices.removeEventListener).toHaveBeenCalledWith('devicechange', expect.any(Function));
    expect(fetcher).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
  });
  it('shows enumeration failure, recovers with manual refresh, and never prompts', async () => {
    enumerate.mockRejectedValueOnce(new Error('private browser enumeration details'));
    await mount();
    expect(screen.getByRole('alert')).toHaveTextContent(/unable to list microphones/i);
    expect(screen.getByRole('alert')).not.toHaveTextContent('private browser');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh microphones' })); await settle();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
  });
  it('handles unavailable enumeration and an empty list honestly', async () => {
    vi.stubGlobal('navigator', {});
    const view = await mount();
    expect(screen.getByRole('alert')).toHaveTextContent(/not available/i);
    view.unmount(); vi.stubGlobal('navigator', { mediaDevices: devices }); enumerate.mockResolvedValue([]);
    await mount();
    expect(screen.getByText(/no microphones listed/i)).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(1); expect(getUserMedia).not.toHaveBeenCalled();
  });
  it('keeps a stale selected ID explicit, with no permission request or automatic fallback', async () => {
    saveInputDeviceId('missing'); await mount();
    expect(screen.getByRole('combobox')).toHaveValue('missing');
    expect(screen.getByRole('option', { name: /selected microphone.*unavailable/i })).toBeInTheDocument();
    getUserMedia.mockRejectedValueOnce(Object.assign(new Error('missing'), { name: 'NotFoundError' }));
    await start();
    expect(screen.getByRole('alert')).toHaveTextContent(/system default/i);
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(localStorage.getItem(KEY)).toBe('"missing"');
  });
  it('applies same-tab and cross-tab preferences only to the next explicit capture', async () => {
    await mount(); act(() => { saveInputDeviceId('opaque-1'); });
    expect(screen.getByRole('combobox')).toHaveValue('opaque-1');
    await start();
    expect(getUserMedia).toHaveBeenLastCalledWith(expect.objectContaining({ audio: expect.objectContaining({ deviceId: { exact: 'opaque-1' } }), video: false }));
    act(() => { localStorage.setItem(KEY, '"opaque-2"'); window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: '"opaque-2"', storageArea: localStorage })); });
    expect(getUserMedia).toHaveBeenCalledOnce();
    await finish(); await start();
    expect(getUserMedia).toHaveBeenLastCalledWith(expect.objectContaining({ audio: expect.objectContaining({ deviceId: { exact: 'opaque-2' } }), video: false }));
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('reports failed preference persistence without pretending it saved', async () => {
    await mount(); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'opaque-1' } });
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be saved/i);
    expect(screen.getByRole('combobox')).toHaveValue('');
    expect(getUserMedia).not.toHaveBeenCalled();
  });
  it.each([[.25, false, false], [.001, true, false], [1, false, true]])('reports real scalar duration/RMS/peak for level %s and clears audio immediately', async (level, quiet, clipped) => {
    const disposed: AudioRecorder[] = [];
    const erased: Uint8Array[] = [];
    const originalStop = AudioRecorder.prototype.stopMicrophoneCapture;
    vi.spyOn(AudioRecorder.prototype, 'stopMicrophoneCapture').mockImplementation(async function (this: AudioRecorder) { const result = await originalStop.call(this); erased.push(result.wavBytes); return result; });
    const originalDispose = AudioRecorder.prototype.dispose;
    vi.spyOn(AudioRecorder.prototype, 'dispose').mockImplementation(function (this: AudioRecorder) { disposed.push(this); return originalDispose.call(this); });
    await mount(); await start();
    expect(screen.getByRole('button', { name: 'Check microphone' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Refresh microphones' })).toBeDisabled();
    expect(screen.getByRole('combobox')).toBeDisabled();
    await finish(level as number);
    const result = screen.getByRole('status');
    expect(result).toHaveTextContent(/duration: 2\.00 s/i);
    expect(result).toHaveTextContent(new RegExp(`RMS: ${Number(level).toFixed(3)}`, 'i'));
    expect(result).toHaveTextContent(new RegExp(`Peak: ${Number(level).toFixed(3)}`, 'i'));
    expect(Boolean(screen.queryByText(/quiet input/i))).toBe(quiet);
    expect(Boolean(screen.queryByText(/clipped input/i))).toBe(clipped);
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts[0].close).toHaveBeenCalledOnce();
    expect(worklets[0].port.onmessage).toBeNull(); expect(worklets[0].disconnect).toHaveBeenCalledOnce();
    expect(disposed[0].capturedSamplesCount).toBe(0);
    expect(erased[0].every(byte => byte === 0)).toBe(true);
    expect(screen.queryByRole('audio')).not.toBeInTheDocument(); expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Check microphone' })).toBeEnabled();
  });
  it('treats zero frames as an error instead of a successful microphone check', async () => {
    await mount(); await start(); await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole('alert')).toHaveTextContent(/empty|no audio/i);
    expect(screen.queryByText(/duration:/i)).not.toBeInTheDocument();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts[0].close).toHaveBeenCalledOnce();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('starts the two-second deadline only after delayed permission and graph readiness', async () => {
    const permission = deferred<MediaStream>(); const graph = deferred<void>();
    getUserMedia.mockReturnValueOnce(permission.promise); graphReady = graph.promise;
    await mount(); await start();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(screen.getByRole('button', { name: 'Cancel microphone check' })).toBeEnabled();
    expect(screen.queryByText(/duration:/i)).not.toBeInTheDocument();
    await act(async () => { permission.resolve(stream()); });
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(tracks[0].stop).not.toHaveBeenCalled();
    await act(async () => { graph.resolve(); }); await settle();
    act(() => worklets[0].port.onmessage?.({ data: { type: 'AUDIO_FRAME', samples: new Float32Array(32000).fill(.25), sampleRate: 16000 } } as MessageEvent));
    await act(async () => { await vi.advanceTimersByTimeAsync(1999); }); expect(tracks[0].stop).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByRole('status')).toHaveTextContent('Duration: 2.00 s');
  });
  it.each(['cancel', 'unmount'])('safely disposes late-granted permission after %s without a graph or network', async mode => {
    const permission = deferred<MediaStream>(); getUserMedia.mockReturnValueOnce(permission.promise);
    const view = await mount(); await start();
    if (mode === 'cancel') { fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' })); await settle(); }
    else view.unmount();
    await act(async () => { permission.resolve(stream()); }); await settle();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0); expect(fetcher).not.toHaveBeenCalled();
    if (mode === 'cancel') { expect(screen.getByRole('status')).toHaveTextContent(/cancelled/i); expect(screen.queryByRole('alert')).not.toBeInTheDocument(); }
  });
  it.each(['cancel', 'unmount'])('disposes a delayed graph initialization after %s and ignores its late result', async mode => {
    const graph = deferred<void>(); graphReady = graph.promise;
    const view = await mount(); await start();
    if (mode === 'cancel') { fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' })); await settle(); }
    else view.unmount();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts[0].close).toHaveBeenCalledOnce();
    await act(async () => { graph.resolve(); }); await settle();
    expect(worklets).toHaveLength(0); expect(vi.getTimerCount()).toBe(0); expect(fetcher).not.toHaveBeenCalled();
  });
  it('cancels recording and creates a fresh recorder for the next attempt; late callbacks cannot erase results', async () => {
    const options: Parameters<AudioRecorder['startMicrophoneCapture']>[0][] = [];
    const instances: AudioRecorder[] = [];
    const originalStart = AudioRecorder.prototype.startMicrophoneCapture;
    vi.spyOn(AudioRecorder.prototype, 'startMicrophoneCapture').mockImplementation(function (this: AudioRecorder, option) { options.push(option); instances.push(this); return originalStart.call(this, option); });
    await mount(); await start();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' })); await settle();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
    await start(); await finish();
    expect(instances[0]).not.toBe(instances[1]);
    act(() => { options[0]?.onDeviceLost?.('late'); options[0]?.onBackpressureLimitReached?.(); }); await settle();
    expect(screen.getByRole('status')).toHaveTextContent('Duration: 2.00 s');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it.each(['track-ended', 'devicechange', 'enumerated-loss', 'unmount', 'backpressure'])('cleans tracks/context/timer/buffers on %s and never reports success', async mode => {
    const view = await mount(); if (mode === 'enumerated-loss') act(() => { saveInputDeviceId('opaque-1'); });
    await start();
    if (mode === 'track-ended') act(() => tracks[0].onended?.());
    if (mode === 'devicechange') { tracks[0].readyState = 'ended'; act(() => devices.dispatchEvent(new Event('devicechange'))); }
    if (mode === 'enumerated-loss') { enumerate.mockResolvedValue([]); act(() => devices.dispatchEvent(new Event('devicechange'))); }
    if (mode === 'unmount') view.unmount();
    if (mode === 'backpressure') act(() => worklets[0].port.onmessage?.({ data: { type: 'AUDIO_FRAME', samples: new Float32Array(480000).fill(.3), sampleRate: 16000 } } as MessageEvent));
    await settle();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts[0].close).toHaveBeenCalledOnce();
    expect(worklets[0].port.onmessage).toBeNull(); expect(vi.getTimerCount()).toBe(0);
    if (mode !== 'unmount') { expect(screen.getByRole('alert')).toHaveTextContent(/lost|disconnected|limit/i); expect(screen.queryByText(/duration:/i)).not.toBeInTheDocument(); }
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('keeps permission errors visible through enumeration refresh and permits text fallback', async () => {
    getUserMedia.mockRejectedValueOnce(Object.assign(new Error('private denial'), { name: 'NotAllowedError' }));
    await mount(); await start();
    expect(screen.getByRole('alert')).toHaveTextContent(/permission.*denied/i);
    expect(screen.getByRole('alert')).toHaveTextContent(/typed|type/i);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh microphones' })); await settle();
    expect(screen.getByRole('alert')).toHaveTextContent(/permission.*denied/i);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([null, undefined, {}, 'invalid', [null]])('reports invalid browser enumeration %j without requesting permission', async value => {
    enumerate.mockResolvedValueOnce(value);
    await mount();
    expect(screen.getByRole('alert')).toHaveTextContent(/unable to list microphones/i);
    expect(getUserMedia).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('handles 10,000 input devices, filters duplicates, and does not persist labels', async () => {
    const list = Array.from({ length: 10000 }, (_, index) => device(`input-${index}`, `Microphone ${index}`));
    enumerate.mockResolvedValueOnce([...list, list[0], device('', 'No usable ID')]);
    await mount();
    const select = screen.getByRole<HTMLSelectElement>('combobox');
    expect(select.options).toHaveLength(10001);
    fireEvent.change(select, { target: { value: 'input-9999' } });
    expect(select).toHaveValue('input-9999');
    expect(localStorage.getItem(KEY)).toBe('"input-9999"');
    expect(localStorage.getItem(KEY)).not.toContain('Microphone');
    expect(getUserMedia).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  }, 30000);
  it('cancels an explicitly selected device lost while permission is pending and stops its late stream', async () => {
    const permission = deferred<MediaStream>(); getUserMedia.mockReturnValueOnce(permission.promise);
    saveInputDeviceId('opaque-1'); await mount(); await start();
    enumerate.mockResolvedValueOnce([]);
    act(() => devices.dispatchEvent(new Event('devicechange'))); await settle();
    expect(screen.getByRole('alert')).toHaveTextContent(/disconnected/i);
    await act(async () => { permission.resolve(stream()); }); await settle();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0); expect(fetcher).not.toHaveBeenCalled();
  });
  it('does not let a cancelled permission result overwrite a later completed attempt', async () => {
    const permission = deferred<MediaStream>(); getUserMedia.mockReturnValueOnce(permission.promise);
    await mount(); await start();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' })); await settle();
    await start(); await finish();
    await act(async () => { permission.resolve(stream()); }); await settle();
    expect(tracks[1].stop).toHaveBeenCalledOnce(); expect(contexts).toHaveLength(1);
    expect(screen.getByRole('status')).toHaveTextContent('Duration: 2.00 s');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('cancels while finalization is pending and erases its late payload without reporting success', async () => {
    const final = deferred<Awaited<ReturnType<AudioRecorder['stopMicrophoneCapture']>>>();
    vi.spyOn(AudioRecorder.prototype, 'stopMicrophoneCapture').mockReturnValueOnce(final.promise);
    await mount(); await start();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel microphone check' })); await settle();
    const wavBytes = new Uint8Array(100).fill(1);
    await act(async () => { final.resolve({ sessionId: 'local', turnGeneration: 1, captureAttemptId: 1, wavBytes, durationSec: 2, rmsNormalized: .3, peakNormalized: .5, sampleRateHz: 16000, lowEnergyWarning: false, clippedSamples: 0 }); }); await settle();
    expect(wavBytes.every(byte => byte === 0)).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent(/cancelled/i);
    expect(screen.queryByText(/duration:/i)).not.toBeInTheDocument();
    expect(tracks[0].stop).toHaveBeenCalledOnce(); expect(contexts[0].close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0); expect(fetcher).not.toHaveBeenCalled();
  });
  it('ignores an enumeration reply after unmount', async () => {
    const listing = deferred<MediaDeviceInfo[]>(); enumerate.mockReturnValueOnce(listing.promise);
    const view = render(<MicrophoneCheck />); view.unmount();
    await act(async () => { listing.resolve([device('late', 'Late microphone')]); }); await settle();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(devices.removeEventListener).toHaveBeenCalledWith('devicechange', expect.any(Function));
    expect(getUserMedia).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('ignores stale enumeration completions and duplicate starts', async () => {
    const old = deferred<MediaDeviceInfo[]>(); enumerate.mockReturnValueOnce(old.promise);
    const view = render(<MicrophoneCheck />); await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh microphones' })); await settle();
    await act(async () => { old.resolve([device('late', 'Old microphone')]); });
    expect(screen.queryByRole('option', { name: 'Old microphone' })).not.toBeInTheDocument();
    const check = screen.getByRole('button', { name: 'Check microphone' });
    act(() => { fireEvent.click(check); fireEvent.click(check); }); await settle();
    expect(getUserMedia).toHaveBeenCalledOnce();
    view.unmount(); expect(vi.getTimerCount()).toBe(0);
  });
});
