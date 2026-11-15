import { describe, expect, it } from 'vitest';
import { SpeechActivityDetector } from '../services/speechActivity';

import { voiceLike } from './fixtures/syntheticActivity';

function process(detector: SpeechActivityDetector, samples: Float32Array, rate = 48000): number {
  let active = 0;
  for (let i = 0; i < samples.length; i += 128) if (detector.push(samples.subarray(i, i + 128), rate)) active++;
  return active;
}
describe('conservative speech-like activity heuristic', () => {
  it.each([16000, 44100, 48000])('accepts sustained modulated speech-band activity at %s Hz', rate => {
    const detector = new SpeechActivityDetector();
    expect(process(detector, voiceLike(rate), rate)).toBeGreaterThan(0);
    expect(detector.hasActivity).toBe(true);
  });
  it.each(['DC', 'fan', 'high-frequency', 'spike'] as const)('rejects synthetic %s without claiming speech recognition', kind => {
    const detector = new SpeechActivityDetector();
    const samples = Float32Array.from({ length: 48000 * 3 }, (_, i) => kind === 'DC' ? .2 : kind === 'fan' ? .12 * Math.sin(2 * Math.PI * 95 * i / 48000) : kind === 'high-frequency' ? .2 * Math.sin(2 * Math.PI * 10000 * i / 48000) : i === 1000 ? 1 : 0);
    expect(process(detector, samples)).toBe(0); expect(detector.hasActivity).toBe(false);
  });
  it('rejects short voice-band bursts and rearms only after sustained activity', () => {
    const detector = new SpeechActivityDetector();
    expect(process(detector, voiceLike(48000, .1))).toBe(0);
    detector.reset(); expect(detector.hasActivity).toBe(false);
    expect(process(detector, voiceLike())).toBeGreaterThan(0);
  });
  it('accepts modulated activity above an estimated stationary fan floor', () => {
    const detector = new SpeechActivityDetector();
    const fan = Float32Array.from({ length: 48000 * 2 }, (_, i) => .015 * Math.sin(2 * Math.PI * 150 * i / 48000));
    expect(process(detector, fan)).toBe(0);
    const mixed = voiceLike(); for (let i = 0; i < mixed.length; i++) mixed[i] += .015 * Math.sin(2 * Math.PI * 150 * i / 48000);
    expect(process(detector, mixed)).toBeGreaterThan(0);
  });
  it('rejects invalid rates and nonfinite samples without arming activity', () => {
    const detector = new SpeechActivityDetector();
    expect(detector.push(new Float32Array([NaN, Infinity]), NaN)).toBe(false);
    expect(process(detector, new Float32Array(48000).fill(NaN))).toBe(0);
    expect(detector.hasActivity).toBe(false);
  });
});
