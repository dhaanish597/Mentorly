/**
 * Browser Coach TTS Player & Instant Barge-In Controller (`audioPlayer.ts`).
 *
 * Implements Plan §8.4 / Phase 2 Prompt §B.6 & Fix P2-07:
 * - Uses a dedicated playback `AudioContext` (strictly independent of the microphone
 *   capture `AudioContext` so barge-in never suspends or breaks microphone capture).
 * - Implements real PCM16 WAV decoding (`decodeWavToPcmFloat32` + `AudioContext.decodeAudioData` /
 *   `createBuffer`), `AudioBufferSourceNode` graph connection, autoplay `suspended -> resume()`
 *   recovery with clean `READ_TEXT_FALLBACK` degradation when blocked, completion/interruption
 *   acknowledgements preserving `playback_id` and `RevisionRef`, and resource release.
 * - Stops scheduled sources synchronously and reports local callback latency; real
 *   audible barge-in latency requires browser/device measurement.
 */

import type { RevisionRef, VoicePlaybackAckRequest } from '../types/api';
import { DEFAULT_AUDIO_PREFERENCES, shouldRequestVoice, updateAudioPreferences, type PlaybackPreferences } from '../voice/preferences';

export interface PlaybackSourceHandle {
  stop: () => void;
  disconnect?: () => void;
  startedAtMs: number;
}

export interface DecodedWavData {
  readonly sampleRateHz: number;
  readonly numChannels: number;
  readonly samples: Float32Array;
  readonly durationMs: number;
}

export interface PlayWavBytesParams {
  readonly wavBytes: Uint8Array | ArrayBuffer;
  readonly playbackId?: string;
  readonly sessionId: string;
  readonly turnId: string;
  readonly turnGeneration: number;
  readonly revision?: RevisionRef | null;
  readonly audioContextFactory?: () => AudioContext;
  readonly onEnded?: (ack: VoicePlaybackAckRequest) => void;
  readonly onAutoplayBlocked?: (ack: VoicePlaybackAckRequest) => void;
}

/**
 * Deterministically parse a 16-bit PCM RIFF/WAVE container into normalized Float32 samples.
 */
