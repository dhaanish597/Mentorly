/** Conservative local activity heuristic, not speech recognition or a trained VAD.
 * Uses 20 ms windows, a changing envelope, band energy, and sustained activity.
 * Stationary fans, DC offsets, and brief spikes cannot arm auto-submit alone.
 * Browser noise suppression remains best effort; real microphone accuracy needs testing.
 */
export class SpeechActivityDetector {
  private rate = 0;
  private previousInput = 0;
  private highPass = 0;
  private lowPass = 0;
  private count = 0;
  private rawEnergy = 0;
  private bandEnergy = 0;
  private crossings = 0;
  private previousBand = 0;
  private noiseFloor = .004;
  private envelope: number[] = [];
  private candidateMs = 0;
  private detected = false;

  get hasActivity(): boolean { return this.detected; }

  reset(): void {
    this.rate = 0; this.previousInput = 0; this.highPass = 0; this.lowPass = 0;
    this.count = 0; this.rawEnergy = 0; this.bandEnergy = 0; this.crossings = 0;
    this.previousBand = 0; this.noiseFloor = .004; this.envelope = [];
    this.candidateMs = 0; this.detected = false;
  }

  push(samples: Float32Array, sampleRate: number): boolean {
    if (!Number.isFinite(sampleRate) || sampleRate < 8000) return false;
    if (this.rate && this.rate !== sampleRate) this.reset();
    this.rate = sampleRate;
    const highAlpha = Math.exp(-2 * Math.PI * 120 / sampleRate);
    const lowAlpha = 1 - Math.exp(-2 * Math.PI * 3500 / sampleRate);
    const windowSamples = Math.round(sampleRate * .02);
    let active = false;
    for (const input of samples) {
      const sample = Number.isFinite(input) ? input : 0;
      this.highPass = highAlpha * (this.highPass + sample - this.previousInput);
      this.previousInput = sample;
      this.lowPass += lowAlpha * (this.highPass - this.lowPass);
      this.rawEnergy += sample * sample;
      this.bandEnergy += this.lowPass * this.lowPass;
      if ((this.lowPass >= 0) !== (this.previousBand >= 0)) this.crossings++;
      this.previousBand = this.lowPass;
      if (++this.count < windowSamples) continue;
      const rms = Math.sqrt(this.bandEnergy / this.count);
      const ratio = this.bandEnergy / Math.max(this.rawEnergy, 1e-12);
      const crossingRate = this.crossings / this.count;
      this.envelope.push(rms);
      if (this.envelope.length > 30) this.envelope.shift();
      const mean = this.envelope.reduce((sum, value) => sum + value, 0) / this.envelope.length;
      const variation = Math.sqrt(this.envelope.reduce((sum, value) => sum + (value - mean) ** 2, 0) / this.envelope.length) / Math.max(mean, .001);
      const modulated = this.envelope.length >= 12 && variation >= .12;
      const candidate = rms >= Math.max(.008, this.noiseFloor * 1.8) && ratio >= .45 && crossingRate >= .006 && crossingRate <= .35 && modulated;
      this.candidateMs = candidate ? this.candidateMs + 20 : Math.max(0, this.candidateMs - 40);
      if (!candidate && (!modulated || rms < this.noiseFloor)) {
        this.noiseFloor += .02 * (Math.max(.001, rms) - this.noiseFloor);
      }
      if (candidate && this.candidateMs >= 240) { active = true; this.detected = true; }
      this.count = 0; this.rawEnergy = 0; this.bandEnergy = 0; this.crossings = 0;
    }
    return active;
  }
}
