import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AudioRecorder,
  MAX_RECORDING_DURATION_SEC,
  MAX_WAV_BYTES,
  type CapturedAudio,
  type MicrophoneCaptureOptions,
} from '../services/audioRecorder';
import { TARGET_SAMPLE_RATE_HZ } from '../services/audioWorkletProcessor';

function createMicrophoneHarness(sampleRate = 48000) {
  const track = { readyState: 'live', onended: null as (() => void) | null, stop: vi.fn() };
  const stream = {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream;
  const port = { onmessage: null as ((event: MessageEvent) => void) | null, postMessage: vi.fn() };
  const node = { port, disconnect: vi.fn() };
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    sampleRate,
    state: 'running',
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createMediaStreamSource: () => source,
    close: vi.fn().mockResolvedValue(undefined),
  };
  const options: MicrophoneCaptureOptions = {
    mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue(stream),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
    audioContextFactory: () => context as unknown as AudioContext,
    workletNodeFactory: () => node as unknown as AudioWorkletNode,
  };
  const emit = (samples: Float32Array, rate = sampleRate) => {
    port.onmessage?.({ data: { type: 'AUDIO_FRAME', samples, sampleRate: rate } } as MessageEvent);
  };
  return { options, emit, track, context, node, source, port };
}

const speech = () => new Float32Array(128).fill(0.1);
const quiet = () => new Float32Array(128).fill(0.001);

function pcmOf(recording: CapturedAudio): number[] {
  const view = new DataView(recording.wavBytes.buffer, recording.wavBytes.byteOffset);
  return Array.from({ length: (recording.wavBytes.byteLength - 44) / 2 }, (_, i) =>
    view.getInt16(44 + i * 2, true));
}

