import { CODE_MIXING_LANGUAGES, isSpeechLocale, isTTSVoice, type SpeechLocale, type TTSVoice } from './languages';

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
    const normalized = normalize(preferences, DEFAULT_AUDIO_PREFERENCES);
    target.setItem(STORAGE_KEY, JSON.stringify(normalized));
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(STORAGE_KEY, {detail:normalized}));
    return true;
  } catch { return false; /* The caller can tell the user preferences were not persisted. */ }
}
export function shouldRequestVoice(preferences: PlaybackPreferences): boolean {
  return !preferences.textOnly && preferences.voiceOutput !== false && !preferences.muted && preferences.volume > 0;
}
export function shouldPlayIntroduction(preferences: AudioPreferences): boolean {
  return preferences.introductions && shouldRequestVoice(preferences);
}

export interface SpeechPreferences {
  readonly interfaceLanguage: SpeechLocale;
  readonly sttLanguage: SpeechLocale;
  readonly spokenLanguage: SpeechLocale;
  readonly codeMixing: boolean;
  readonly voice: TTSVoice;
}
export const DEFAULT_SPEECH_PREFERENCES: SpeechPreferences = Object.freeze({
  interfaceLanguage:'en-IN', sttLanguage:'en-IN', spokenLanguage:'en-IN', codeMixing:false, voice:'Avinash',
});
const SPEECH_STORAGE_KEY = 'viva.speech-preferences.v1';
function normalizeSpeech(value: unknown, fallback: SpeechPreferences): SpeechPreferences {
  const raw = typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
  const sttLanguage = isSpeechLocale(raw.sttLanguage) ? raw.sttLanguage : fallback.sttLanguage;
  return Object.freeze({
    interfaceLanguage:isSpeechLocale(raw.interfaceLanguage) ? raw.interfaceLanguage : fallback.interfaceLanguage,
    sttLanguage, spokenLanguage:isSpeechLocale(raw.spokenLanguage) ? raw.spokenLanguage : fallback.spokenLanguage,
    voice:isTTSVoice(raw.voice) ? raw.voice : fallback.voice,
    codeMixing:CODE_MIXING_LANGUAGES.includes(sttLanguage) && (typeof raw.codeMixing === 'boolean' ? raw.codeMixing : fallback.codeMixing),
  });
}
export function updateSpeechPreferences(current: SpeechPreferences, patch: Partial<SpeechPreferences>): SpeechPreferences {
  return normalizeSpeech({...current,...patch},current);
}
export function loadSpeechPreferences(storage?: Pick<Storage,'getItem'>): SpeechPreferences {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    const raw = target?.getItem(SPEECH_STORAGE_KEY);
    return raw ? normalizeSpeech(JSON.parse(raw),DEFAULT_SPEECH_PREFERENCES) : DEFAULT_SPEECH_PREFERENCES;
  } catch { return DEFAULT_SPEECH_PREFERENCES; }
}
export function saveSpeechPreferences(preferences: SpeechPreferences, storage?: Pick<Storage,'setItem'>): boolean {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    if (!target) return false;
    const normalized = normalizeSpeech(preferences,DEFAULT_SPEECH_PREFERENCES);
    target.setItem(SPEECH_STORAGE_KEY,JSON.stringify(normalized));
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(SPEECH_STORAGE_KEY,{detail:normalized}));
    return true;
  } catch { return false; }
}
function subscribePreferences<T>(key: string, load: () => T, normalizeValue: (raw: unknown) => T, receive: (preferences: T) => void): () => void {
  receive(load());
  if (typeof window === 'undefined') return () => undefined;
  const local = (event: Event) => receive(normalizeValue((event as CustomEvent<unknown>).detail));
  const crossTab = (event: StorageEvent) => {
    if (event.key !== key && event.key !== null) return;
    if (event.storageArea && event.storageArea !== window.localStorage) return;
    let value: unknown;
    try { value = event.newValue ? JSON.parse(event.newValue) : undefined; } catch { value = undefined; }
    receive(normalizeValue(value));
  };
  window.addEventListener(key,local);
  window.addEventListener('storage',crossTab);
  return () => { window.removeEventListener(key,local); window.removeEventListener('storage',crossTab); };
}
export function subscribeSpeechPreferences(receive: (preferences: SpeechPreferences) => void): () => void {
  return subscribePreferences(SPEECH_STORAGE_KEY,loadSpeechPreferences,value=>normalizeSpeech(value,DEFAULT_SPEECH_PREFERENCES),receive);
}
export function subscribeAudioPreferences(receive: (preferences: AudioPreferences) => void): () => void {
  return subscribePreferences(STORAGE_KEY,loadAudioPreferences,value=>normalize(value,DEFAULT_AUDIO_PREFERENCES),receive);
}
