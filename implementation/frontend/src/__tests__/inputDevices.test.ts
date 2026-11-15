import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadInputDeviceId, saveInputDeviceId, subscribeInputDeviceId } from '../voice/inputDevices';
import { AudioRecorder, MicrophoneCaptureError } from '../services/audioRecorder';

const KEY = 'viva.microphone-input.v1';
beforeEach(() => localStorage.clear());
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

describe('input device preference boundary', () => {
  it('defaults to the system input, saves only a JSON opaque ID, and removes on reset', () => {
    expect(loadInputDeviceId()).toBeNull();
    expect(saveInputDeviceId('opaque-தமிழ்-🎙-\'";')).toBe(true);
    expect(localStorage.getItem(KEY)).toBe(JSON.stringify('opaque-தமிழ்-🎙-\'";'));
    expect(loadInputDeviceId()).toBe('opaque-தமிழ்-🎙-\'";');
    expect(saveInputDeviceId(null)).toBe(true);
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(loadInputDeviceId()).toBeNull();
    expect(localStorage.length).toBe(0);
  });
  it.each([undefined, '', ' ', '\n', 'a\u0000b', 'x'.repeat(1025), 0, false, [], {}, { deviceId: 'id', label: 'private' }])('rejects invalid saved ID %j without changing storage', value => {
    const target = { setItem: vi.fn(), removeItem: vi.fn() };
    expect(saveInputDeviceId(value as string, target)).toBe(false);
    expect(target.setItem).not.toHaveBeenCalled();
    expect(target.removeItem).not.toHaveBeenCalled();
  });
  it('accepts the maximum bounded ID and injected storage', () => {
    const id = 'x'.repeat(1024);
    const target = { setItem: vi.fn(), removeItem: vi.fn() };
    expect(saveInputDeviceId(id, target)).toBe(true);
    expect(target.setItem).toHaveBeenCalledWith(KEY, JSON.stringify(id));
    expect(loadInputDeviceId({ getItem: () => JSON.stringify(id) })).toBe(id);
    expect(saveInputDeviceId(null, target)).toBe(true);
    expect(target.removeItem).toHaveBeenCalledWith(KEY);
  });
  it.each(['null', 'false', '123', '[]', '{}', '""', '" "', 'not-json', JSON.stringify('x'.repeat(1025)), ' '.repeat(10000)])('safely defaults for malformed stored value %s', raw => {
    expect(loadInputDeviceId({ getItem: () => raw })).toBeNull();
  });
  it('handles read/write/removal denial and localStorage access denial', () => {
    expect(loadInputDeviceId({ getItem: () => { throw new Error('denied'); } })).toBeNull();
    const target = { setItem: () => { throw new Error('quota'); }, removeItem: () => { throw new Error('denied'); } };
    expect(saveInputDeviceId('id', target)).toBe(false);
    expect(saveInputDeviceId(null, target)).toBe(false);
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('denied'); });
    expect(loadInputDeviceId()).toBeNull();
    expect(saveInputDeviceId('id')).toBe(false);
  });
  it('notifies same-tab and validated cross-tab updates, ignores unrelated storage, and cleans up', () => {
    const receive = vi.fn();
    const unsubscribe = subscribeInputDeviceId(receive);
    saveInputDeviceId('one');
    expect(receive).toHaveBeenLastCalledWith('one');
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: JSON.stringify('two'), storageArea: localStorage }));
    expect(receive).toHaveBeenLastCalledWith('two');
    const count = receive.mock.calls.length;
    window.dispatchEvent(new StorageEvent('storage', { key: 'other', newValue: '"other"' }));
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: '"session"', storageArea: sessionStorage }));
    expect(receive).toHaveBeenCalledTimes(count);
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: '{}' }));
    expect(receive).toHaveBeenLastCalledWith(null);
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: 'broken' }));
    expect(receive).toHaveBeenLastCalledWith(null);
    window.dispatchEvent(new StorageEvent('storage', { key: null }));
    expect(receive).toHaveBeenLastCalledWith(null);
    saveInputDeviceId(null);
    expect(receive).toHaveBeenLastCalledWith(null);
    unsubscribe();
    const finalCount = receive.mock.calls.length;
    saveInputDeviceId('after');
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: '"after"' }));
    expect(receive).toHaveBeenCalledTimes(finalCount);
  });
  it('is safe without a browser and filters storage events when storage access is denied', () => {
    const receive = vi.fn();
    const unsubscribe = subscribeInputDeviceId(receive);
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('denied'); });
    expect(() => window.dispatchEvent(new StorageEvent('storage', { key: KEY, storageArea: sessionStorage }))).not.toThrow();
    unsubscribe();
    vi.stubGlobal('window', undefined);
    expect(loadInputDeviceId()).toBeNull();
    expect(saveInputDeviceId('id')).toBe(false);
    expect(() => subscribeInputDeviceId(receive)()).not.toThrow();
  });
});

