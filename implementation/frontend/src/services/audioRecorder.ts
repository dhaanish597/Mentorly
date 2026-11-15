/**
 * Browser Microphone Recorder & 16 kHz Mono PCM WAV Assembler (`audioRecorder.ts`).
 *
 * Implements Plan §8.1 / Phase 2 Prompt §B.6 & Fix P2-07:
 * - Captures microphone audio via `navigator.mediaDevices.getUserMedia` + `AudioContext` +
 *   `AudioWorkletNode` (never `ScriptProcessorNode`), with Blob URL registration & revocation,
 *   port message handling, backpressure bounds (`<= 30.0 s`, `<= 1 MiB`), mid-capture device
 *   loss (`track.onended` and `devicechange`) handling, and deterministic track/context cleanup.
 * - Uses `StatefulResampler` across 128-sample worklet quanta so 375 frames of 128 samples at
 *   48 kHz yield 16,000 samples (0 lost samples).
 * - Preserves `TYPED_FALLBACK` degradation state when microphone permission is denied or lost.
 */

import type { InteractionMode } from '../types/api';
import { SpeechActivityDetector } from './speechActivity';
import { loadInputDeviceId } from '../voice/inputDevices';
import {
  StatefulResampler,
  TARGET_SAMPLE_RATE_HZ,
  VCC_AUDIO_WORKLET_SOURCE,
  type WorkletTelemetryFrame,
} from './audioWorkletProcessor';

export const MAX_RECORDING_DURATION_SEC = 30.0;
export const MAX_WAV_BYTES = 1_048_576; // 1 MiB
export const LOW_ENERGY_RMS_THRESHOLD = 0.008;
export const SPEECH_RMS_THRESHOLD = 0.02;
export const DEFAULT_SILENCE_MS = 10_000;

export type RecorderLifecycleState =
  | 'IDLE'
  | 'REQUESTING_PERMISSION'
  | 'RECORDING'
  | 'STOPPING'
  | 'PERMISSION_DENIED_TEXT_FALLBACK'
  | 'DEVICE_UNAVAILABLE_TEXT_FALLBACK'
  | 'DEVICE_LOST_TEXT_FALLBACK'
  | 'ERROR_TEXT_FALLBACK';

export interface AssembledWavRecording {
  readonly sessionId: string;
  readonly turnGeneration: number;
  readonly captureAttemptId: number;
  readonly wavBytes: Uint8Array;
  readonly sampleRateHz: number;
  readonly durationSec: number;
  readonly rmsNormalized: number;
  readonly peakNormalized: number;
  readonly lowEnergyWarning: boolean;
  readonly clippedSamples: number;
  /** Local heuristic only; recognition still determines whether usable text exists. */
  readonly speechLikeActivityDetected: boolean;
}

/** The same WAV payload returned by stopping capture, also usable for continuous-turn drains. */
export type CapturedAudio = AssembledWavRecording;

type CaptureMediaDevices = Pick<MediaDevices, 'getUserMedia' | 'addEventListener' | 'removeEventListener'> & Partial<Pick<MediaDevices, 'getSupportedConstraints'>>;
export type CaptureProcessingStatus = { echoCancellation: 'enabled' | 'disabled' | 'unreported'; noiseSuppression: 'enabled' | 'disabled' | 'unreported'; autoGainControl: 'enabled' | 'disabled' | 'unreported' };

export interface MicrophoneCaptureOptions {
  readonly mediaDevices?: CaptureMediaDevices;
  readonly audioContextFactory?: () => AudioContext;
  readonly workletNodeFactory?: (context: AudioContext, processorName: string) => AudioWorkletNode;
  readonly constraints?: MediaTrackConstraints;
  readonly onFrameTelemetry?: (frame: WorkletTelemetryFrame) => void;
  readonly onDeviceLost?: (reason: string) => void;
  readonly onBackpressureLimitReached?: () => void;
  /** Called after sustained, modulated speech-like activity; never proof of speech. */
  readonly onSpeechActivity?: () => void;
  /** Called once per quiet interval, only after speech has been captured. */
  readonly onSilenceTimeout?: () => void;
  /** Positive finite silence deadline in milliseconds; defaults to 10 seconds. */
  readonly silenceMs?: number;
}

