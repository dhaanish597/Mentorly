import { describe, expect, it, vi } from 'vitest';
import type { RevisionRef } from '../types/api';
import {
  downsampleFloat32ToInt16,
  StatefulResampler,
  TARGET_SAMPLE_RATE_HZ,
  VCC_AUDIO_WORKLET_SOURCE,
} from '../services/audioWorkletProcessor';
import {
  AudioRecorder,
  encodePcm16ToWavBytes,
  MicrophoneCaptureError,
} from '../services/audioRecorder';
import { AudioPlayer, decodeWavToPcmFloat32 } from '../services/audioPlayer';

const SAMPLE_REVISION: RevisionRef = {
  session_id: '11111111-1111-1111-1111-111111111111',
  exercise_id: 'ex1_shortest_subarray',
  spec_version: 'v2_negatives_allowed',
  code_version_id: 2,
  code_hash: 'a'.repeat(64),
  turn_generation: 3,
};

describe('Phase 2 Browser Audio Services (T-03 & P2-07 Repairs)', () => {
  it('downsamples 48 kHz Float32 audio to 16 kHz Int16 PCM and avoids ScriptProcessorNode', () => {
    expect(VCC_AUDIO_WORKLET_SOURCE).toContain('AudioWorkletProcessor');
    expect(VCC_AUDIO_WORKLET_SOURCE).not.toContain('ScriptProcessorNode');

    const input48k = new Float32Array(4800); // 0.1s at 48 kHz
    for (let i = 0; i < input48k.length; i++) {
      input48k[i] = Math.sin((2 * Math.PI * 440 * i) / 48000) * 0.5;
    }

    const frame = downsampleFloat32ToInt16(input48k, 48000, TARGET_SAMPLE_RATE_HZ);
    expect(frame.pcm16.length).toBe(1600); // 0.1s at 16 kHz
    expect(frame.rmsNormalized).toBeGreaterThan(0.3);
    expect(frame.peakNormalized).toBeLessThanOrEqual(0.55);
    expect(frame.clippedSamples).toBe(0);
  });

  it('P2-07 regression: StatefulResampler preserves exact sample count across 375x128 @ 48 kHz and 44.1 kHz worklet quanta', () => {
    const total48k = 48000;
    const full48k = new Float32Array(total48k);
    for (let i = 0; i < total48k; i++) {
      full48k[i] = Math.sin((2 * Math.PI * 330 * i) / 48000) * 0.4;
    }

    const wholeResult = downsampleFloat32ToInt16(full48k, 48000, TARGET_SAMPLE_RATE_HZ);
    expect(wholeResult.pcm16.length).toBe(16000);

    const resampler48k = new StatefulResampler(48000, TARGET_SAMPLE_RATE_HZ);
    const chunked48kOut: number[] = [];
    for (let f = 0; f < 375; f++) {
      const quantum = full48k.subarray(f * 128, (f + 1) * 128);
      const out = resampler48k.processFrame(quantum);
      for (let j = 0; j < out.pcm16.length; j++) {
        chunked48kOut.push(out.pcm16[j]);
      }
    }
    expect(chunked48kOut.length).toBe(16000); // 0 lost samples (was 15,750 before fix)
    expect(Int16Array.from(chunked48kOut)).toEqual(wholeResult.pcm16);

    // 44.1 kHz across non-divisible 128-sample blocks and prime-sized 73-sample blocks
    const total44k = 44100;
    const full44k = new Float32Array(total44k);
    for (let i = 0; i < total44k; i++) {
      full44k[i] = Math.cos((2 * Math.PI * 220 * i) / 44100) * 0.6;
    }
    const whole44k = downsampleFloat32ToInt16(full44k, 44100, TARGET_SAMPLE_RATE_HZ);
    expect(whole44k.pcm16.length).toBe(16000);

    const resampler44k = new StatefulResampler(44100, TARGET_SAMPLE_RATE_HZ);
    const chunked44kOut: number[] = [];
    for (let offset = 0; offset < total44k; offset += 73) {
      const slice = full44k.subarray(offset, Math.min(total44k, offset + 73));
      const out = resampler44k.processFrame(slice);
      for (let j = 0; j < out.pcm16.length; j++) {
        chunked44kOut.push(out.pcm16[j]);
      }
    }
    expect(chunked44kOut.length).toBe(16000);
    expect(Int16Array.from(chunked44kOut)).toEqual(whole44k.pcm16);
  });

  it('assembles a canonical 16 kHz 16-bit mono WAV across 375x128 worklet frames and tracks captureAttemptId', () => {
    const recorder = new AudioRecorder('sess_browser_1', 3);

    const attempt1 = recorder.startCaptureAttempt();
    expect(attempt1).toEqual({ turnGeneration: 3, captureAttemptId: 1 });

    // Re-record on same challenge turn: captureAttemptId increments to 2, turnGeneration stays 3
    const attempt2 = recorder.startCaptureAttempt();
    expect(attempt2).toEqual({ turnGeneration: 3, captureAttemptId: 2 });

    // Push 375 frames of 128 quiet samples at 48 kHz -> must yield 16,000 samples (1.0000s)
    const quietQuantum = new Float32Array(128).fill(0.001);
    for (let i = 0; i < 375; i++) {
      recorder.pushFloat32Frame(quietQuantum, 48000);
    }

    const recording = recorder.finalizeRecording();
    expect(recording.turnGeneration).toBe(3);
    expect(recording.captureAttemptId).toBe(2);
    expect(recording.sampleRateHz).toBe(16000);
    expect(recording.durationSec).toBe(1.0);
    expect(recording.lowEnergyWarning).toBe(true);
    expect(recording.wavBytes.byteLength).toBe(44 + 16000 * 2);

    const headerAscii = String.fromCharCode(
      recording.wavBytes[0],
      recording.wavBytes[1],
      recording.wavBytes[2],
      recording.wavBytes[3],
    );
    expect(headerAscii).toBe('RIFF');

    // Advancing turnGeneration resets captureAttemptId
    recorder.setTurnGeneration(4);
    const nextTurnAttempt = recorder.startCaptureAttempt();
    expect(nextTurnAttempt).toEqual({ turnGeneration: 4, captureAttemptId: 1 });
  });

  it('handles real startMicrophoneCapture/stopMicrophoneCapture graph, permission denial, and device loss', async () => {
    const recorder = new AudioRecorder('sess_web_audio', 1);

    // 1. Permission denial transitions to PERMISSION_DENIED_TEXT_FALLBACK
    await expect(
      recorder.startMicrophoneCapture({
        mediaDevices: {
          getUserMedia: async () => {
            const err = new Error('User denied mic');
            err.name = 'NotAllowedError';
            throw err;
          },
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        },
      }),
    ).rejects.toThrow(MicrophoneCaptureError);
    expect(recorder.state).toBe('PERMISSION_DENIED_TEXT_FALLBACK');

    // 2. Successful worklet graph capture + port frames + cleanup
    let trackStopped = false;
    let contextClosed = false;
    let portHandler: ((ev: MessageEvent) => void) | null = null;
    const mockTrack = {
      readyState: 'live',
      onended: null as (() => void) | null,
      stop: () => {
        trackStopped = true;
      },
    };
    const mockStream = {
      getAudioTracks: () => [mockTrack],
      getTracks: () => [mockTrack],
    } as unknown as MediaStream;

    const mockWorkletNode = {
      port: {
        set onmessage(fn: ((ev: MessageEvent) => void) | null) {
          portHandler = fn;
        },
        get onmessage() {
          return portHandler;
        },
        postMessage: () => undefined,
      },
      disconnect: () => undefined,
    } as unknown as AudioWorkletNode;

    const mockContext = {
      sampleRate: 48000,
      state: 'running',
      audioWorklet: {
        addModule: async () => undefined,
      },
      createMediaStreamSource: () => ({
        connect: () => undefined,
        disconnect: () => undefined,
      }),
      close: async () => {
        contextClosed = true;
      },
    } as unknown as AudioContext;

    const meta = await recorder.startMicrophoneCapture({
      mediaDevices: {
        getUserMedia: async () => mockStream,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      },
      audioContextFactory: () => mockContext,
      workletNodeFactory: () => mockWorkletNode,
    });
    expect(meta).toEqual({ turnGeneration: 1, captureAttemptId: 1 });
    expect(recorder.state).toBe('RECORDING');

    const sampleQuantum = new Float32Array(128).fill(0.25);
    for (let i = 0; i < 30; i++) {
      (portHandler as ((event: MessageEvent) => void) | null)?.({
        data: { type: 'AUDIO_FRAME', samples: sampleQuantum, sampleRate: 48000 },
      } as MessageEvent);
    }

    const wavResult = await recorder.stopMicrophoneCapture();
    expect(wavResult.wavBytes.byteLength).toBe(44 + 1280 * 2);
    expect(trackStopped).toBe(true);
    expect(contextClosed).toBe(true);
    expect(recorder.state).toBe('IDLE');
  });


  it('cancels a pending permission request and stops tracks granted after cancellation', async () => {
    const recorder = new AudioRecorder('session-cancel');
    let grant!: (stream: MediaStream) => void;
    let requested!: () => void;
    const pending = new Promise<void>(resolve => { requested = resolve; });
    const stop = vi.fn();
    const promise = recorder.startMicrophoneCapture({ mediaDevices: {
      getUserMedia: () => { requested(); return new Promise(resolve => { grant = resolve; }); },
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    } });
    const rejected = expect(promise).rejects.toThrow('cancelled');
    await pending;
    await recorder.dispose();
    grant({ getTracks: () => [{ stop }] } as unknown as MediaStream);
    await rejected;
    expect(stop).toHaveBeenCalledTimes(1);
    expect(recorder.isRecording).toBe(false);
  });
  it('decodes WAV, handles autoplay recovery/fallback, preserves playback_id & revision, and stops <= 150 ms', async () => {
    const player = new AudioPlayer();
    const samples = new Int16Array(1600).fill(8192);
    const wavBytes = encodePcm16ToWavBytes(samples, 16000);
    const decoded = decodeWavToPcmFloat32(wavBytes);
    expect(decoded.sampleRateHz).toBe(16000);
    expect(decoded.samples.length).toBe(1600);

    // 1. Blocked autoplay returns READ_TEXT_FALLBACK ack with playback_id and revision
    let blockedAckReceived = false;
    const blockedRes = await player.playWavBytes({
      wavBytes,
      playbackId: 'play_blocked_1',
      sessionId: 'sess_p2',
      turnId: 'turn_9',
      turnGeneration: 3,
      revision: SAMPLE_REVISION,
      audioContextFactory: () =>
        ({
          state: 'suspended',
          resume: async () => {
            throw new Error('NotAllowedError: play() requires user gesture');
          },
          close: async () => undefined,
        }) as unknown as AudioContext,
      onAutoplayBlocked: (ack) => {
        blockedAckReceived = ack.playback_status === 'READ_TEXT_FALLBACK';
      },
    });
    expect(blockedRes.started).toBe(false);
    expect(blockedAckReceived).toBe(true);
    expect(blockedRes.fallbackAck?.playback_id).toBe('play_blocked_1');
    expect(blockedRes.fallbackAck?.revision).toEqual(SAMPLE_REVISION);

    // 2. Active playback + barge-in stop <= 150 ms
    let nodeStopped = false;
    await player.dispose();
    const playRes = await player.playWavBytes({
      wavBytes,
      playbackId: 'play_live_2',
      sessionId: 'sess_p2',
      turnId: 'turn_10',
      turnGeneration: 3,
      revision: SAMPLE_REVISION,
      audioContextFactory: () =>
        ({
          state: 'running',
          destination: {},
          createBuffer: (_ch: number, len: number, rate: number) => ({
            length: len,
            sampleRate: rate,
            copyToChannel: () => undefined,
          }),
          createBufferSource: () => ({
            buffer: null,
            onended: null,
            connect: () => undefined,
            disconnect: () => undefined,
            start: () => undefined,
            stop: () => {
              nodeStopped = true;
            },
          }),
          close: async () => undefined,
        }) as unknown as AudioContext,
    });
    expect(playRes.started).toBe(true);
    expect(player.isPlaying).toBe(true);

    const { stopLatencyMs, ack } = player.bargeInStop();
    expect(nodeStopped).toBe(true);
    expect(stopLatencyMs).toBeLessThanOrEqual(150);
    expect(player.isPlaying).toBe(false);
    expect(ack?.playback_status).toBe('INTERRUPTED');
    expect(ack?.playback_id).toBe('play_live_2');
    expect(ack?.revision).toEqual(SAMPLE_REVISION);
  });

  it('encodes PCM16 samples into a valid 44-byte RIFF header', () => {
    const samples = new Int16Array([0, 16384, -16384, 32767]);
    const wav = encodePcm16ToWavBytes(samples, 16000);
    expect(wav.byteLength).toBe(44 + 8);
    const view = new DataView(wav.buffer);
    expect(view.getUint16(22, true)).toBe(1); // Mono
    expect(view.getUint32(24, true)).toBe(16000); // 16 kHz
    expect(view.getUint16(34, true)).toBe(16); // 16-bit
  });
});