describe('microphone speech activity and silence deadlines', () => {
  const recorders: AudioRecorder[] = [];
  const createRecorder = () => {
    const recorder = new AudioRecorder('voice-静かな-turn', 3);
    recorders.push(recorder);
    return recorder;
  };

  beforeEach(() => vi.useFakeTimers());
  afterEach(async () => {
    for (const recorder of recorders.splice(0)) await recorder.dispose();
    vi.useRealTimers();
  });

  it('does not submit initial silence, low-energy background noise, or empty frames', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSpeechActivity = vi.fn();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSpeechActivity, onSilenceTimeout });

    harness.emit(new Float32Array());
    harness.emit(quiet());
    harness.emit(new Float32Array(128).fill(0.01));
    vi.advanceTimersByTime(20_000);

    expect(onSpeechActivity).not.toHaveBeenCalled();
    expect(onSilenceTimeout).not.toHaveBeenCalled();
  });

  it('reports each real RMS speech frame and fires once after exactly ten seconds quiet', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSpeechActivity = vi.fn();
    const onSilenceTimeout = vi.fn();
    const onFrameTelemetry = vi.fn();
    await recorder.startMicrophoneCapture({
      ...harness.options, onSpeechActivity, onSilenceTimeout, onFrameTelemetry,
    });

    harness.emit(speech());
    harness.emit(quiet());
    vi.advanceTimersByTime(9_999);
    expect(onSpeechActivity).toHaveBeenCalledTimes(1);
    expect(onFrameTelemetry).toHaveBeenCalledTimes(2);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
    harness.emit(quiet());
    vi.advanceTimersByTime(30_000);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
    expect(recorder.isRecording).toBe(true);
  });

  it('uses RMS rather than isolated amplitude peaks for speech activity', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    const onSpeechActivity = vi.fn();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSpeechActivity, onSilenceTimeout });
    const impulse = new Float32Array(16_000);
    impulse[0] = 1;
    harness.emit(impulse);
    vi.advanceTimersByTime(10_000);
    expect(onSpeechActivity).not.toHaveBeenCalled();
    expect(onSilenceTimeout).not.toHaveBeenCalled();
  });

  it('resets the deadline on every speech frame, not just the first speech onset', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSpeechActivity = vi.fn();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSpeechActivity, onSilenceTimeout });

    harness.emit(speech());
    vi.advanceTimersByTime(9_000);
    harness.emit(speech());
    vi.advanceTimersByTime(9_000);
    harness.emit(speech());
    vi.advanceTimersByTime(9_999);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(onSpeechActivity).toHaveBeenCalledTimes(3);
    vi.advanceTimersByTime(1);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
  });

  it('rearms only after new speech and supports a configurable silence duration', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, silenceMs: 100, onSilenceTimeout });
    harness.emit(speech());
    vi.advanceTimersByTime(100);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
    harness.emit(quiet());
    vi.advanceTimersByTime(500);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
    harness.emit(speech());
    vi.advanceTimersByTime(99);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(2);
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])('rejects invalid silenceMs %s before opening a device', async (silenceMs) => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    await expect(recorder.startMicrophoneCapture({ ...harness.options, silenceMs })).rejects.toThrow(/silenceMs/);
    expect(harness.options.mediaDevices?.getUserMedia).not.toHaveBeenCalled();
  });

  it.each(['stop', 'dispose', 'device loss'] as const)('cancels pending silence callbacks on %s', async (action) => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSilenceTimeout = vi.fn();
    const onDeviceLost = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSilenceTimeout, onDeviceLost });
    harness.emit(speech());
    if (action === 'stop') await recorder.stopMicrophoneCapture();
    else if (action === 'dispose') await recorder.dispose();
    else harness.track.onended?.();
    vi.advanceTimersByTime(10_000);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(recorder.isRecording).toBe(false);
    expect(harness.track.stop).toHaveBeenCalledTimes(1);
    if (action === 'device loss') expect(onDeviceLost).toHaveBeenCalledTimes(1);
  });

  it('replacing capture cancels the old deadline and requires speech on the new capture', async () => {
    const recorder = createRecorder();
    const first = createMicrophoneHarness();
    const oldTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...first.options, onSilenceTimeout: oldTimeout });
    first.emit(speech());
    const second = createMicrophoneHarness();
    const newTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...second.options, onSilenceTimeout: newTimeout });
    vi.advanceTimersByTime(10_000);
    expect(oldTimeout).not.toHaveBeenCalled();
    expect(newTimeout).not.toHaveBeenCalled();
    second.emit(speech());
    vi.advanceTimersByTime(10_000);
    expect(newTimeout).toHaveBeenCalledTimes(1);
  });

  it('ignores malformed worklet messages without arming a silence deadline', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSpeechActivity = vi.fn();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSpeechActivity, onSilenceTimeout });
    for (const data of [null, undefined, {}, { type: 'OTHER', samples: speech() }, { type: 'AUDIO_FRAME' }]) {
      harness.port.onmessage?.({ data } as MessageEvent);
    }
    vi.advanceTimersByTime(10_000);
    expect(onSpeechActivity).not.toHaveBeenCalled();
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(recorder.capturedSamplesCount).toBe(0);
  });

  it('drains PCM atomically while keeping the context, device, and later frames active', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    await recorder.startMicrophoneCapture(harness.options);
    harness.emit(new Float32Array([0.25, -0.5, 1]));

    const first: CapturedAudio = recorder.drainMicrophoneCapture();
    expect(pcmOf(first)).toEqual([8192, -16384, 32767]);
    expect(first.sessionId).toBe('voice-静かな-turn');
    expect(first.turnGeneration).toBe(3);
    expect(first.captureAttemptId).toBe(1);
    expect(first.clippedSamples).toBe(1);
    expect(first.sampleRateHz).toBe(16000);
    expect(recorder.capturedSamplesCount).toBe(0);
    expect(recorder.isRecording).toBe(true);
    expect(recorder.state).toBe('RECORDING');
    expect(harness.context.close).not.toHaveBeenCalled();
    expect(harness.track.stop).not.toHaveBeenCalled();
    expect(harness.node.disconnect).not.toHaveBeenCalled();
    expect(harness.source.disconnect).not.toHaveBeenCalled();
    expect(harness.port.postMessage).not.toHaveBeenCalled();

    harness.emit(new Float32Array([0.125, -0.25]));
    const second = await recorder.stopMicrophoneCapture();
    expect(pcmOf(second)).toEqual([4096, -8192]);
    expect(second.captureAttemptId).toBe(first.captureAttemptId);
    expect(second.clippedSamples).toBe(0);
    expect(pcmOf(first)).toEqual([8192, -16384, 32767]);
    expect(harness.context.close).toHaveBeenCalledTimes(1);
    expect(harness.track.stop).toHaveBeenCalledTimes(1);
  });

  it('preserves fractional resampler phase across drains with no dropped subsequent samples', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    await recorder.startMicrophoneCapture(harness.options);
    harness.emit(new Float32Array(128).fill(0.25));
    const first = recorder.drainMicrophoneCapture();
    expect(pcmOf(first)).toHaveLength(42);
    harness.emit(new Float32Array([0.25]));
    const second = recorder.drainMicrophoneCapture();
    expect(pcmOf(second)).toEqual([8192]);
  });

  it('rejects empty drains without stopping capture or losing subsequent samples', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    await recorder.startMicrophoneCapture(harness.options);
    expect(() => recorder.drainMicrophoneCapture()).toThrow(/empty voice recording/);
    expect(recorder.isRecording).toBe(true);
    harness.emit(speech());
    recorder.drainMicrophoneCapture();
    expect(() => recorder.drainMicrophoneCapture()).toThrow(/empty voice recording/);
    harness.emit(speech());
    expect(pcmOf(recorder.drainMicrophoneCapture())).toHaveLength(43);
  });

  it('draining resets pending silence so a submitted turn cannot trigger an empty next turn', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSilenceTimeout, silenceMs: 100 });
    harness.emit(speech());
    recorder.drainMicrophoneCapture();
    vi.advanceTimersByTime(100);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    harness.emit(quiet());
    vi.advanceTimersByTime(100);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    harness.emit(speech());
    vi.advanceTimersByTime(100);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
  });

  it('allows a silence callback to drain synchronously then retains speech during submission', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const recordings: CapturedAudio[] = [];
    await recorder.startMicrophoneCapture({
      ...harness.options, silenceMs: 100,
      onSilenceTimeout: () => recordings.push(recorder.drainMicrophoneCapture()),
    });
    harness.emit(speech());
    vi.advanceTimersByTime(100);
    expect(recordings).toHaveLength(1);
    expect(recorder.isRecording).toBe(true);
    harness.emit(new Float32Array(128).fill(0.25));
    vi.advanceTimersByTime(100);
    expect(recordings).toHaveLength(2);
    expect(pcmOf(recordings[1])).toHaveLength(43);
    expect(harness.track.stop).not.toHaveBeenCalled();
  });

  it('preserves next-turn samples and silence deadline when advancing metadata during recognition', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSilenceTimeout });
    harness.emit(speech());
    recorder.drainMicrophoneCapture();
    harness.emit(new Float32Array(128).fill(0.25));
    const before = recorder.capturedSamplesCount;
    recorder.setTurnGeneration(4, true);
    expect(recorder.capturedSamplesCount).toBe(before);
    vi.advanceTimersByTime(10_000);
    expect(onSilenceTimeout).toHaveBeenCalledTimes(1);
    expect(pcmOf(recorder.drainMicrophoneCapture())).toEqual(new Array(128).fill(8192));
    expect(recorder.isRecording).toBe(true);
  });

  it('rolls over bounded segments without closing the microphone or losing subsequent speech', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    const onBackpressureLimitReached = vi.fn(() => recorder.drainMicrophoneCapture());
    await recorder.startMicrophoneCapture({ ...harness.options, onBackpressureLimitReached });
    harness.emit(new Float32Array(TARGET_SAMPLE_RATE_HZ * MAX_RECORDING_DURATION_SEC).fill(0.25));
    expect(onBackpressureLimitReached).toHaveBeenCalledTimes(1);
    expect(recorder.isRecording).toBe(true);
    harness.emit(speech());
    expect(recorder.capturedSamplesCount).toBe(128);
    expect(harness.track.stop).not.toHaveBeenCalled();
    expect(harness.context.close).not.toHaveBeenCalled();
  });

  it('keeps existing 30-second and WAV backpressure bounds without a drain', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    const onBackpressureLimitReached = vi.fn();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onBackpressureLimitReached, onSilenceTimeout });
    harness.emit(new Float32Array(TARGET_SAMPLE_RATE_HZ * (MAX_RECORDING_DURATION_SEC + 1)).fill(0.25));
    harness.emit(speech());
    vi.advanceTimersByTime(10_000);
    expect(onBackpressureLimitReached).toHaveBeenCalledTimes(1);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(recorder.isRecording).toBe(false);
    const bounded = await recorder.stopMicrophoneCapture();
    expect(bounded.durationSec).toBe(MAX_RECORDING_DURATION_SEC);
    expect(bounded.wavBytes.byteLength).toBeLessThanOrEqual(MAX_WAV_BYTES);
  });

  it('detects positive and negative speech at the exact RMS threshold', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    const onSpeechActivity = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSpeechActivity });
    harness.emit(new Float32Array(128).fill(0.019));
    harness.emit(new Float32Array(128).fill(0.02));
    harness.emit(new Float32Array(128).fill(-0.02));
    expect(onSpeechActivity).toHaveBeenCalledTimes(2);
  });

  it('handles devicechange only when all microphone tracks have ended', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onDeviceLost = vi.fn();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onDeviceLost, onSilenceTimeout });
    const listener = vi.mocked(harness.options.mediaDevices!.addEventListener).mock.calls[0][1] as () => void;
    harness.emit(speech());
    listener();
    expect(onDeviceLost).not.toHaveBeenCalled();
    expect(recorder.isRecording).toBe(true);
    harness.track.readyState = 'ended';
    listener();
    vi.advanceTimersByTime(10_000);
    expect(onDeviceLost).toHaveBeenCalledTimes(1);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(recorder.state).toBe('DEVICE_LOST_TEXT_FALLBACK');
  });

  it.each(['NotAllowedError', 'PermissionDeniedError', 'SecurityError', 'NotFoundError'])('preserves typed fallback when permission fails with %s', async (name) => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    vi.mocked(harness.options.mediaDevices!.getUserMedia).mockRejectedValueOnce(Object.assign(new Error('denied'), { name }));
    await expect(recorder.startMicrophoneCapture(harness.options)).rejects.toThrow(/typed fallback/);
    expect(recorder.state).toBe(name === 'NotFoundError' ? 'DEVICE_UNAVAILABLE_TEXT_FALLBACK' : 'PERMISSION_DENIED_TEXT_FALLBACK');
    expect(recorder.isRecording).toBe(false);
  });

  it('handles a non-Error microphone rejection without leaking the rejection value', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    vi.mocked(harness.options.mediaDevices!.getUserMedia).mockRejectedValueOnce('private device failure');
    await expect(recorder.startMicrophoneCapture(harness.options)).rejects.toThrow('UnknownError');
    expect(recorder.state).toBe('DEVICE_UNAVAILABLE_TEXT_FALLBACK');
  });

  it('fails safely when the browser has no microphone support', async () => {
    const recorder = createRecorder();
    await expect(recorder.startMicrophoneCapture()).rejects.toThrow(/getUserMedia is unavailable/);
    expect(recorder.state).toBe('DEVICE_UNAVAILABLE_TEXT_FALLBACK');
  });

  it('cleans up a failed worklet registration and does not leave a silence callback', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSilenceTimeout = vi.fn();
    harness.context.audioWorklet.addModule.mockRejectedValueOnce(new Error('registration failed'));
    await expect(recorder.startMicrophoneCapture({ ...harness.options, onSilenceTimeout })).rejects.toThrow('registration failed');
    vi.advanceTimersByTime(10_000);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(harness.track.stop).toHaveBeenCalledTimes(1);
    expect(harness.context.close).toHaveBeenCalledTimes(1);
    expect(recorder.isRecording).toBe(false);
    expect(recorder.state).toBe('ERROR_TEXT_FALLBACK');
  });

  it('resumes suspended audio and uses the default browser context and worklet constructors', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const resume = vi.fn().mockResolvedValue(undefined);
    const context = { ...harness.context, state: 'suspended', resume };
    class BrowserContext { constructor() { return context; } }
    class BrowserWorklet { constructor() { return harness.node; } }
    vi.stubGlobal('AudioContext', BrowserContext);
    vi.stubGlobal('AudioWorkletNode', BrowserWorklet);
    try {
      await recorder.startMicrophoneCapture({ mediaDevices: harness.options.mediaDevices });
      harness.emit(speech(), 0);
      expect(resume).toHaveBeenCalledTimes(1);
      expect(recorder.capturedSamplesCount).toBe(42);
      expect((await recorder.stopMicrophoneCapture()).wavBytes).toHaveLength(128);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('revokes the registered worklet Blob URL even when registration fails', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const createObjectURL = vi.fn().mockReturnValue('blob:mock-audio-worklet');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    harness.context.audioWorklet.addModule.mockRejectedValueOnce('registration rejected');
    try {
      await expect(recorder.startMicrophoneCapture(harness.options)).rejects.toThrow('registration rejected');
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-audio-worklet');
      expect(harness.track.stop).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('still cancels silence and returns the WAV when browser cleanup operations reject', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness();
    const onSilenceTimeout = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onSilenceTimeout });
    harness.emit(speech());
    const fail = () => { throw new Error('browser cleanup failed'); };
    vi.mocked(harness.options.mediaDevices!.removeEventListener).mockImplementation(fail);
    harness.node.disconnect.mockImplementation(fail);
    harness.source.disconnect.mockImplementation(fail);
    harness.track.stop.mockImplementation(fail);
    harness.context.close.mockRejectedValue(new Error('close failed'));
    const result = await recorder.stopMicrophoneCapture();
    vi.advanceTimersByTime(10_000);
    expect(result.wavBytes.byteLength).toBe(128);
    expect(onSilenceTimeout).not.toHaveBeenCalled();
    expect(recorder.state).toBe('IDLE');
    expect(harness.context.close).toHaveBeenCalledTimes(1);
  });

  it('applies bounds to each drained segment rather than the entire open microphone session', async () => {
    const recorder = createRecorder();
    const harness = createMicrophoneHarness(16000);
    const onBackpressureLimitReached = vi.fn();
    await recorder.startMicrophoneCapture({ ...harness.options, onBackpressureLimitReached });
    for (let turn = 0; turn < 2; turn++) {
      harness.emit(new Float32Array(20 * TARGET_SAMPLE_RATE_HZ).fill(0.25));
      expect(recorder.drainMicrophoneCapture().durationSec).toBe(20);
    }
    expect(onBackpressureLimitReached).not.toHaveBeenCalled();
    expect(recorder.isRecording).toBe(true);
    expect(harness.context.close).not.toHaveBeenCalled();
  });
});