export class MicrophoneCaptureError extends Error {
  public readonly code: string;
  public readonly state: RecorderLifecycleState;
  public readonly fallbackMode: InteractionMode = 'TYPED_FALLBACK';

  constructor(code: string, message: string, state: RecorderLifecycleState) {
    super(message);
    this.name = 'MicrophoneCaptureError';
    this.code = code;
    this.state = state;
  }
}

/**
 * Encode a 16-bit signed mono PCM buffer into a canonical 44-byte RIFF/WAVE container.
 */
export function encodePcm16ToWavBytes(
  pcmSamples: Int16Array,
  sampleRateHz: number = TARGET_SAMPLE_RATE_HZ,
): Uint8Array {
  const numChannels = 1;
  const bytesPerSample = 2;
  const dataByteLength = pcmSamples.length * bytesPerSample;
  const totalByteLength = 44 + dataByteLength;

  if (totalByteLength > MAX_WAV_BYTES) {
    throw new Error(`WAV payload (${totalByteLength} bytes) exceeds 1 MiB limit (${MAX_WAV_BYTES}).`);
  }

  const buffer = new ArrayBuffer(totalByteLength);
  const view = new DataView(buffer);

  const writeAscii = (offset: number, str: string): void => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  };

  writeAscii(0, 'RIFF');
  view.setUint32(4, 36 + dataByteLength, true);
  writeAscii(8, 'WAVE');
  writeAscii(12, 'fmt ');
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // AudioFormat = 1 (Linear PCM)
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRateHz, true);
  view.setUint32(28, sampleRateHz * numChannels * bytesPerSample, true);
  view.setUint16(32, numChannels * bytesPerSample, true);
  view.setUint16(34, bytesPerSample * 8, true);
  writeAscii(36, 'data');
  view.setUint32(40, dataByteLength, true);

  let byteOffset = 44;
  for (let i = 0; i < pcmSamples.length; i++) {
    view.setInt16(byteOffset, pcmSamples[i], true);
    byteOffset += 2;
  }

  return new Uint8Array(buffer);
}

/**
 * Stateful recorder managing logical-turn `captureAttemptId`, WebAudio worklet graph,
 * and 16 kHz WAV assembly.
 */
export class AudioRecorder {
  private sessionId: string;
  private turnGeneration: number;
  private captureAttemptId = 0;
  private recordingActive = false;
  private lifecycleState: RecorderLifecycleState = 'IDLE';
  private lifecycleEpoch = 0;
  private resampler: StatefulResampler = new StatefulResampler(48000, TARGET_SAMPLE_RATE_HZ);
  private pcmChunks: Int16Array[] = [];
  private totalSamples = 0;
  private clippedSamples = 0;
  private activity = new SpeechActivityDetector();
  private processing: CaptureProcessingStatus = { echoCancellation: 'unreported', noiseSuppression: 'unreported', autoGainControl: 'unreported' };
  public get processingStatus(): CaptureProcessingStatus { return { ...this.processing }; }

  private mediaStream: MediaStream | null = null;
  private captureContext: AudioContext | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private mediaDevicesRef: Pick<MediaDevices, 'getUserMedia' | 'addEventListener' | 'removeEventListener'> | null = null;
  private deviceChangeHandler: (() => void) | null = null;
  private onFrameTelemetryCallback: ((frame: WorkletTelemetryFrame) => void) | null = null;
  private onBackpressureCallback: (() => void) | null = null;
  private onSpeechActivityCallback: (() => void) | null = null;
  private onSilenceTimeoutCallback: (() => void) | null = null;
  private silenceMs = DEFAULT_SILENCE_MS;
  private silenceTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(sessionId: string, turnGeneration: number = 1) {
    this.sessionId = sessionId;
    this.turnGeneration = turnGeneration;
  }

  public get state(): RecorderLifecycleState {
    return this.lifecycleState;
  }

