import type { ExerciseMetadata } from '../types/api';

export type ThemePreference = 'light' | 'dark' | 'system';
export interface PracticeDraft {
  readonly sourceCode: string;
  readonly transcript: string;
  readonly updatedAt: number;
  readonly status: 'Draft' | 'In progress';
}
export interface ProductState {
  readonly theme: ThemePreference;
  readonly inputChoice: 'text' | 'voice' | null;
  readonly alwaysVoiceOn?: boolean;
  readonly language: 'en-IN' | 'ta-IN,en-IN';
  readonly statementWidth: number;
  readonly coachWidth: number;
  readonly resultsHeight: number;
  readonly coachCollapsed: boolean;
  readonly bookmarks: string[];
  readonly drafts: Record<string, PracticeDraft>;
}
export interface ProductRoute {
  readonly problemId: string | null;
  readonly specVersion: string | null;
  readonly query: string;
  readonly difficulty: string;
  readonly topic: string;
  readonly sort: 'recommended' | 'title' | 'difficulty';
  readonly bookmarked: boolean;
  readonly progress: 'all' | 'not_started' | 'draft' | 'in_progress';
}
export const DEFAULT_PRODUCT_STATE: ProductState = {
  theme: 'system', inputChoice: null, alwaysVoiceOn: false, language: 'en-IN', statementWidth: 300, coachWidth: 360, resultsHeight: 190,
  coachCollapsed: false, bookmarks: [], drafts: {},
};
const STORAGE_KEY = 'vcc-product-v1';
const MAX_DRAFT_LENGTH = 100_000;
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function bounded(value: unknown, min: number, max: number, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max ? value : fallback;
}
export function draftKey(problem: string, spec: string): string {
  return `${encodeURIComponent(problem)}::${encodeURIComponent(spec)}`;
}
export function loadProductState(storage: Pick<Storage, 'getItem'> = localStorage): ProductState {
  try {
    const raw: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? 'null');
    if (!record(raw)) return DEFAULT_PRODUCT_STATE;
    const drafts = record(raw.drafts) ? Object.fromEntries(Object.entries(raw.drafts).filter(([key, value]) =>
      key !== '__proto__' && record(value) && typeof value.sourceCode === 'string' && value.sourceCode.length <= MAX_DRAFT_LENGTH
      && typeof value.transcript === 'string' && value.transcript.length <= MAX_DRAFT_LENGTH && typeof value.updatedAt === 'number'
      && (value.status === 'Draft' || value.status === 'In progress')).map(([key, value]) => {
      const draft = value as PracticeDraft;
      return [key, { sourceCode: draft.sourceCode, transcript: draft.transcript, updatedAt: draft.updatedAt, status: draft.status }];
    })) : {};
    return {
      theme: raw.theme === 'light' || raw.theme === 'dark' ? raw.theme : 'system',
      inputChoice: raw.inputChoice === 'text' || raw.inputChoice === 'voice' ? raw.inputChoice : null,
      alwaysVoiceOn: raw.alwaysVoiceOn === true,
      language: raw.language === 'ta-IN,en-IN' ? raw.language : 'en-IN',
      statementWidth: bounded(raw.statementWidth, 240, 480, 300), coachWidth: bounded(raw.coachWidth, 300, 520, 360),
      resultsHeight: bounded(raw.resultsHeight, 120, 400, 190), coachCollapsed: raw.coachCollapsed === true,
      bookmarks: Array.isArray(raw.bookmarks) ? raw.bookmarks.filter((id): id is string => typeof id === 'string') : [], drafts,
    };
  } catch { return DEFAULT_PRODUCT_STATE; }
}
export function saveProductState(state: ProductState, storage: Pick<Storage, 'setItem'> = localStorage): string | null {
  try { storage.setItem(STORAGE_KEY, JSON.stringify(state)); return null; }
  catch { return 'Local storage is unavailable. Keep this tab open or copy your draft before leaving.'; }
}
export function problemUrl(problem: string, spec: string): string {
  return `/practice/${encodeURIComponent(problem)}?spec=${encodeURIComponent(spec)}`;
}
export function readRoute(url: URL = new URL(location.href)): ProductRoute {
  let problemId: string | null = null;
  if (url.pathname.startsWith('/practice/')) {
    try { problemId = decodeURIComponent(url.pathname.slice('/practice/'.length)) || null; } catch { problemId = null; }
  }
  return {
    problemId, specVersion: url.searchParams.get('spec'), query: url.searchParams.get('q') ?? '',
    difficulty: url.searchParams.get('difficulty') ?? '', topic: url.searchParams.get('topic') ?? '',
    sort: url.searchParams.get('sort') === 'title' ? 'title' : url.searchParams.get('sort') === 'difficulty' ? 'difficulty' : 'recommended',
    bookmarked: url.searchParams.get('saved') === '1',
    progress: url.searchParams.get('progress') === 'draft' ? 'draft' : url.searchParams.get('progress') === 'in_progress' ? 'in_progress' : url.searchParams.get('progress') === 'not_started' ? 'not_started' : 'all',
  };
}
export function libraryUrl(route: ProductRoute): string {
  const params = new URLSearchParams();
  if (route.query) params.set('q', route.query);
  if (route.difficulty) params.set('difficulty', route.difficulty);
  if (route.topic) params.set('topic', route.topic);
  if (route.sort !== 'recommended') params.set('sort', route.sort);
  if (route.bookmarked) params.set('saved', '1');
  if (route.progress === 'draft' || route.progress === 'in_progress' || route.progress === 'not_started') params.set('progress', route.progress);
  return `/library${params.size ? `?${params.toString()}` : ''}`;
}
export function filterExercises(exercises: ExerciseMetadata[], route: ProductRoute, bookmarks: string[], drafts: Record<string, PracticeDraft> = {}): ExerciseMetadata[] {
  const query = route.query.trim().toLocaleLowerCase();
  const progress = route.progress === 'draft' || route.progress === 'in_progress' || route.progress === 'not_started' ? route.progress : 'all';
  const difficultyRank: Record<string, number> = { beginner: 0, easy: 0, intermediate: 1, medium: 1, advanced: 2, hard: 2 };
  return exercises.filter(exercise => (!route.difficulty || exercise.difficulty === route.difficulty)
    && (!route.topic || exercise.core_concepts.includes(route.topic))
    && (!route.bookmarked || bookmarks.includes(exercise.exercise_id))
    && (progress === 'all' || (() => { const prefix = `${encodeURIComponent(exercise.exercise_id)}::`; const entries = Object.entries(drafts).filter(([key]) => key.startsWith(prefix)); return progress === 'not_started' ? !entries.length : entries.some(([, draft]) => draft.status === (progress === 'draft' ? 'Draft' : 'In progress')); })())
    && (!query || [exercise.title, exercise.description, exercise.function_name, ...exercise.core_concepts].join(' ').toLocaleLowerCase().includes(query)))
    .sort((a, b) => route.sort === 'title' ? a.title.localeCompare(b.title) || a.exercise_id.localeCompare(b.exercise_id)
      : route.sort === 'difficulty' ? (difficultyRank[a.difficulty] ?? 1) - (difficultyRank[b.difficulty] ?? 1) || a.title.localeCompare(b.title) : 0);
}
// Session credentials intentionally remain tab-scoped, never in local draft storage.
export interface TabSession { readonly id: string; readonly token: string }
export function readTabSessions(): Record<string, TabSession> {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem('vcc-tab-sessions') ?? '{}');
    return record(raw) ? Object.fromEntries(Object.entries(raw).filter(([key, value]) => key !== '__proto__' && record(value) && typeof value.id === 'string' && typeof value.token === 'string')) as Record<string, TabSession> : {};
  } catch { return {}; }
}
export function rememberTabSession(problem: string, spec: string, session: TabSession): void {
  sessionStorage.setItem('vcc-tab-sessions', JSON.stringify({ ...readTabSessions(), [draftKey(problem, spec)]: session }));
}
export function forgetTabSession(problem: string, spec: string): void {
  const key = draftKey(problem, spec);
  sessionStorage.setItem('vcc-tab-sessions', JSON.stringify(Object.fromEntries(Object.entries(readTabSessions()).filter(([id]) => id !== key))));
}
