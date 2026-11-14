import type { AudioEvent, RevisionRef } from '../types/api';
import { decodeWavToPcmFloat32 } from './audioPlayer';
import { DEFAULT_AUDIO_PREFERENCES, shouldRequestVoice, updateAudioPreferences, type PlaybackPreferences } from '../voice/preferences';

/** Reframe arbitrarily sized AudioWorklet PCM quanta into 32ms provider frames. */
export class PcmFrameWriter {
  private pending = new Uint8Array(0);
  private bytesSent = 0;
  constructor(private readonly send: (frame: Uint8Array) => void) {}
  push(samples: Int16Array): void {
    if (this.bytesSent + this.pending.length + samples.byteLength > 960_000) throw new Error('Recording exceeds thirty seconds.');
    const bytes = new Uint8Array(this.pending.length + samples.byteLength);
    bytes.set(this.pending);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < samples.length; i++) view.setInt16(this.pending.length + i * 2, samples[i], true);
    let offset = 0;
    while (bytes.length - offset >= 1024) { this.send(bytes.slice(offset, offset + 1024)); this.bytesSent += 1024; offset += 1024; }
    this.pending = bytes.slice(offset);
  }
  finish(): void {
    if (this.pending.length) { const frame = new Uint8Array(1024); frame.set(this.pending); this.send(frame); this.bytesSent += 1024; this.pending = new Uint8Array(0); }
  }
}