  public get isRecording(): boolean {
    return this.recordingActive;
  }

  public get currentCaptureAttemptId(): number {
    return this.captureAttemptId;
  }

  public get capturedSamplesCount(): number {
    return this.totalSamples;
  }

  /**
   * Advance to a new logical turn (resets `captureAttemptId` to 0).
   */
  public setTurnGeneration(nextTurnGeneration: number, preserveBufferedAudio = false): void {
    if (nextTurnGeneration !== this.turnGeneration) {
      this.turnGeneration = nextTurnGeneration;
      this.captureAttemptId = 0;
      if (!preserveBufferedAudio) this.resetBuffers();
    }
  }

  /**
   * Begin or re-record a voice capture on the current `turnGeneration`.
   * Re-recording increments `captureAttemptId` without incrementing `turnGeneration`.
   */
  public startCaptureAttempt(): { turnGeneration: number; captureAttemptId: number } {
    this.captureAttemptId += 1;
    this.recordingActive = true;
    this.lifecycleState = 'RECORDING';
    this.resetBuffers();
    return {
      turnGeneration: this.turnGeneration,
      captureAttemptId: this.captureAttemptId,
    };
  }

  /**
   * Request browser microphone permission, register the AudioWorklet processor, connect
   * `MediaStreamAudioSourceNode -> AudioWorkletNode`, and begin streaming 128-sample frames
   * through the stateful 16 kHz resampler.
   */
  public async startMicrophoneCapture(
    options: MicrophoneCaptureOptions = {},
  ): Promise<{ turnGeneration: number; captureAttemptId: number }> {
    const silenceMs = options.silenceMs ?? DEFAULT_SILENCE_MS;
    if (!Number.isFinite(silenceMs) || silenceMs <= 0) {
      throw new RangeError('silenceMs must be a positive finite number of milliseconds.');
    }
    const epoch = ++this.lifecycleEpoch;
    await this.cleanupAudioGraph();
    this.lifecycleState = 'REQUESTING_PERMISSION';

    const mediaDevices =
      options.mediaDevices ??
      (typeof navigator !== 'undefined' && navigator.mediaDevices ? navigator.mediaDevices : undefined);

    if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
      this.lifecycleState = 'DEVICE_UNAVAILABLE_TEXT_FALLBACK';
      throw new MicrophoneCaptureError(
        'MEDIA_DEVICES_UNAVAILABLE',
        'Browser navigator.mediaDevices.getUserMedia is unavailable; use typed fallback.',
        this.lifecycleState,
      );
    }

