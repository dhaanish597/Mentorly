import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  INTERVIEW_PREFERENCE_CONFIG as config, getDefaultInterviewPreferences,
  loadInterviewPreferences, saveInterviewPreferences, resetInterviewPreferences,
  subscribeInterviewPreferences, type InterviewPreferences,
} from '../features/interview/preferences';
import { parseConfig } from '../features/interview/validation';
import { CODE_MIXING_LANGUAGES, SPEECH_LANGUAGES, resolveLanguageMode } from '../voice/languages';
import type { InterviewConfig } from '../features/interview/types';

const key = 'viva.interview-preferences.v1';
const defaults = { type: 'dsa', difficulty: 'beginner', duration_minutes: 15 };
const selected: InterviewPreferences = { type: 'system_design', difficulty: 'advanced', duration_minutes: 30 };
const listeners: (() => void)[] = [];
afterEach(() => { listeners.splice(0).forEach(cleanup => cleanup()); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });
function read(value: unknown, supported = config): InterviewPreferences {
  return loadInterviewPreferences(supported, { getItem: () => JSON.stringify(value) });
}

describe('device-local interview preferences', () => {
  it('ships the fixed parseConfig and backend contract, using canonical shared language modes', () => {
    expect(parseConfig(config)).toBe(config);
    expect(config.types).toEqual(['dsa', 'cs', 'system_design', 'codebase_defense']);
    expect(config.difficulties).toEqual(['beginner', 'intermediate', 'advanced']);
    expect(config.duration_minutes).toEqual({ minimum: 5, maximum: 60, default: 15 });
    expect(config.camera_default).toBe(false);
    expect(config.language_modes).toEqual([...SPEECH_LANGUAGES.map(item => item.code), ...CODE_MIXING_LANGUAGES.map(code => resolveLanguageMode(code, true))]);
    const schema = readFileSync(resolve(process.cwd(), '../backend/app/interviews/schemas.py'), 'utf8');
    const catalog = readFileSync(resolve(process.cwd(), '../backend/app/interviews/catalog.py'), 'utf8');
    expect(catalog).toContain('"duration_minutes": {"minimum": 5, "maximum": 60, "default": 15}');
    expect(catalog).toContain('"camera_default": False');
    expect(schema).toContain('InterviewType = Literal["dsa", "cs", "system_design", "codebase_defense"]');
    expect(schema).toContain('Difficulty = Literal["beginner", "intermediate", "advanced"]');
    expect(schema).toContain('duration_minutes: int = Field(ge=5, le=60, strict=True)');
  });
  it('returns defaults for missing storage and immutable new preference values', () => {
    expect(getDefaultInterviewPreferences(config)).toEqual(defaults);
    expect(loadInterviewPreferences(config)).toEqual(defaults);
    expect(Object.isFrozen(loadInterviewPreferences(config))).toBe(true);
  });
  it('chooses supported defaults when the server removes the normal default choices', () => {
    const restricted: InterviewConfig = { ...config, types: ['cs'], difficulties: ['advanced'], duration_minutes: { minimum: 20, maximum: 40, default: 25 } };
    expect(getDefaultInterviewPreferences(restricted)).toEqual({ type: 'cs', difficulty: 'advanced', duration_minutes: 25 });
    expect(read({ ...selected, type: 'dsa', difficulty: 'beginner', duration_minutes: 15 }, restricted)).toEqual({ type: 'cs', difficulty: 'advanced', duration_minutes: 25 });
    expect(read(selected, restricted)).toEqual({ type: 'cs', difficulty: 'advanced', duration_minutes: 30 });
  });
  it.each([null, undefined, [], '', 'বাংলা 😀', 123, true])('falls back for non-object data %j', value => {
    expect(read(value)).toEqual(defaults);
  });
  it.each(['', '{', 'undefined'])('falls back for corrupt or empty JSON %j', raw => {
    expect(loadInterviewPreferences(config, { getItem: () => raw })).toEqual(defaults);
  });
  it('validates fields independently and never restores sensitive or unrelated fields', () => {
    expect(read({ ...selected, type: 'invalid', topics: ['capacity'], language_mode: 'hi-IN', consent: true, camera: true, token: 'not-retained', transcript: 'not-retained' }))
      .toEqual({ ...selected, type: 'dsa' });
    expect(read({ ...selected, difficulty: null, duration_minutes: '30' })).toEqual({ ...selected, difficulty: 'beginner', duration_minutes: 15 });
    expect(read({ type: 'cs' })).toEqual({ ...defaults, type: 'cs' });
  });
  it.each([4, 61, 5.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER, null, '30', true])('falls back for invalid duration %j', duration_minutes => {
    expect(read({ ...selected, duration_minutes })).toEqual({ ...selected, duration_minutes: 15 });
  });
  it.each([5, 60])('accepts and persists integer boundary %i without mutating input or config', duration_minutes => {
    const value = Object.freeze({ ...selected, duration_minutes, topics: ['capacity'], language_mode: 'hi-IN', camera: true, consent: true });
    expect(saveInterviewPreferences(value, config)).toBe(true);
    expect(JSON.parse(localStorage.getItem(key)!)).toEqual({ ...selected, duration_minutes });
    expect(loadInterviewPreferences(config)).toEqual({ ...selected, duration_minutes });
    expect(value.topics).toEqual(['capacity']);
    expect(config.duration_minutes).toEqual({ minimum: 5, maximum: 60, default: 15 });
  });
  it.each([null, undefined, [], '', 1, {}, { ...selected, type: 'dsa;--😀' }, { ...selected, difficulty: 3 }, { ...selected, duration_minutes: 0 }, { ...selected, duration_minutes: 30.5 }, { ...selected, duration_minutes: '30' }, { ...selected, duration_minutes: Infinity }])('rejects invalid saves without writes or notifications %j', value => {
    const setItem = vi.fn(); const receive = vi.fn();
    listeners.push(subscribeInterviewPreferences(config, receive)); receive.mockClear();
    expect(saveInterviewPreferences(value as InterviewPreferences, config, { setItem })).toBe(false);
    expect(setItem).not.toHaveBeenCalled(); expect(receive).not.toHaveBeenCalled();
  });
  it('rejects server-removed choices on save instead of silently coercing them', () => {
    const setItem = vi.fn();
    expect(saveInterviewPreferences(selected, { ...config, types: ['cs'] }, { setItem })).toBe(false);
    expect(setItem).not.toHaveBeenCalled();
  });
  it('reads safely and reports failed writes/removals when storage is denied', () => {
    const denied = () => { throw new DOMException('Denied', 'SecurityError'); };
    expect(loadInterviewPreferences(config, { getItem: denied })).toEqual(defaults);
    const receive = vi.fn(); listeners.push(subscribeInterviewPreferences(config, receive)); receive.mockClear();
    expect(saveInterviewPreferences(selected, config, { setItem: denied })).toBe(false);
    expect(resetInterviewPreferences({ removeItem: denied })).toBe(false);
    expect(receive).not.toHaveBeenCalled();
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(denied);
    expect(loadInterviewPreferences(config)).toEqual(defaults);
    expect(saveInterviewPreferences(selected, config)).toBe(false);
    expect(resetInterviewPreferences()).toBe(false);
  });
  it('works without window, with optional injected storage', () => {
    vi.stubGlobal('window', undefined);
    expect(loadInterviewPreferences(config)).toEqual(defaults);
    expect(saveInterviewPreferences(selected, config)).toBe(false);
    expect(resetInterviewPreferences()).toBe(false);
    const setItem = vi.fn(), removeItem = vi.fn(), receive = vi.fn();
    expect(saveInterviewPreferences(selected, config, { setItem })).toBe(true);
    expect(resetInterviewPreferences({ removeItem })).toBe(true);
    expect(setItem).toHaveBeenCalledWith(key, JSON.stringify(selected));
    expect(removeItem).toHaveBeenCalledWith(key);
    subscribeInterviewPreferences(config, receive)();
    expect(receive).toHaveBeenCalledWith(defaults);
  });
  it('notifies all same-tab subscribers after successful save/reset and removes only this key', () => {
    const first = vi.fn(), second = vi.fn();
    listeners.push(subscribeInterviewPreferences(config, first), subscribeInterviewPreferences(config, second));
    expect(first).toHaveBeenLastCalledWith(defaults);
    expect(saveInterviewPreferences(selected, config)).toBe(true);
    expect(first).toHaveBeenLastCalledWith(selected); expect(second).toHaveBeenLastCalledWith(selected);
    localStorage.setItem('viva.speech-preferences.v1', 'unchanged');
    expect(resetInterviewPreferences()).toBe(true);
    expect(localStorage.getItem(key)).toBeNull();
    expect(localStorage.getItem('viva.speech-preferences.v1')).toBe('unchanged');
    expect(first).toHaveBeenLastCalledWith(defaults); expect(second).toHaveBeenLastCalledWith(defaults);
  });
  it('validates same-tab event payloads against each subscriber config', () => {
    const receive = vi.fn(); listeners.push(subscribeInterviewPreferences({ ...config, types: ['cs'] }, receive));
    saveInterviewPreferences(selected, config, { setItem: vi.fn() });
    expect(receive).toHaveBeenLastCalledWith({ ...selected, type: 'cs' });
    window.dispatchEvent(new CustomEvent(key, { detail: { ...selected, difficulty: 'wrong' } }));
    expect(receive).toHaveBeenLastCalledWith({ type: 'cs', difficulty: 'beginner', duration_minutes: 30 });
  });
  it('handles cross-tab save, removal, clear, corrupt JSON and ignores unrelated storage', () => {
    const receive = vi.fn(); listeners.push(subscribeInterviewPreferences(config, receive)); receive.mockClear();
    window.dispatchEvent(new StorageEvent('storage', { key: 'other', newValue: JSON.stringify(selected) }));
    window.dispatchEvent(new StorageEvent('storage', { key, storageArea: sessionStorage, newValue: JSON.stringify(selected) }));
    expect(receive).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent('storage', { key, storageArea: localStorage, newValue: JSON.stringify(selected) }));
    expect(receive).toHaveBeenLastCalledWith(selected);
    for (const event of [{ key, newValue: null }, { key: null }, { key, newValue: '{' }, { key, newValue: '[]' }]) {
      window.dispatchEvent(new StorageEvent('storage', event));
      expect(receive).toHaveBeenLastCalledWith(defaults);
    }
  });
  it('keeps storage events safe when localStorage becomes inaccessible', () => {
    const receive = vi.fn(); listeners.push(subscribeInterviewPreferences(config, receive));
    const storageArea = localStorage;
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('Denied'); });
    expect(() => window.dispatchEvent(new StorageEvent('storage', { key, storageArea, newValue: JSON.stringify(selected) }))).not.toThrow();
  });
  it('cleans up idempotently and supports repeated concurrent subscriber lifecycle changes', () => {
    const receive = vi.fn(); const stop = subscribeInterviewPreferences(config, receive);
    stop(); stop(); receive.mockClear();
    saveInterviewPreferences(selected, config);
    resetInterviewPreferences();
    window.dispatchEvent(new StorageEvent('storage', { key, newValue: JSON.stringify(selected) }));
    expect(receive).not.toHaveBeenCalled();
    const active = vi.fn(), stopped = vi.fn();
    listeners.push(subscribeInterviewPreferences(config, active));
    const stopOther = subscribeInterviewPreferences(config, stopped); stopOther(); stopped.mockClear();
    saveInterviewPreferences(selected, config); resetInterviewPreferences();
    expect(active).toHaveBeenLastCalledWith(defaults); expect(stopped).not.toHaveBeenCalled();
  });
  it('ignores 10,000 unrelated fields and Unicode/SQL-like text without retaining them', () => {
    const extras = Object.fromEntries(Array.from({ length: 10_000 }, (_, index) => [`field${index}`, "বাংলা 😀 '; DROP TABLE --"]));
    expect(read({ ...extras, ...selected })).toEqual(selected);
    expect(saveInterviewPreferences({ ...extras, ...selected }, config)).toBe(true);
    expect(JSON.parse(localStorage.getItem(key)!)).toEqual(selected);
  });
});
