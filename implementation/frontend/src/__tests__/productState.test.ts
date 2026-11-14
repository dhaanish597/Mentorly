import { afterEach, describe, expect, it } from 'vitest';
import { loadProductState, saveProductState, draftKey, readRoute, problemUrl, filterExercises } from '../state/productState';
import type { ExerciseMetadata } from '../types/api';

afterEach(() => localStorage.clear());
describe('Local practice state', () => {
  it('keeps drafts separated by problem and specification without claiming completion', () => {
    const initial = loadProductState();
    const key = draftKey('problem-1', 'positive');
    const state = { ...initial, bookmarks: ['problem-1'], drafts: { [key]: { sourceCode: 'unsaved repair', transcript: 'my reasoning', updatedAt: 100, status: 'Draft' as const } } };
    expect(saveProductState(state)).toBeNull();
    expect(loadProductState().drafts[key].sourceCode).toBe('unsaved repair');
    expect(loadProductState().drafts[draftKey('problem-1', 'negative')]).toBeUndefined();
    expect(loadProductState().bookmarks).toEqual(['problem-1']);
    expect(JSON.stringify(loadProductState())).not.toMatch(/sessionToken|completed|mastery/i);
  });
  it('recovers corrupted storage and validates settings and imported draft values', () => {
    localStorage.setItem('vcc-product-v1', '{invalid');
    expect(loadProductState().theme).toBe('system');
    localStorage.setItem('vcc-product-v1', JSON.stringify({ theme: 'evil', statementWidth: 9999, drafts: { bad: { sourceCode: 22 } }, bookmarks: [1, 'valid'] }));
    expect(loadProductState().statementWidth).toBe(300);
    expect(loadProductState().drafts).toEqual({});
    expect(loadProductState().bookmarks).toEqual(['valid']);
    expect(saveProductState(loadProductState(), { setItem: () => { throw new Error('Quota exceeded'); } })).toMatch(/Local storage is unavailable/);
    expect(loadProductState({ getItem: () => { throw new Error('Blocked'); } }).inputChoice).toBeNull();
  });
  it('round trips stable escaped problem routes and URL library filters', () => {
    const route = readRoute(new URL(problemUrl('two sum', 'v1'), 'https://example.test'));
    expect(route.problemId).toBe('two sum');
    expect(route.specVersion).toBe('v1');
    expect(readRoute(new URL('https://example.test/library?q=window&difficulty=intermediate&sort=title')).query).toBe('window');
    expect(readRoute(new URL('https://example.test/practice/%ZZ')).problemId).toBeNull();
    expect(readRoute(new URL('https://example.test/library?progress=undefined')).progress).toBe('all');
  });
  it('filters the real catalog by topic, difficulty, bookmark and query with stable ordering', () => {
    const exercise = (id: string, title: string, difficulty: ExerciseMetadata['difficulty']): ExerciseMetadata => ({ exercise_id: id, title, difficulty, comparator: 'strict_structural', catalog_status: 'READY', core_concepts: ['window'], description: 'Arrays', function_name: 'solve', starter_code: '', default_spec_version: 'v1', spec_versions: [] });
    const exercises = [exercise('b', 'Zulu', 'intermediate'), exercise('a', 'Alpha', 'beginner')];
    const route = readRoute(new URL('https://example.test/library?topic=window&sort=title'));
    expect(filterExercises(exercises, route, []).map(e => e.title)).toEqual(['Alpha', 'Zulu']);
    expect(filterExercises(exercises, { ...route, bookmarked: true }, ['b']).map(e => e.exercise_id)).toEqual(['b']);
    expect(filterExercises(exercises, { ...route, query: 'missing' }, [])).toEqual([]);
    const drafts = { [draftKey('b', 'v1')]: { sourceCode: 'draft', transcript: '', updatedAt: 1, status: 'Draft' as const } };
    expect(filterExercises(exercises, { ...route, progress: 'draft' }, [], drafts).map(e => e.exercise_id)).toEqual(['b']);
    expect(filterExercises(exercises, { ...route, progress: 'not_started' }, [], drafts).map(e => e.exercise_id)).toEqual(['a']);
  });
});
