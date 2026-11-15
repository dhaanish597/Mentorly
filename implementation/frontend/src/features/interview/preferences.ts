import type { Difficulty, InterviewConfig, InterviewType } from './types';
import { CODE_MIXING_LANGUAGES, SPEECH_LANGUAGES, resolveLanguageMode } from '../../voice/languages';

/** Device-local defaults only: no topics, language, consent, media or credentials. */
export interface InterviewPreferences {
  readonly type: InterviewType;
  readonly difficulty: Difficulty;
  readonly duration_minutes: number;
}

/** Locally shipped bounds, not server availability. Setup validates using server config. */
export const INTERVIEW_PREFERENCE_CONFIG: InterviewConfig = Object.freeze({
  types: ['dsa', 'cs', 'system_design', 'codebase_defense'] as InterviewType[],
  difficulties: ['beginner', 'intermediate', 'advanced'] as Difficulty[],
  duration_minutes: Object.freeze({ minimum: 5, maximum: 60, default: 15 }),
  language_modes: [...SPEECH_LANGUAGES.map(item => item.code), ...CODE_MIXING_LANGUAGES.map(code => resolveLanguageMode(code, true))],
  camera_default: false,
});
const STORAGE_KEY = 'viva.interview-preferences.v1';

export function getDefaultInterviewPreferences(config: InterviewConfig): InterviewPreferences {
  return Object.freeze({
    type: config.types.includes('dsa') ? 'dsa' : config.types[0] ?? 'dsa',
    difficulty: config.difficulties.includes('beginner') ? 'beginner' : config.difficulties[0] ?? 'beginner',
    duration_minutes: config.duration_minutes.default,
  });
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function validDuration(value: unknown, config: InterviewConfig): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value)
    && value >= config.duration_minutes.minimum && value <= config.duration_minutes.maximum;
}
function normalize(value: unknown, config: InterviewConfig): InterviewPreferences {
  const raw = isRecord(value) ? value : {};
  const fallback = getDefaultInterviewPreferences(config);
  return Object.freeze({
    type: config.types.find(type => type === raw.type) ?? fallback.type,
    difficulty: config.difficulties.find(difficulty => difficulty === raw.difficulty) ?? fallback.difficulty,
    duration_minutes: validDuration(raw.duration_minutes, config) ? raw.duration_minutes : fallback.duration_minutes,
  });
}
function parse(raw: string | null | undefined, config: InterviewConfig): InterviewPreferences {
  try { return normalize(raw ? JSON.parse(raw) : undefined, config); }
  catch { return getDefaultInterviewPreferences(config); /* Corrupt data never prevents a new interview. */ }
}
export function loadInterviewPreferences(config: InterviewConfig, storage?: Pick<Storage, 'getItem'>): InterviewPreferences {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    return parse(target?.getItem(STORAGE_KEY), config);
  } catch { return getDefaultInterviewPreferences(config); /* Denied storage: callers can still use safe defaults. */ }
}
export function saveInterviewPreferences(value: InterviewPreferences, config: InterviewConfig, storage?: Pick<Storage, 'setItem'>): boolean {
  if (!isRecord(value) || !config.types.some(type => type === value.type)
    || !config.difficulties.some(difficulty => difficulty === value.difficulty)
    || !validDuration(value.duration_minutes, config)) return false;
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    if (!target) return false;
    const preferences = normalize(value, config);
    target.setItem(STORAGE_KEY, JSON.stringify(preferences));
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(STORAGE_KEY, { detail: preferences }));
    return true;
  } catch { return false; /* The editor must show a visible save failure. */ }
}
export function resetInterviewPreferences(storage?: Pick<Storage, 'removeItem'>): boolean {
  try {
    const target = storage ?? (typeof window === 'undefined' ? undefined : window.localStorage);
    if (!target) return false;
    target.removeItem(STORAGE_KEY);
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(STORAGE_KEY));
    return true;
  } catch { return false; /* Do not announce a reset that was not persisted. */ }
}
export function subscribeInterviewPreferences(config: InterviewConfig, receive: (value: InterviewPreferences) => void): () => void {
  receive(loadInterviewPreferences(config));
  if (typeof window === 'undefined') return () => undefined;
  const local = (event: Event): void => receive(normalize((event as CustomEvent<unknown>).detail, config));
  const crossTab = (event: StorageEvent): void => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    try { if (event.storageArea && event.storageArea !== window.localStorage) return; }
    catch { receive(getDefaultInterviewPreferences(config)); return; }
    receive(parse(event.newValue, config));
  };
  window.addEventListener(STORAGE_KEY, local);
  window.addEventListener('storage', crossTab);
  return () => { window.removeEventListener(STORAGE_KEY, local); window.removeEventListener('storage', crossTab); };
}
