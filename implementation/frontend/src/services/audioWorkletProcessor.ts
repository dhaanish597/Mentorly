/**
 * Browser AudioWorklet Capture & Stateful 16 kHz Resampler (`audioWorkletProcessor.ts`).
 *
 * Implements Plan §8.1 / Phase 2 Prompt §B.6 & Fix P2-07:
 * - Uses modern `AudioWorkletProcessor` (NEVER deprecated `ScriptProcessorNode`).
 * - Implements `StatefulResampler` using exact integer rational phase accumulation and
 *   anti-alias boxcar integration across arbitrary worklet quantum boundaries (e.g., 128 samples),
 *   so 375 frames of 128 samples at 48 kHz yield exactly 16,000 output samples (0 lost samples)
 *   and 44,100 samples at 44.1 kHz across 128-sample blocks yield exactly 16,000 output samples.
 */

export const TARGET_SAMPLE_RATE_HZ = 16000;

export interface WorkletTelemetryFrame {
  readonly pcm16: Int16Array;
  readonly rmsNormalized: number;
  readonly peakNormalized: number;
  readonly clippedSamples: number;
}

function gcd(a: number, b: number): number {
  let x = Math.abs(Math.round(a));
  let y = Math.abs(Math.round(b));
  while (y !== 0) {
    const t = y;
    y = x % y;
    x = t;
  }
  return x || 1;
}

/**
 * Stateful rational-phase boxcar resampler that carries fractional phase and weighted sum
 * across arbitrary AudioWorklet quantum boundaries (128 samples, 73 samples, etc.).
 */
export class StatefulResampler {
  private inputSampleRate: number;
  private readonly targetSampleRate: number;
  private inStep: number;
  private outStep: number;
  private phaseAccum = 0;
  private weightedSum = 0;
  private pendingClipped = false;

  constructor(inputSampleRate: number = 48000, targetSampleRate: number = TARGET_SAMPLE_RATE_HZ) {
    if (inputSampleRate <= 0 || targetSampleRate <= 0) {
      throw new Error(`Invalid sample rates: in=${inputSampleRate}, target=${targetSampleRate}`);
    }
    this.inputSampleRate = Math.round(inputSampleRate);
    this.targetSampleRate = Math.round(targetSampleRate);
    const divisor = gcd(this.inputSampleRate, this.targetSampleRate);
    this.inStep = this.inputSampleRate / divisor;
    this.outStep = this.targetSampleRate / divisor;
  }

  public getInputSampleRate(): number {
    return this.inputSampleRate;
  }

  public getTargetSampleRate(): number {
    return this.targetSampleRate;
  }

  public setInputSampleRate(nextInputSampleRate: number): void {
    const rounded = Math.round(nextInputSampleRate);
    if (rounded <= 0) {
      throw new Error(`Invalid inputSampleRate: ${nextInputSampleRate}`);
    }
    if (rounded !== this.inputSampleRate) {
      this.inputSampleRate = rounded;
      const divisor = gcd(this.inputSampleRate, this.targetSampleRate);
      this.inStep = this.inputSampleRate / divisor;
      this.outStep = this.targetSampleRate / divisor;
      this.reset();
    }
  }

  public reset(): void {
    this.phaseAccum = 0;
    this.weightedSum = 0;
    this.pendingClipped = false;
  }

  public processFrame(input: Float32Array): WorkletTelemetryFrame {
    if (input.length === 0) {
      return {
        pcm16: new Int16Array(0),
        rmsNormalized: 0,
        peakNormalized: 0,
        clippedSamples: 0,
      };
    }

    const expectedMaxOut = Math.ceil((input.length * this.outStep + this.phaseAccum) / this.inStep) + 2;
    const outBuffer = new Int16Array(expectedMaxOut);
    let outIndex = 0;
    let sumSq = 0;
    let peak = 0;
    let clippedSamples = 0;

    for (let i = 0; i < input.length; i++) {
      const sample = input[i];
      if (Math.abs(sample) >= 0.999) {
        this.pendingClipped = true;
      }

      let remainingWeight = this.outStep;
      while (remainingWeight > 0) {
        const needed = this.inStep - this.phaseAccum;
        if (remainingWeight < needed) {
          this.weightedSum += sample * remainingWeight;
          this.phaseAccum += remainingWeight;
          remainingWeight = 0;
        } else {
          this.weightedSum += sample * needed;
          const avg = this.weightedSum / this.inStep;
          const absVal = Math.abs(avg);
          if (absVal > peak) {
            peak = absVal;
          }
          if (absVal >= 0.999 || this.pendingClipped) {
            clippedSamples += 1;
          }
          const clamped = Math.max(-1, Math.min(1, avg));
          sumSq += clamped * clamped;
          outBuffer[outIndex++] =
            clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);

          remainingWeight -= needed;
          this.phaseAccum = 0;
          this.weightedSum = 0;
          this.pendingClipped = Math.abs(sample) >= 0.999 && remainingWeight > 0;
        }
      }
    }

    const pcm16 = outBuffer.subarray(0, outIndex).slice();
    const rmsNormalized = outIndex > 0 ? Math.min(1, Math.sqrt(sumSq / outIndex)) : 0;
    const peakNormalized = Math.min(1, peak);

    return {
      pcm16,
      rmsNormalized: Number(rmsNormalized.toFixed(6)),
      peakNormalized: Number(peakNormalized.toFixed(6)),
      clippedSamples,
    };
  }
}

/**
 * Pure deterministic downsampler and float32-to-int16 converter for single-buffer callers.
 * Uses `StatefulResampler` so whole-buffer and chunked worklet outputs match identically.
 */
export function downsampleFloat32ToInt16(
  input: Float32Array,
  inputSampleRate: number,
  targetSampleRate: number = TARGET_SAMPLE_RATE_HZ,
): WorkletTelemetryFrame {
  if (input.length === 0 || inputSampleRate <= 0 || targetSampleRate <= 0) {
    return {
      pcm16: new Int16Array(0),
      rmsNormalized: 0,
      peakNormalized: 0,
      clippedSamples: 0,
    };
  }
  const resampler = new StatefulResampler(inputSampleRate, targetSampleRate);
  return resampler.processFrame(input);
}

/**
 * Inline source string for registering `'vcc-capture-worklet'` via Blob URL in browsers.
 */
export const VCC_AUDIO_WORKLET_SOURCE = `
class VccCaptureWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._stopped = false;
    this.port.onmessage = (event) => {
      const data = event && event.data ? event.data : {};
      if (data.type === 'STOP') {
        this._stopped = true;
      }
    };
  }

  process(inputs) {
    if (this._stopped) {
      return false;
    }
    const input = inputs[0];
    if (!input || input.length === 0) {
      return true;
    }
    const channelData = input[0];
    if (!channelData || channelData.length === 0) {
      return true;
    }
    this.port.postMessage({
      type: 'AUDIO_FRAME',
      samples: channelData.slice(0),
      sampleRate: sampleRate,
    });
    return true;
  }
}
registerProcessor('vcc-capture-worklet', VccCaptureWorkletProcessor);
`;
