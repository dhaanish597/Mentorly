import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseLearningCatalog, parseLearningProgress, parseLearningSession, learningUrl } from '../services/learningApi';
import { ensureWorkspaceSession } from '../state/workspaceSession';
import { readStudioTab } from '../studioApi';
import { readLessonSession, rememberLessonSession } from '../features/curriculum/lessonSession';

// Contract fixtures only; no live provider or backend assertions.
const workspace = { id: 'mock-shared', token: 'mock-token' };
const session = { id: 'session', lesson_id: 'l1', epoch: 2, mode: 'practice', state: 'active', question: { id: 'q', prompt: 'Choose a value', options: ['1', '2'] }, coach_messages: [{ id: 'msg-real', role: 'assistant', kind: 'hint', text: 'Trace the value.' }], answer_count: 0, hint_count: 1, hint: 'Trace the value.', deadline: null };
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); });
describe('validated learning and workspace contracts', () => {
  it('preserves real message IDs for audio alongside rendered text', () => {
    const parsed = parseLearningSession(session);
    expect(parsed.coach_messages).toEqual(['Trace the value.']);
    expect(parsed.coach_message_refs[0].id).toBe('msg-real');
    expect(parsed.hint_count).toBe(1);
  });
  it('rejects incomplete, nonfinite and malformed API data', () => {
    expect(() => parseLearningCatalog(null)).toThrow();
    expect(() => parseLearningCatalog({ version: 'v', tracks: 'no' })).toThrow();
    expect(() => parseLearningSession({ ...session, epoch: Infinity })).toThrow();
    expect(() => parseLearningSession({ ...session, question: { id: 'q' } })).toThrow();
    expect(() => parseLearningProgress({})).toThrow();
  });
  it.each(['javascript:alert(1)', '//evil.test/x', '/\\evil.test', '/unsafe path', 'https://evil.test'])('rejects unsafe internal destination %s', url => {
    expect(learningUrl(url)).toBe('/learn');
  });
  it('keeps valid product query navigation', () => expect(learningUrl('/studio?scenario=bridge')).toBe('/studio?scenario=bridge'));
  it('reuses existing studio workspace without another creation request', async () => {
    sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ workspace, sessions: [{ id: 'studio-session', token: 'session-token', workspace }] }));
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    expect(await ensureWorkspaceSession()).toEqual(workspace);
    expect(fetcher).not.toHaveBeenCalled();
    expect(readStudioTab().sessions).toHaveLength(1);
  });
  it('deduplicates workspace creation and preserves studio sessions at publication', async () => {
    let resolve: (response: Response) => void = () => {};
    const fetcher = vi.fn(() => new Promise<Response>(done => { resolve = done; })); vi.stubGlobal('fetch', fetcher);
    const first = ensureWorkspaceSession(); const second = ensureWorkspaceSession();
    sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ sessions: [{ id: 'studio-session' }] }));
    resolve(new Response('{}', { status: 201 }));
    expect(await first).toEqual(await second);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(readStudioTab().sessions[0].id).toBe('studio-session');
    expect(readStudioTab().workspace?.id).toBeTruthy();
  });
  it('scopes lesson sessions to workspace and gracefully handles storage denial', () => {
    expect(rememberLessonSession(workspace, 'lesson', 'practice')).toBe(true);
    expect(readLessonSession(workspace, 'lesson')).toBe('practice');
    expect(readLessonSession({ ...workspace, id: 'other' }, 'lesson')).toBeNull();
    sessionStorage.setItem('viva-learning-sessions-v1', 'invalid');
    expect(readLessonSession(workspace, 'lesson')).toBeNull();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
    expect(rememberLessonSession(workspace, 'lesson', 'practice')).toBe(false);
  });
});