export function decodeWavToPcmFloat32(wavInput: Uint8Array | ArrayBuffer): DecodedWavData {
  const bytes = wavInput instanceof Uint8Array ? wavInput : new Uint8Array(wavInput);
  if (bytes.byteLength < 44) {
    throw new Error(`WAV buffer too short (${bytes.byteLength} bytes < 44-byte RIFF header).`);
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const magicRiff = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
  const magicWave = String.fromCharCode(bytes[8], bytes[9], bytes[10], bytes[11]);
  if (magicRiff !== 'RIFF' || magicWave !== 'WAVE') {
    throw new Error('Invalid RIFF/WAVE magic header in playback audio.');
  }

  const audioFormat = view.getUint16(20, true);
  const numChannels = view.getUint16(22, true);
  const sampleRateHz = view.getUint32(24, true);
  const bitsPerSample = view.getUint16(34, true);
  if (audioFormat !== 1 || bitsPerSample !== 16 || numChannels < 1 || sampleRateHz <= 0) {
    throw new Error(
      `Unsupported WAV format (format=${audioFormat}, channels=${numChannels}, rate=${sampleRateHz}, bits=${bitsPerSample}).`,
    );
  }

  let dataOffset = 12;
  let dataByteLength = 0;
  while (dataOffset + 8 <= bytes.byteLength) {
    const chunkId = String.fromCharCode(
      bytes[dataOffset],
      bytes[dataOffset + 1],
      bytes[dataOffset + 2],
      bytes[dataOffset + 3],
    );
    const chunkSize = view.getUint32(dataOffset + 4, true);
    if (chunkId === 'data') {
      dataOffset += 8;
      dataByteLength = Math.min(chunkSize, bytes.byteLength - dataOffset);
      break;
    }
    dataOffset += 8 + chunkSize + (chunkSize % 2);
  }

  if (dataByteLength <= 0) {
    throw new Error('WAV container is missing a non-empty data chunk.');
  }

  const frameSize = numChannels * 2;
  const numFrames = Math.floor(dataByteLength / frameSize);
  const samples = new Float32Array(numFrames);
  for (let i = 0; i < numFrames; i++) {
    const int16 = view.getInt16(dataOffset + i * frameSize, true);
    samples[i] = int16 < 0 ? int16 / 32768.0 : int16 / 32767.0;
  }

  const durationMs = Math.max(1, Math.round((numFrames / sampleRateHz) * 1000));
  return {
    sampleRateHz,
    numChannels,
    samples,
    durationMs,
  };
}

export class AudioPlayer {
  private activePlaybackId = '';
  private activeTurnId: string | null = null;
  private activeSessionId: string | null = null;
  private activeTurnGeneration = 0;
  private activeRevision: RevisionRef | null = null;
  private activeSources: Set<PlaybackSourceHandle> = new Set();
  private playbackContext: AudioContext | null = null;
  private startedAtPerfMs = 0;
  private isPlayingState = false;
  private playbackEpoch = 0;
  private preferences: PlaybackPreferences = DEFAULT_AUDIO_PREFERENCES;
  private gain: GainNode | null = null;
  private activeNode: AudioBufferSourceNode | null = null;

  public setPreferences(preferences: PlaybackPreferences): void {
    this.preferences = updateAudioPreferences(DEFAULT_AUDIO_PREFERENCES, preferences);
    if (this.gain) this.gain.gain.value = this.preferences.muted ? 0 : this.preferences.volume;
    if (this.activeNode?.playbackRate) this.activeNode.playbackRate.value = this.preferences.speed;
    if (!shouldRequestVoice(this.preferences)) this.bargeInStop();
  }

  /** Call directly inside the user's click, before awaiting a voice network request.
   * Activates the dedicated playback context without scheduling audio or touching capture.
   */
  public async unlockAudioFromGesture(audioContextFactory?: () => AudioContext): Promise<boolean> {
    let context = this.playbackContext;
    if (!context || context.state === 'closed') {
      if (!audioContextFactory && typeof AudioContext === 'undefined') return false;
      context = audioContextFactory ? audioContextFactory() : new AudioContext();
      this.playbackContext = context;
    }
    try {
      // resume is invoked synchronously while transient user activation is present.
      if (context.state === 'suspended') await context.resume();
      return this.playbackContext === context && context.state === 'running';
    } catch { return false; /* Expose blocked activation to the caller; text remains available. */ }
  }

  public get isPlaying(): boolean {
    return this.isPlayingState;
  }

  public get currentPlaybackId(): string {
    return this.activePlaybackId;
  }

  public get currentRevision(): RevisionRef | null {
    return this.activeRevision;
  }

  /**
   * Start tracking playback for a specific coaching turn.
   */
  public beginTurnPlayback(
    sessionId: string,
    turnId: string,
    turnGeneration: number,
    sourceHandle?: PlaybackSourceHandle,
    options?: { playbackId?: string; revision?: RevisionRef | null },
  ): void {
    if (this.isPlayingState) {
      this.bargeInStop();
    }
    this.activePlaybackId = options?.playbackId ?? `play_${turnId}_${turnGeneration}`;
    this.activeSessionId = sessionId;
    this.activeTurnId = turnId;
    this.activeTurnGeneration = turnGeneration;
    this.activeRevision = options?.revision ?? null;
    this.startedAtPerfMs = performance.now();
    this.isPlayingState = true;
    if (sourceHandle) {
      this.activeSources.add(sourceHandle);
    }
  }

  /**
   * Decode WAV bytes in a dedicated playback `AudioContext`, handle browser autoplay
   * suspension (`suspended -> resume()`), schedule `AudioBufferSourceNode`, and emit
   * completion or fallback acknowledgements bound to `playbackId` and `revision`.
   */
  public async playWavBytes(
    params: PlayWavBytesParams,
  ): Promise<{ started: boolean; fallbackAck: VoicePlaybackAckRequest | null }> {
    this.bargeInStop();
    const epoch = ++this.playbackEpoch;
    if (!shouldRequestVoice(this.preferences)) {
      const fallbackAck = AudioPlayer.buildReadTextFallbackAck(params.sessionId, params.turnId, params.turnGeneration, params.playbackId, params.revision);
      params.onAutoplayBlocked?.(fallbackAck);
      return { started: false, fallbackAck };
    }
    const playbackId = params.playbackId ?? `play_${params.turnId}_${params.turnGeneration}`;
    const revision = params.revision ?? null;
    const decoded = decodeWavToPcmFloat32(params.wavBytes);

    let ctx = this.playbackContext;
    if (!ctx || ctx.state === 'closed') {
      if (params.audioContextFactory) {
        ctx = params.audioContextFactory();
      } else if (typeof AudioContext !== 'undefined') {
        ctx = new AudioContext();
      } else {
        const fallbackAck = AudioPlayer.buildReadTextFallbackAck(
          params.sessionId,
          params.turnId,
          params.turnGeneration,
          playbackId,
          revision,
        );
        if (params.onAutoplayBlocked) {
          params.onAutoplayBlocked(fallbackAck);
        }
        return { started: false, fallbackAck };
      }
      this.playbackContext = ctx;
    }

    if (ctx.state === 'suspended' && typeof ctx.resume === 'function') {
      try {
        await ctx.resume();
      } catch {
        const fallbackAck = AudioPlayer.buildReadTextFallbackAck(
          params.sessionId,
          params.turnId,
          params.turnGeneration,
          playbackId,
          revision,
        );
        if (params.onAutoplayBlocked) {
          params.onAutoplayBlocked(fallbackAck);
        }
        return { started: false, fallbackAck };
      }
      if ((ctx.state as string) === 'suspended') {
        const fallbackAck = AudioPlayer.buildReadTextFallbackAck(
          params.sessionId,
          params.turnId,
          params.turnGeneration,
          playbackId,
          revision,
        );
        if (params.onAutoplayBlocked) {
          params.onAutoplayBlocked(fallbackAck);
        }
        return { started: false, fallbackAck };
      }
    }

    let audioBuffer: AudioBuffer;
    if (typeof ctx.createBuffer === 'function') {
      audioBuffer = ctx.createBuffer(1, decoded.samples.length, decoded.sampleRateHz);
      if (typeof audioBuffer.copyToChannel === 'function') {
        audioBuffer.copyToChannel(new Float32Array(decoded.samples), 0);
      } else if (typeof audioBuffer.getChannelData === 'function') {
        audioBuffer.getChannelData(0).set(decoded.samples);
      }
    } else if (typeof ctx.decodeAudioData === 'function') {
      const rawBytes =
        params.wavBytes instanceof Uint8Array
          ? params.wavBytes.buffer.slice(
              params.wavBytes.byteOffset,
              params.wavBytes.byteOffset + params.wavBytes.byteLength,
            )
          : params.wavBytes.slice(0);
      audioBuffer = await ctx.decodeAudioData(rawBytes as ArrayBuffer);
    } else {
      throw new Error('Playback AudioContext supports neither createBuffer nor decodeAudioData.');
    }

    if (epoch !== this.playbackEpoch) return { started: false, fallbackAck: null };
    const sourceNode = ctx.createBufferSource();
    sourceNode.buffer = audioBuffer;
    if (sourceNode.playbackRate) sourceNode.playbackRate.value = this.preferences.speed;
    if (!this.gain && typeof ctx.createGain === 'function') {
      this.gain = ctx.createGain();
      this.gain.connect(ctx.destination);
    }
    if (this.gain) this.gain.gain.value = this.preferences.volume;
    sourceNode.connect(this.gain ?? ctx.destination);
    this.activeNode = sourceNode;

    let stoppedManually = false;
    const handle: PlaybackSourceHandle = {
      startedAtMs: performance.now(),
      stop: () => {
        stoppedManually = true;
        try {
          sourceNode.onended = null;
          sourceNode.stop(0);
        } catch {
          // Ignore already-stopped source errors
        }
        try {
          sourceNode.disconnect();
        } catch {
          // Ignore disconnect errors
        }
      },
      disconnect: () => {
        try {
          sourceNode.disconnect();
        } catch {
          // Ignore disconnect errors
        }
      },
    };

    this.beginTurnPlayback(params.sessionId, params.turnId, params.turnGeneration, handle, {
      playbackId,
      revision,
    });

    sourceNode.onended = () => {
      try {
        sourceNode.disconnect();
      } catch {
        // Ignore disconnect errors
      }
      this.activeSources.delete(handle);
      if (!stoppedManually && this.isPlayingState && this.activePlaybackId === playbackId) {
        const completedAck = this.markCompleted();
        if (completedAck && params.onEnded) {
          params.onEnded(completedAck);
        }
      }
    };

    sourceNode.start(0);
    return { started: true, fallbackAck: null };
  }

  /**
   * Stop active playback sources and report local stop callback duration
   * without touching the microphone capture context, and return `INTERRUPTED` ack.
   */
  public bargeInStop(): {
    stopLatencyMs: number;
    ack: VoicePlaybackAckRequest | null;
  } {
    this.playbackEpoch++;
    const t0 = performance.now();
    for (const src of this.activeSources) {
      try {
        src.stop();
      } catch {
        // Ignore already-stopped source errors
      }
      if (src.disconnect) {
        try {
          src.disconnect();
        } catch {
          // Ignore disconnect errors
        }
      }
    }
    this.activeSources.clear();
    this.activeNode = null;
    const stopLatencyMs = Math.max(0, Math.round(performance.now() - t0));

    if (!this.isPlayingState || !this.activeSessionId || !this.activeTurnId) {
      this.isPlayingState = false;
      return { stopLatencyMs, ack: null };
    }

    const playedDurationMs = Math.max(0, Math.round(performance.now() - this.startedAtPerfMs));
    const ack: VoicePlaybackAckRequest = {
      playback_id: this.activePlaybackId,
      session_id: this.activeSessionId,
      turn_id: this.activeTurnId,
      turn_generation: this.activeTurnGeneration,
      revision: this.activeRevision,
      playback_status: 'INTERRUPTED',
      played_duration_ms: playedDurationMs,
    };
    this.isPlayingState = false;
    return { stopLatencyMs, ack };
  }

  /**
   * Mark the current turn's playback as naturally completed and return `COMPLETED` ack.
   */
  public markCompleted(): VoicePlaybackAckRequest | null {
    if (!this.activeSessionId || !this.activeTurnId) {
      return null;
    }
    const playedDurationMs = Math.max(0, Math.round(performance.now() - this.startedAtPerfMs));
    for (const src of this.activeSources) {
      if (src.disconnect) {
        try {
          src.disconnect();
        } catch {
          // Ignore disconnect errors
        }
      }
    }
    this.activeSources.clear();
    this.isPlayingState = false;
    return {
      playback_id: this.activePlaybackId,
      session_id: this.activeSessionId,
      turn_id: this.activeTurnId,
      turn_generation: this.activeTurnGeneration,
      revision: this.activeRevision,
      playback_status: 'COMPLETED',
      played_duration_ms: playedDurationMs,
    };
  }

  public async dispose(): Promise<void> {
    this.bargeInStop();
    if (this.playbackContext) {
      const ctx = this.playbackContext;
      this.playbackContext = null;
      this.gain?.disconnect(); this.gain = null;
      if (ctx.state !== 'closed' && typeof ctx.close === 'function') {
        try {
          await ctx.close();
        } catch {
          // Ignore close errors
        }
      }
    }
  }

  /**
   * Produce a `READ_TEXT_FALLBACK` acknowledgement when TTS is degraded or muted.
   */
  public static buildReadTextFallbackAck(
    sessionId: string,
    turnId: string,
    turnGeneration: number,
    playbackId: string = '',
    revision: RevisionRef | null = null,
  ): VoicePlaybackAckRequest {
    return {
      playback_id: playbackId || `play_${turnId}_${turnGeneration}`,
      session_id: sessionId,
      turn_id: turnId,
      turn_generation: turnGeneration,
      revision,
      playback_status: 'READ_TEXT_FALLBACK',
      played_duration_ms: 0,
    };
  }
}