function graph() {
  const track = { readyState: 'live', onended: null as (() => void) | null, stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
  const mediaDevices = { getUserMedia: vi.fn(async () => stream), addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const node = { port: { onmessage: null, postMessage: vi.fn() }, disconnect: vi.fn() } as unknown as AudioWorkletNode;
  const context = { sampleRate: 48000, state: 'running', audioWorklet: { addModule: vi.fn(async () => undefined) }, createMediaStreamSource: () => ({ connect: vi.fn(), disconnect: vi.fn() }), close: vi.fn(async () => undefined) } as unknown as AudioContext;
  return { track, mediaDevices, audioContextFactory: () => context, workletNodeFactory: () => node };
}

describe('shared recorder input selection (DSA/Studio/Module seam)', () => {
  it('reads the saved exact input on every capture without mutating caller constraints', async () => {
    const recorder = new AudioRecorder('local-test');
    const boundary = graph();
    saveInputDeviceId('first');
    await recorder.startMicrophoneCapture(boundary);
    expect(boundary.mediaDevices.getUserMedia).toHaveBeenLastCalledWith({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true, deviceId: { exact: 'first' } }, video: false });
    saveInputDeviceId('second');
    await recorder.startMicrophoneCapture(boundary);
    expect(boundary.mediaDevices.getUserMedia).toHaveBeenLastCalledWith(expect.objectContaining({ audio: expect.objectContaining({ deviceId: { exact: 'second' } }) }));
    await recorder.dispose();
    expect(boundary.track.stop).toHaveBeenCalled();
  });
  it('merges explicit caller constraints last and always disables video', async () => {
    saveInputDeviceId('saved');
    const constraints = Object.freeze({ deviceId: { exact: 'caller' }, echoCancellation: false, channelCount: 2 });
    const boundary = graph();
    const recorder = new AudioRecorder('local-test');
    await recorder.startMicrophoneCapture({ ...boundary, constraints });
    expect(boundary.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: { ...constraints, noiseSuppression: true, autoGainControl: true }, video: false });
    expect(constraints.deviceId).toEqual({ exact: 'caller' });
    await recorder.dispose();
  });
  it('uses the browser default when reset or invalid storage is present', async () => {
    const recorder = new AudioRecorder('local-test');
    const boundary = graph();
    localStorage.setItem(KEY, '{}');
    await recorder.startMicrophoneCapture(boundary);
    expect(boundary.mediaDevices.getUserMedia).toHaveBeenLastCalledWith({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
    saveInputDeviceId('selected'); saveInputDeviceId(null);
    await recorder.startMicrophoneCapture(boundary);
    expect(boundary.mediaDevices.getUserMedia).toHaveBeenLastCalledWith(expect.objectContaining({ audio: expect.not.objectContaining({ deviceId: expect.anything() }), video: false }));
    await recorder.dispose();
  });
  it.each(['OverconstrainedError', 'NotFoundError', 'NotReadableError'])('keeps typed fallback and fails explicit unavailable input (%s) without retry', async name => {
    saveInputDeviceId('stale');
    const getUserMedia = vi.fn(async () => { throw Object.assign(new Error('private device detail'), { name }); });
    const recorder = new AudioRecorder('local-test');
    try {
      await recorder.startMicrophoneCapture({ mediaDevices: { getUserMedia, addEventListener: vi.fn(), removeEventListener: vi.fn() } });
      expect.fail('unavailable explicit device must fail');
    } catch (error) {
      expect(error).toBeInstanceOf(MicrophoneCaptureError);
      expect(error).toMatchObject({ fallbackMode: 'TYPED_FALLBACK', code: 'MIC_DEVICE_UNAVAILABLE' });
      expect((error as Error).message).toMatch(/system default/i);
      expect((error as Error).message).not.toContain('private device detail');
    }
    expect(getUserMedia).toHaveBeenCalledOnce();
    await recorder.dispose();
  });
});
