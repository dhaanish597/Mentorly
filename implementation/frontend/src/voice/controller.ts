import { AudioPlayer, type PlayWavBytesParams } from '../services/audioPlayer';
import { DEFAULT_AUDIO_PREFERENCES, type AudioPreferences, shouldRequestVoice, updateAudioPreferences } from './preferences';

const MAX_REPLAY_ENTRIES = 12;
const MAX_REPLAY_BYTES = 8 * 1024 * 1024;
type CachedPlayback = { playback: PlayWavBytesParams; context: string; artifactContext?: string };
function revisionContext(params: PlayWavBytesParams): string {
  const r = params.revision;
  return JSON.stringify([params.sessionId, r?.session_id, r?.exercise_id, r?.spec_version, r?.code_version_id, r?.code_hash, r?.turn_generation ?? params.turnGeneration]);
}

/** Explicit gesture-driven playback. Private replay is bounded and never calls a provider. */
export class VoiceController {
  private currentPreferences: AudioPreferences = DEFAULT_AUDIO_PREFERENCES;
  private lastPlayback: PlayWavBytesParams | null = null;
  private messagePlayback: ReadonlyMap<string, CachedPlayback> = new Map();
  private activeAbortCleanup: (() => void) | null = null;
  private disposed = false;
  constructor(private readonly player = new AudioPlayer()) {}
  hasReplay(key: string): boolean { return !this.disposed && this.messagePlayback.has(key); }
  get preferences(): AudioPreferences { return this.currentPreferences; }
  unlockAudioFromGesture(audioContextFactory?: () => AudioContext): Promise<boolean> {
    return this.disposed ? Promise.resolve(false) : this.player.unlockAudioFromGesture(audioContextFactory);
  }
  setPreferences(preferences: AudioPreferences): void {
    this.currentPreferences = updateAudioPreferences(DEFAULT_AUDIO_PREFERENCES, preferences);
    this.player.setPreferences(this.currentPreferences);
    if (!shouldRequestVoice(this.currentPreferences)) this.bargeInStop();
  }
  private remember(params: PlayWavBytesParams, replayKey?: string, artifactContext?: string): PlayWavBytesParams | null {
    const context = JSON.stringify([revisionContext(params), artifactContext ?? null]);
    const entries = [...this.messagePlayback].filter(([, entry]) => revisionContext(entry.playback) === revisionContext(params) && (!replayKey || entry.context === context));
    if (params.wavBytes.byteLength > MAX_REPLAY_BYTES) {
      this.lastPlayback = null; this.messagePlayback = new Map(entries.filter(([key]) => key !== replayKey)); return null;
    }
    // Delivery callbacks are only used by the live invocation, never retained by replay.
    const playback = { ...params, wavBytes: params.wavBytes.slice(0), revision: params.revision ? { ...params.revision } : params.revision, onEnded: undefined, onAutoplayBlocked: undefined };
    this.lastPlayback = playback;
    let retained = entries.filter(([key]) => key !== replayKey);
    if (replayKey) retained = [...retained, [replayKey, { playback, context, artifactContext }]];
    const retainedBytes = () => retained.reduce((bytes, [, entry]) => bytes + entry.playback.wavBytes.byteLength, 0) + (retained.some(([, entry]) => entry.playback === playback) ? 0 : playback.wavBytes.byteLength);
    while (retained.length > MAX_REPLAY_ENTRIES || retainedBytes() > MAX_REPLAY_BYTES) retained = retained.slice(1);
    this.messagePlayback = new Map(retained);
    return playback;
  }
  private evictFailed(playback: PlayWavBytesParams | null): void {
    if (!playback) return;
    // Identity prevents a late rejection from evicting a newer same-key replacement.
    this.messagePlayback = new Map([...this.messagePlayback].filter(([, entry]) => entry.playback !== playback));
    if (this.lastPlayback === playback) this.lastPlayback = null;
  }
  async play(params: PlayWavBytesParams, signal?: AbortSignal, replayKey?: string, artifactContext?: string): Promise<{ started: boolean; fallbackAck: ReturnType<typeof AudioPlayer.buildReadTextFallbackAck> | null }> {
    this.bargeInStop();
    if (signal?.aborted) throw new DOMException('Playback cancelled', 'AbortError');
    if (this.disposed || !shouldRequestVoice(this.currentPreferences)) {
      return { started: false, fallbackAck: AudioPlayer.buildReadTextFallbackAck(params.sessionId, params.turnId, params.turnGeneration, params.playbackId, params.revision) };
    }
    const remembered = this.remember(params, replayKey, artifactContext);
    const abort = () => { this.bargeInStop(); };
    signal?.addEventListener('abort', abort, { once: true });
    const cleanupListener = () => { signal?.removeEventListener('abort', abort); };
    this.activeAbortCleanup = cleanupListener;
    const cleanup = () => {
      cleanupListener();
      if (this.activeAbortCleanup === cleanupListener) this.activeAbortCleanup = null;
    };
    try {
      const result = await this.player.playWavBytes({ ...params,
        onEnded: ack => { cleanup(); params.onEnded?.(ack); },
        onAutoplayBlocked: ack => { cleanup(); params.onAutoplayBlocked?.(ack); },
      });
      if (!result.started) cleanup();
      return result;
    } catch (error) { cleanup(); this.evictFailed(remembered); throw error; }
  }
  async replay(signal?: AbortSignal, replayKey?: string): Promise<{ started: boolean; fallbackAck: ReturnType<typeof AudioPlayer.buildReadTextFallbackAck> | null }> {
    const cached = replayKey === undefined ? [...this.messagePlayback].find(([, entry]) => entry.playback === this.lastPlayback) : [...this.messagePlayback].find(([key]) => key === replayKey);
    const playback = replayKey === undefined ? this.lastPlayback : cached?.[1].playback;
    if (!playback) return { started: false, fallbackAck: null };
    return this.play(playback, signal, cached?.[0], cached?.[1].artifactContext);
  }
  bargeInStop(): ReturnType<AudioPlayer['bargeInStop']> {
    this.activeAbortCleanup?.(); this.activeAbortCleanup = null;
    return this.player.bargeInStop();
  }
  clearReplay(): void {
    this.bargeInStop(); this.lastPlayback = null; this.messagePlayback = new Map();
  }
  async dispose(): Promise<void> {
    this.disposed = true;
    this.clearReplay();
    await this.player.dispose();
  }
}
