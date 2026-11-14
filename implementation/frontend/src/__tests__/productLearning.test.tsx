import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { apiClient } from '../services/apiClient';

// Explicit network fixtures: these tests are not evidence of live backend integration.
const catalogMock = { version: 'mock-v1', tracks: [{ id: 'python', module: 'Programming foundations', title: 'Python foundations', description: 'Understand the building blocks.', lessons: [
  { id: 'variables', title: 'Values and variables', prerequisites: [], difficulty: 'beginner', estimated_minutes: 8, objectives: ['Explain a variable'], explanation: 'A variable names a value.', example: 'count = 3', hints: ['Follow the assignment.'], practice_url: '/practice/dsa-second-largest', question: { id: 'q1', prompt: 'What value does count hold?', options: ['3', '4'] } },
  { id: 'loops', title: 'Loops and repetition', prerequisites: ['variables'], difficulty: 'beginner', estimated_minutes: 10, objectives: ['Trace a loop'], explanation: 'A loop repeats an action.', example: 'for n in range(3): print(n)', hints: [], practice_url: '/library', question: { id: 'q2', prompt: 'Explain the loop.' } },
] }] };
const progressMock = { lessons_completed: 0, attempts: 0, topics_mastered: 0, practice_sessions: 0, interviews_completed: 0, study_seconds: 0, streak: 0, completed_lesson_ids: [], achievements: [], recommendations: [], recent_activity: [] };
const sessionMock = { id: 'mock-session', lesson_id: 'variables', epoch: 0, mode: 'practice', state: 'active', question: catalogMock.tracks[0].lessons[0].question, coach_messages: [], answer_count: 0, deadline: null };
let fetcher: ReturnType<typeof vi.fn>;
let currentProgress: Record<string, unknown>;
let currentSession: Record<string, unknown>;

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  currentProgress = { ...progressMock }; currentSession = { ...sessionMock };
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
  sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ workspace: { id: 'mock-workspace', token: 'mock-token' }, sessions: [] }));
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === '/api/v1/learning/catalog') return response(catalogMock);
    if (url === '/api/v1/learning/progress') return response(currentProgress);
    if (url === '/api/v1/learning/sessions') return response(currentSession);
    if (url.endsWith('/hints')) return response({ ...currentSession, hint: 'Follow the assignment.' });
    if (url.endsWith('/answers')) {
      const body = JSON.parse(String(options?.body));
      const correct = body.answer === '3';
      currentSession = { ...currentSession, epoch: Number(currentSession.epoch) + 1, answer_count: Number(currentSession.answer_count) + 1, state: correct ? 'completed' : 'active', feedback: { correct, message: correct ? 'Exactly. Assignment stores the value 3.' : 'Try tracing the assignment again.' }, report: correct ? { lesson_completed: true, summary: 'You explained a variable.' } : null };
      if (correct) currentProgress = { ...progressMock, lessons_completed: 1, attempts: 1, completed_lesson_ids: ['variables'] };
      return response(currentSession);
    }
    if (url === '/api/v1/learning/sessions/mock-session') return response(currentSession);
    throw new Error(`Unmocked request: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function response(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }); }
function show(path: string) { history.replaceState({}, '', path); return render(<ProductApp />); }

describe('curriculum and lesson practice', () => {
  it('groups actual lessons and explains locked prerequisites', async () => {
    show('/learn');
    expect(await screen.findByRole('heading', { name: 'Python foundations' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Values and variables/ })).toHaveAttribute('href', '/learn/variables');
    expect(screen.queryByRole('link', { name: /Loops and repetition/ })).not.toBeInTheDocument();
    expect(screen.getByText('Complete Values and variables to unlock.')).toBeInTheDocument();
    expect(screen.getByText('0 of 2 lessons completed')).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith('/api/v1/learning/progress', expect.objectContaining({ headers: expect.objectContaining({ 'X-Workspace-Id': 'mock-workspace', 'X-Workspace-Token': 'mock-token' }) }));
  });
  it('cannot start a locked lesson through its direct URL', async () => {
    show('/learn/loops');
    await screen.findByRole('heading', { name: 'Loops and repetition' });
    expect(screen.getByText('Complete Values and variables to unlock.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Start practice/ })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url]) => url === '/api/v1/learning/sessions')).toBe(false);
  });
  it('runs lesson practice, requests a hint, persists session and unlocks next lesson', async () => {
    const view = show('/learn/variables');
    await screen.findByRole('heading', { name: 'Values and variables' });
    fireEvent.click(screen.getByRole('button', { name: 'Start practice' }));
    await screen.findByText('What value does count hold?');
    fireEvent.click(screen.getByRole('button', { name: 'Get a hint' }));
    expect(await screen.findByText('Follow the assignment.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: '4' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }));
    expect(await screen.findByText('Try tracing the assignment again.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: '3' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }));
    expect(await screen.findByText('Exactly. Assignment stores the value 3.')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: /Next lesson: Loops and repetition/ })).toHaveAttribute('href', '/learn/loops');
    const answerCalls = fetcher.mock.calls.filter(([url]) => String(url).endsWith('/answers'));
    expect(JSON.parse(String(answerCalls[1][1]?.body))).toEqual({ expected_epoch: 1, question_id: 'q1', answer: '3' });
    view.unmount(); show('/learn/variables');
    await screen.findByText('Exactly. Assignment stores the value 3.');
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/v1/learning/sessions')).toHaveLength(1);
  });
  it('handles catalog failure with a retry and never shows fabricated lessons', async () => {
    fetcher.mockImplementationOnce(async () => response({ message: 'Catalog offline' }, 503));
    show('/learn');
    expect((await screen.findByRole('alert')).textContent).toContain('Catalog offline');
    fireEvent.click(screen.getByRole('button', { name: 'Retry learning' }));
    await screen.findByRole('heading', { name: 'Python foundations' });
  });
  it('recovers an unknown or malformed lesson with a curriculum link', async () => {
    show('/learn/%');
    await screen.findByRole('heading', { name: 'Lesson not found' });
    expect(screen.getByRole('link', { name: 'Back to curriculum' })).toHaveAttribute('href', '/learn');
  });
  it('keeps failed answers editable and displays recovery feedback', async () => {
    show('/learn/variables'); await screen.findByRole('button', { name: 'Start practice' });
    fireEvent.click(screen.getByRole('button', { name: 'Start practice' })); await screen.findByText('What value does count hold?');
    fireEvent.click(screen.getByRole('radio', { name: '3' }));
    const normalFetch = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, options?: RequestInit) => String(url).endsWith('/answers') ? response({ message: 'Please retry your answer.' }, 503) : normalFetch(url, options));
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Please retry your answer.');
    expect(screen.getByRole('radio', { name: '3' })).toBeChecked();
    expect(screen.getByRole('button', { name: 'Check answer' })).toBeEnabled();
  });
});

describe('real progress surfaces', () => {
  it('starts with honest beginner progress and keeps teacher discovery', async () => {
    show('/dashboard');
    await screen.findByText('Your first lesson is a good place to start.');
    expect(screen.getByRole('heading', { name: 'Meet Your AI Teachers' })).toBeInTheDocument();
    expect(screen.queryByText(/leaderboard/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Total XP/i)).not.toBeInTheDocument();
  });
  it('only displays achievements with a recorded source event', async () => {
    currentProgress = { ...progressMock, lessons_completed: 1, completed_lesson_ids: ['variables'], achievements: [{ id: 'first', title: 'First lesson', earned_at: '2026-11-15', source_event: 'lesson.completed' }, { id: 'fake', title: 'Fake badge', earned_at: '2026-11-15' }] };
    show('/progress');
    expect(await screen.findByText('First lesson')).toBeInTheDocument();
    expect(screen.queryByText('Fake badge')).not.toBeInTheDocument();
    expect(screen.getByText(/not proven mastery/)).toBeInTheDocument();
  });
});

describe('navigation contracts', () => {
  it('provides real curriculum and settings routes without overriding handled clicks', async () => {
    show('/learn'); await screen.findByRole('heading', { name: 'Python foundations' });
    const main = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(within(main).getByRole('link', { name: 'Learn' })).toHaveAttribute('href', '/learn');
    const handled = document.createElement('a'); handled.href = '/progress'; handled.textContent = 'Handled'; handled.addEventListener('click', e => e.preventDefault()); document.body.appendChild(handled);
    fireEvent.click(handled); expect(location.pathname).toBe('/learn'); handled.remove();
    fireEvent.click(screen.getByRole('link', { name: 'Settings', exact: true }));
    expect(location.pathname).toBe('/settings');
  });
  it('responds to same-path query changes', async () => {
    show('/settings?category=appearance');
    expect(await screen.findByRole('heading', { name: 'Appearance', exact: true })).toBeInTheDocument();
    act(() => { history.pushState({}, '', '/settings?category=privacy'); window.dispatchEvent(new PopStateEvent('popstate')); });
    expect(await screen.findByRole('heading', { name: 'Privacy', exact: true })).toBeInTheDocument();
  });
});
