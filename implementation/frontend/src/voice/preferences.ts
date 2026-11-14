/** Persist device preferences only, never audio, code, transcripts or credentials. */
export interface AudioPreferences {
  readonly volume: number;
  readonly speed: number;
  readonly muted: boolean;
  readonly textOnly: boolean;
  readonly introductions: boolean;
  readonly autoSpeak: boolean;
  readonly voiceOutput: boolean;
}
export type PlaybackPreferences = Pick<AudioPreferences, 'volume' | 'speed' | 'muted' | 'textOnly'> & Partial<Pick<AudioPreferences, 'voiceOutput'>>;
export const DEFAULT_AUDIO_PREFERENCES: AudioPreferences = Object.freeze({
  volume: 1, speed: 1, muted: false, textOnly: false, introductions: false,
  autoSpeak: false, voiceOutput: true,
});
const STORAGE_KEY = 'viva.audio-preferences.v1';

function normalize(value: unknown, fallback: AudioPreferences): AudioPreferences {
  const raw = typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
  return Object.freeze({
    volume: typeof raw.volume === 'number' && Number.isFinite(raw.volume) && raw.volume >= 0 && raw.volume <= 1 ? raw.volume : fallback.volume,
    speed: typeof raw.speed === 'number' && Number.isFinite(raw.speed) && raw.speed >= .5 && raw.speed <= 2 ? raw.speed : fallback.speed,
    muted: typeof raw.muted === 'boolean' ? raw.muted : fallback.muted,
    textOnly: typeof raw.textOnly === 'boolean' ? raw.textOnly : fallback.textOnly,
    introductions: typeof raw.introductions === 'boolean' ? raw.introductions : fallback.introductions,
    autoSpeak: typeof raw.autoSpeak === 'boolean' ? raw.autoSpeak : fallback.autoSpeak,
    voiceOutput: typeof raw.voiceOutput === 'boolean' ? raw.voiceOutput : fallback.voiceOutput,
  });
}
export function updateAudioPreferences(current: AudioPreferences, patch: Partial<AudioPreferences>): AudioPreferences {
  return normalize({ ...current, ...patch }, current);
}
export function loadAudioPreferences(storage?: Pick<Storage, 'getItem'>): AudioPreferences {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    const raw = target?.getItem(STORAGE_KEY);
    return raw ? normalize(JSON.parse(raw), DEFAULT_AUDIO_PREFERENCES) : DEFAULT_AUDIO_PREFERENCES;
  } catch { return DEFAULT_AUDIO_PREFERENCES; /* Private browsing/storage denial: safe defaults. */ }
}
export function saveAudioPreferences(preferences: AudioPreferences, storage?: Pick<Storage, 'setItem'>): boolean {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    if (!target) return false;
    target.setItem(STORAGE_KEY, JSON.stringify(normalize(preferences, DEFAULT_AUDIO_PREFERENCES)));
    return true;
  } catch { return false; /* The caller can tell the user preferences were not persisted. */ }
}
export function shouldRequestVoice(preferences: PlaybackPreferences): boolean {
  return !preferences.textOnly && preferences.voiceOutput !== false && !preferences.muted && preferences.volume > 0;
}
export function shouldPlayIntroduction(preferences: AudioPreferences): boolean {
  return preferences.introductions && shouldRequestVoice(preferences);
}