    const inputDeviceId = loadInputDeviceId();
    let supported: MediaTrackSupportedConstraints | undefined;
    try { supported = mediaDevices.getSupportedConstraints?.(); } catch { /* Some browsers do not expose constraint discovery. */ }
    let stream: MediaStream;
    try {
      stream = await mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          ...(supported && !supported.echoCancellation ? {} : { echoCancellation: true }),
          ...(supported && !supported.noiseSuppression ? {} : { noiseSuppression: true }),
          ...(supported && !supported.autoGainControl ? {} : { autoGainControl: true }),
          ...(inputDeviceId ? { deviceId: { exact: inputDeviceId } } : {}),
          ...(options.constraints ?? {}),
        },
        video: false,
      });
    } catch (err) {
      const errName = err instanceof Error ? err.name : 'UnknownError';
      if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError' || errName === 'SecurityError') {
        this.lifecycleState = 'PERMISSION_DENIED_TEXT_FALLBACK';
        throw new MicrophoneCaptureError(
          'MIC_PERMISSION_DENIED',
          'Microphone permission was denied; switched to typed fallback.',
          this.lifecycleState,
        );
      }
      this.lifecycleState = 'DEVICE_UNAVAILABLE_TEXT_FALLBACK';
      throw new MicrophoneCaptureError(
        'MIC_DEVICE_UNAVAILABLE',
        `Unable to open microphone (${errName}); switched to typed fallback. Choose System default in Microphone input settings if the selected device is unavailable.`,
        this.lifecycleState,
      );
    }

    if (epoch !== this.lifecycleEpoch) {
      for (const track of stream.getTracks()) track.stop();
      throw new DOMException('Microphone capture cancelled', 'AbortError');
    }
    const attemptMeta = this.startCaptureAttempt();
    this.mediaStream = stream;
    this.processing = { echoCancellation: 'unreported', noiseSuppression: 'unreported', autoGainControl: 'unreported' };
    try {
      const settings = stream.getAudioTracks()[0]?.getSettings?.();
      for (const key of ['echoCancellation', 'noiseSuppression', 'autoGainControl'] as const) {
        if (typeof settings?.[key] === 'boolean') this.processing[key] = settings[key] ? 'enabled' : 'disabled';
      }
    } catch { /* Missing track settings do not imply that browser processing was applied. */ }
    this.mediaDevicesRef = mediaDevices;
    this.onFrameTelemetryCallback = options.onFrameTelemetry ?? null;
    this.onBackpressureCallback = options.onBackpressureLimitReached ?? null;
    this.onSpeechActivityCallback = options.onSpeechActivity ?? null;
    this.onSilenceTimeoutCallback = options.onSilenceTimeout ?? null;
    this.silenceMs = silenceMs;

    let blobUrl: string | null = null;
    try {
      const ctx = options.audioContextFactory
        ? options.audioContextFactory()
        : new AudioContext({ latencyHint: 'interactive' });
      this.captureContext = ctx;
      if (ctx.state === 'suspended' && typeof ctx.resume === 'function') {
        await ctx.resume();
      }
      this.resampler.setInputSampleRate(ctx.sampleRate || 48000);

      if (!ctx.audioWorklet || typeof ctx.audioWorklet.addModule !== 'function') {
        throw new Error('AudioWorklet is not supported by the active AudioContext.');
      }

      if (typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function' && typeof Blob !== 'undefined') {
        const blob = new Blob([VCC_AUDIO_WORKLET_SOURCE], { type: 'application/javascript' });
        blobUrl = URL.createObjectURL(blob);
        await ctx.audioWorklet.addModule(blobUrl);
      } else {
        await ctx.audioWorklet.addModule('data:application/javascript,' + encodeURIComponent(VCC_AUDIO_WORKLET_SOURCE));
      }

      if (epoch !== this.lifecycleEpoch) throw new DOMException('Microphone capture cancelled', 'AbortError');
      const sourceNode = ctx.createMediaStreamSource(stream);
      const workletNode = options.workletNodeFactory
        ? options.workletNodeFactory(ctx, 'vcc-capture-worklet')
        : new AudioWorkletNode(ctx, 'vcc-capture-worklet', {
            numberOfInputs: 1,
            numberOfOutputs: 0,
            channelCount: 1,
          });

      this.sourceNode = sourceNode;
      this.workletNode = workletNode;

      workletNode.port.onmessage = (event: MessageEvent) => {
        if (!this.recordingActive) {
          return;
        }
        const payload = event.data as {
          type?: string;
          samples?: Float32Array;
          sampleRate?: number;
        } | null;
        if (!payload || payload.type !== 'AUDIO_FRAME' || !payload.samples) {
          return;
        }
        const rate = typeof payload.sampleRate === 'number' && payload.sampleRate > 0
          ? payload.sampleRate
          : ctx.sampleRate || 48000;
        const telemetry = this.pushFloat32Frame(payload.samples, rate);
        if (telemetry && this.onFrameTelemetryCallback) {
          this.onFrameTelemetryCallback(telemetry);
        }
      };

      const tracks = typeof stream.getAudioTracks === 'function' ? stream.getAudioTracks() : [];
      for (const track of tracks) {
        track.onended = () => {
          this.handleDeviceLost('Microphone audio track ended unexpectedly during capture.', options.onDeviceLost);
        };
      }

      if (typeof mediaDevices.addEventListener === 'function') {
        this.deviceChangeHandler = () => {
          const activeTracks = typeof stream.getAudioTracks === 'function' ? stream.getAudioTracks() : [];
          const allEnded = activeTracks.length > 0 && activeTracks.every((t) => t.readyState === 'ended');
          if (allEnded) {
            this.handleDeviceLost('Microphone device disconnected on devicechange.', options.onDeviceLost);
          }
        };
        mediaDevices.addEventListener('devicechange', this.deviceChangeHandler);
      }

      sourceNode.connect(workletNode);
      return attemptMeta;
    } catch (err) {
      await this.cleanupAudioGraph();
      this.recordingActive = false;
      this.lifecycleState = 'ERROR_TEXT_FALLBACK';
      const msg = err instanceof Error ? err.message : String(err);
      throw new MicrophoneCaptureError(
        'WORKLET_INIT_FAILED',
        `Failed to initialize AudioWorklet capture graph: ${msg}`,
        this.lifecycleState,
      );
    } finally {
      if (blobUrl && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
        try {
          URL.revokeObjectURL(blobUrl);
        } catch {
          // Ignore URL revocation errors
        }
      }
    }
  }

  public pushFloat32Frame(samples: Float32Array, inputSampleRateHz: number): WorkletTelemetryFrame | null {
    if (!this.recordingActive) {
      return null;
    }
    this.resampler.setInputSampleRate(inputSampleRateHz);
    const frame = this.resampler.processFrame(samples);
    const maxSamples = Math.min(
      Math.floor(MAX_RECORDING_DURATION_SEC * TARGET_SAMPLE_RATE_HZ),
      Math.floor((MAX_WAV_BYTES - 44) / 2),
    );
    const remaining = maxSamples - this.totalSamples;
    if (remaining <= 0) {
      this.recordingActive = false;
      this.clearSilenceDeadline();
      if (this.onBackpressureCallback) {
        this.onBackpressureCallback();
      }
      return null;
    }
    const slice = frame.pcm16.length > remaining ? frame.pcm16.subarray(0, remaining).slice() : frame.pcm16;
    if (slice.length > 0) {
      this.pcmChunks.push(slice);
      this.totalSamples += slice.length;
    }
    this.clippedSamples += frame.clippedSamples;
    if (this.totalSamples >= maxSamples) {
      this.recordingActive = false;
      this.clearSilenceDeadline();
      if (this.onBackpressureCallback) {
        this.onBackpressureCallback();
      }
    }
    if (this.recordingActive && this.activity.push(samples, inputSampleRateHz)) {
      this.resetSilenceDeadline();
      this.onSpeechActivityCallback?.();
    }
    return frame;
  }

  /**
   * Snapshot and consume the current segment without stopping the microphone graph.
   * Later frames stay in the next segment, including fractional resampler carry.
   * An empty drain throws without changing capture state.
   */
  public drainMicrophoneCapture(): CapturedAudio {
    const result = this.assembleRecording();
    this.clearSampleBuffers();
    this.clearSilenceDeadline();
    // A bounded segment can roll over without closing the live microphone graph.
    if (this.captureContext && this.lifecycleState === 'RECORDING') this.recordingActive = true;
    return result;
  }

  public async stopMicrophoneCapture(): Promise<AssembledWavRecording> {
    this.lifecycleState = 'STOPPING';
    await this.cleanupAudioGraph();
    const result = this.finalizeRecording();
    this.lifecycleState = 'IDLE';
    return result;
  }

  public finalizeRecording(): AssembledWavRecording {
    this.recordingActive = false;
    this.clearSilenceDeadline();
    return this.assembleRecording();
  }

  private assembleRecording(): CapturedAudio {
    if (this.totalSamples === 0) {
      throw new Error('Cannot finalize empty voice recording (0 samples captured).');
    }

    const merged = new Int16Array(this.totalSamples);
    let offset = 0;
    let sumSq = 0;
    let peak = 0;

    for (const chunk of this.pcmChunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
      for (let i = 0; i < chunk.length; i++) {
        const norm = chunk[i] / 32768.0;
        const absNorm = Math.abs(norm);
        if (absNorm > peak) {
          peak = absNorm;
        }
        sumSq += norm * norm;
      }
    }

    const rmsNormalized = Number(Math.min(1, Math.sqrt(sumSq / this.totalSamples)).toFixed(6));
    const peakNormalized = Number(Math.min(1, peak).toFixed(6));
    const durationSec = Number((this.totalSamples / TARGET_SAMPLE_RATE_HZ).toFixed(4));
    const wavBytes = encodePcm16ToWavBytes(merged, TARGET_SAMPLE_RATE_HZ);

    return {
      sessionId: this.sessionId,
      turnGeneration: this.turnGeneration,
      captureAttemptId: this.captureAttemptId,
      wavBytes,
      sampleRateHz: TARGET_SAMPLE_RATE_HZ,
      durationSec,
      rmsNormalized,
      peakNormalized,
      lowEnergyWarning: rmsNormalized < LOW_ENERGY_RMS_THRESHOLD,
      clippedSamples: this.clippedSamples,
      speechLikeActivityDetected: this.activity.hasActivity,
    };
  }

  public async dispose(): Promise<void> {
    this.lifecycleEpoch++;
    this.recordingActive = false;
    await this.cleanupAudioGraph();
    this.resetBuffers();
    this.lifecycleState = 'IDLE';
  }

  private handleDeviceLost(reason: string, onDeviceLost?: (reason: string) => void): void {
    this.recordingActive = false;
    this.lifecycleState = 'DEVICE_LOST_TEXT_FALLBACK';
    void this.cleanupAudioGraph();
    if (onDeviceLost) {
      onDeviceLost(reason);
    }
  }

  private resetSilenceDeadline(): void {
    this.clearSilenceDeadline();
    if (!this.onSilenceTimeoutCallback) return;
    this.silenceTimer = setTimeout(() => {
      this.silenceTimer = null;
      if (this.recordingActive) this.onSilenceTimeoutCallback?.();
    }, this.silenceMs);
  }

  private clearSilenceDeadline(): void {
    if (this.silenceTimer !== null) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
  }

  private async cleanupAudioGraph(): Promise<void> {
    this.clearSilenceDeadline();
    this.onSpeechActivityCallback = null;
    this.onSilenceTimeoutCallback = null;
    if (this.mediaDevicesRef && this.deviceChangeHandler && typeof this.mediaDevicesRef.removeEventListener === 'function') {
      try {
        this.mediaDevicesRef.removeEventListener('devicechange', this.deviceChangeHandler);
      } catch {
        // Ignore listener removal errors
      }
    }
    this.deviceChangeHandler = null;
    this.mediaDevicesRef = null;
    this.onFrameTelemetryCallback = null;
    this.onBackpressureCallback = null;

    if (this.workletNode) {
      try {
        this.workletNode.port.postMessage({ type: 'STOP' });
        this.workletNode.port.onmessage = null;
        this.workletNode.disconnect();
      } catch {
        // Ignore worklet cleanup errors
      }
      this.workletNode = null;
    }

    if (this.sourceNode) {
      try {
        this.sourceNode.disconnect();
      } catch {
        // Ignore source disconnect errors
      }
      this.sourceNode = null;
    }

    if (this.mediaStream) {
      const tracks = typeof this.mediaStream.getTracks === 'function' ? this.mediaStream.getTracks() : [];
      for (const track of tracks) {
        try {
          track.onended = null;
          track.stop();
        } catch {
          // Ignore track stop errors
        }
      }
      this.mediaStream = null;
    }

    if (this.captureContext) {
      const ctx = this.captureContext;
      this.captureContext = null;
      if (ctx.state !== 'closed' && typeof ctx.close === 'function') {
        try {
          await ctx.close();
        } catch {
          // Ignore context close errors
        }
      }
    }
  }

  private clearSampleBuffers(): void {
    this.pcmChunks = [];
    this.totalSamples = 0;
    this.clippedSamples = 0;
    this.activity.reset();
  }

  private resetBuffers(): void {
    this.clearSampleBuffers();
    this.clearSilenceDeadline();
    this.resampler.reset();
  }
}