/** Bounded SSE parsing supports event and UTF-8 boundaries split across network reads. */
export async function consumeAudioEvents(response: Response, receive: (event: AudioEvent) => Promise<void> | void, signal: AbortSignal): Promise<void> {
  if (!response.ok || !response.body) throw new Error(`Streaming voice unavailable (HTTP ${response.status}).`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let text = '', bytes = 0, events = 0, last: string | null = null, audioBytes = 0;
  async function parse(final = false): Promise<void> {
    for (;;) {
      const boundary = /\r?\n\r?\n/.exec(text);
      if (!boundary && !final) break;
      if (!boundary && !text.trim()) break;
      const block = boundary ? text.slice(0, boundary.index) : text;
      text = boundary ? text.slice(boundary.index + boundary[0].length) : '';
      const data = block.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!data) continue;
      if (++events > 2000) throw new Error('Voice stream event limit exceeded.');
      const event = JSON.parse(data) as AudioEvent;
      if (!event || !['start', 'chunk', 'complete', 'error'].includes(event.event_type)) throw new Error('Invalid voice stream event.');
      if (event.event_type === 'error') throw new Error('Voice provider stopped the stream. Read the coach text instead.');
      const audio = event.audio_b64 ?? event.wav_bytes_b64;
      if (audio) { audioBytes += audio.length * .75; if (audioBytes > 4 * 1024 * 1024) throw new Error('Voice stream audio limit exceeded.'); }
      last = event.event_type;
      await receive(event);
    }
  }
  const abort = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener('abort', abort, { once: true });
  try {
    for (;;) {
      if (signal.aborted) throw new DOMException('Playback cancelled', 'AbortError');
      const item = await reader.read();
      if (signal.aborted) throw new DOMException('Playback cancelled', 'AbortError');
      if (item.done) break;
      bytes += item.value.byteLength;
      if (bytes > 8 * 1024 * 1024) throw new Error('Voice stream size limit exceeded.');
      text += decoder.decode(item.value, { stream: true }); await parse();
    }
    text += decoder.decode(); await parse(true);
    if (last !== 'complete' || audioBytes === 0) throw new Error('Incomplete voice stream; playback is unconfirmed.');
  } finally { signal.removeEventListener('abort', abort); await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

/** Schedules PCM as it arrives. Cancellation stops every queued source locally. */
export class StreamingPcmPlayer {
  private context: AudioContext | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private pendingByte: number | null = null;
  private complete = false;
  private stopped = false;
  private eventIndex: number | null = null;
  private segment: number | null = null;
  private resolveEnd: (() => void) | null = null;
  private epoch = 0;
  private gain: GainNode | null = null;
  private preferences: PlaybackPreferences = DEFAULT_AUDIO_PREFERENCES;
  setPreferences(preferences: PlaybackPreferences): void {
    this.preferences = updateAudioPreferences(DEFAULT_AUDIO_PREFERENCES, preferences);
    if (this.gain) this.gain.gain.value = this.preferences.muted ? 0 : this.preferences.volume;
    if (!shouldRequestVoice(this.preferences)) void this.stop();
  }
  readonly revision: RevisionRef;
  constructor(revision: RevisionRef, private readonly contextFactory = () => new AudioContext()) { this.revision = revision; }
  async append(event: AudioEvent): Promise<void> {
    if (this.stopped) throw new DOMException('Playback cancelled', 'AbortError');
    if (!event.audio_b64 && !event.wav_bytes_b64) return;
    if (!shouldRequestVoice(this.preferences)) throw new DOMException('Playback disabled', 'AbortError');
    const epoch = this.epoch;
    if ((event.segment_index ?? 0) !== this.segment) { this.segment = event.segment_index ?? 0; this.eventIndex = null; }
    const index = event.chunk_index;
    if (index !== null && index !== undefined) {
      if (!Number.isInteger(index) || (this.eventIndex === null ? ![0,1].includes(index) : index !== this.eventIndex + 1)) throw new Error('Voice stream chunk order is invalid.');
      this.eventIndex = index;
    }
    let rate = event.sample_rate ?? 22050;
    if (!Number.isInteger(rate) || rate < 8000 || rate > 48000) throw new Error('Unsupported streaming sample rate.');
    const binary = atob(event.audio_b64 ?? event.wav_bytes_b64!);
    if (binary.length > 1024 * 1024) throw new Error('Voice chunk limit exceeded.');
    const bytes = new Uint8Array(binary.length + (this.pendingByte === null ? 0 : 1));
    let offset = 0;
    if (this.pendingByte !== null) bytes[offset++] = this.pendingByte;
    for (let i = 0; i < binary.length; i++) bytes[offset + i] = binary.charCodeAt(i);
    const cached = event.wav_bytes_b64 ? decodeWavToPcmFloat32(bytes) : null;
    if (cached) rate = cached.sampleRateHz;
    this.pendingByte = cached ? null : (bytes.length % 2 ? bytes[bytes.length - 1] : null);
    const frames = cached ? cached.samples.length : Math.floor(bytes.length / 2);
    if (!frames) return;
    const ctx = this.context ?? (this.context = this.contextFactory());
    if (ctx.state === 'suspended') await ctx.resume();
    if (this.stopped || epoch !== this.epoch) throw new DOMException('Playback cancelled', 'AbortError');
    if (ctx.state !== 'running') throw new Error('Autoplay blocked; use the coach text.');
    const buffer = ctx.createBuffer(1, frames, rate), channel = buffer.getChannelData(0), view = new DataView(bytes.buffer);
    for (let i = 0; i < frames; i++) channel[i] = cached ? cached.samples[i] : view.getInt16(i * 2, true) / 32768;
    if (!this.gain && typeof ctx.createGain === 'function') { this.gain = ctx.createGain(); this.gain.connect(ctx.destination); }
    if (this.gain) this.gain.gain.value = this.preferences.volume;
    const source = ctx.createBufferSource(); source.buffer = buffer;
    if (source.playbackRate) source.playbackRate.value = this.preferences.speed;
    source.connect(this.gain ?? ctx.destination);
    this.sources.add(source);
    source.onended = () => { source.disconnect(); this.sources.delete(source); if (this.complete && !this.sources.size) this.resolveEnd?.(); };
    const when = Math.max(ctx.currentTime + .03, this.nextTime); this.nextTime = when + buffer.duration / this.preferences.speed;
    source.start(when);
  }
  async finish(): Promise<void> {
    if (this.pendingByte !== null) throw new Error('Truncated PCM stream; playback is unconfirmed.');
    this.complete = true;
    if (this.sources.size) await new Promise<void>(resolve => { this.resolveEnd = resolve; });
    if (this.stopped) throw new DOMException('Playback cancelled', 'AbortError');
  }
  async stop(): Promise<void> {
    this.stopped = true; this.epoch++;
    for (const source of this.sources) { source.onended = null; try { source.stop(); } catch { /* Already ended. */ } source.disconnect(); }
    this.sources.clear(); this.resolveEnd?.();
    const ctx = this.context; this.context = null;
    this.gain?.disconnect(); this.gain = null;
    if (ctx && ctx.state !== 'closed') await ctx.close();
  }
}
