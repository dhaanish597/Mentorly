import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { apiClient } from '../services/apiClient';
import { parseLearningProgress } from '../services/learningApi';
import type { InterviewReport, InterviewSession } from '../features/interview/types';

// Network fixtures exercise the real frontend transport, not a live backend.
const workspace = { id: 'report-workspace', token: 'fixture-capability' };
const progress = { lessons_completed: 0, attempts: 0, topics_mastered: 0, practice_sessions: 0, interviews_completed: 1, study_seconds: 0, streak: 0, completed_lesson_ids: [], achievements: [], recommendations: [], recent_activity: [] };
const question = { id: 'q1', text: 'Saved interview B question.', kind: 'primary' as const, parent_id: null, source_refs: [] };
const active: InterviewSession = { id: 'B', type: 'dsa', difficulty: 'beginner', topics: [], duration_minutes: 15, language_mode: 'en-IN', epoch: 1, state: 'active', deadline_at: '2099-01-01T00:00:00Z', started_at: '2026-11-15T10:00:00Z', question, introduction: { text: 'Fixture introduction.', source_refs: [] }, acknowledgement: null, report: null };
function completed(id: string): InterviewReport {
  return { session_id: id, completion_reason: 'finished', completed_at: '2026-11-15T10:15:00Z', answered_count: 1, semantic_validity: { status: 'unassessed', reason: 'Not graded.' }, technical_correctness: { status: 'unassessed_no_execution_evidence', reason: 'Code not run.' }, psychology: { status: 'not_assessed', reason: 'Never inferred.' }, answers: [{ question_id: `q-${id}`, question: `Recorded question ${id}`, answer: `Recorded answer ${id}`, code: null, indicators: [] }], recommendations: [], limitations: ['Text evidence only.'] };
}
const config = { types: ['dsa'], difficulties: ['beginner'], duration_minutes: { minimum: 5, maximum: 60, default: 15 }, language_modes: ['en-IN'], camera_default: false };
const catalog = { topics: { dsa: [], cs: [], system_design: [], codebase_defense: [] }, dsa_exercises: [] };
function response(value: unknown, status = 200): Response { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }); }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function show(url: string) { history.replaceState({}, '', url); return render(<ProductApp />); }
function move(url: string) { act(() => { history.pushState({}, '', url); window.dispatchEvent(new PopStateEvent('popstate')); }); }
function interviewReads(fetcher: ReturnType<typeof vi.fn>) { return fetcher.mock.calls.filter(([url]) => String(url).startsWith('/api/v1/interviews/')); }
let fetcher: ReturnType<typeof vi.fn<(url: string, options?: RequestInit) => Promise<Response>>>;
let media: ReturnType<typeof vi.fn>;
let audio: ReturnType<typeof vi.fn>;
let voice: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear(); localStorage.clear();
  sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ workspace, sessions: [] }));
  sessionStorage.setItem(`viva-interview:${workspace.id}`, 'B');
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
  media = vi.fn(); audio = vi.fn(); voice = vi.fn();
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: media } });
  vi.stubGlobal('AudioContext', audio); vi.stubGlobal('speechSynthesis', { speak: voice, cancel: vi.fn() });
  fetcher = vi.fn(async (url: string) => {
    if (url === '/api/v1/learning/progress') return response({ ...progress, recent_activity: [{ id: 'interview:A:completed', type: 'interview.completed', title: 'dsa interview', created_at: '2026-11-15', session_id: 'A' }] });
    if (url === '/api/v1/interviews/config') return response(config);
    if (url === '/api/v1/interviews/catalog') return response(catalog);
    if (url === '/api/v1/interviews/sessions/B') return response(active);
    if (url.startsWith('/api/v1/interviews/reports/')) return response(completed(decodeURIComponent(url.slice('/api/v1/interviews/reports/'.length))));
    throw new Error(`Unmocked request: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); localStorage.clear(); });

function expectReadOnly(): void {
  expect(fetcher.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
  expect(interviewReads(fetcher).every(([url]) => String(url).startsWith('/api/v1/interviews/reports/'))).toBe(true);
  expect(media).not.toHaveBeenCalled(); expect(audio).not.toHaveBeenCalled(); expect(voice).not.toHaveBeenCalled();
  expect(screen.queryByRole('timer')).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Start|Finish|Submit|camera|microphone|voice/i })).not.toBeInTheDocument();
  expect(sessionStorage.getItem(`viva-interview:${workspace.id}`)).toBe('B');
}

describe('progress interview report references', () => {
  it('preserves a valid completed interview session reference without mutating the source', () => {
    const activity = Object.freeze({ id: 'completed-A', type: 'interview.completed', title: 'dsa interview', session_id: 'A' });
    expect(parseLearningProgress({ ...progress, recent_activity: [activity] }).recent_activity[0]).toMatchObject({ kind: 'interview.completed', session_id: 'A' });
    expect(activity.session_id).toBe('A');
  });
  it.each([undefined, null, '', '.', '..', ' ', '\t', 5, false, [], {}, ' A', 'A ', 'A\nB', 'A\u0000B', 'A' + String.fromCodePoint(0x200b) + 'B', '\ud800', 'x'.repeat(201)])('omits invalid optional session reference %j without losing activity', value => {
    const parsed = parseLearningProgress({ ...progress, recent_activity: [{ kind: 'interview.completed', title: 'Recorded interview', session_id: value }] });
    expect(parsed.recent_activity[0].title).toBe('Recorded interview');
    expect(parsed.recent_activity[0]).not.toHaveProperty('session_id');
  });
  it.each(['A', 'x'.repeat(200), 'প্রতিবেদন-🙂', "report-'?/#\\", 'report%opaque'])('preserves bounded opaque identifier %s', id => {
    expect(parseLearningProgress({ ...progress, recent_activity: [{ kind: 'interview.completed', title: 'Interview', session_id: id }] }).recent_activity[0]).toHaveProperty('session_id', id);
  });
  it('keeps progress parsing bounded in behavior with 10,000 activity references', () => {
    const recent_activity = Array.from({ length: 10000 }, (_, index) => ({ kind: 'interview.completed', title: `Interview ${index}`, session_id: `session-${index}` }));
    const parsed = parseLearningProgress({ ...progress, recent_activity });
    expect(parsed.recent_activity).toHaveLength(10000);
    expect(parsed.recent_activity[9999]).toHaveProperty('session_id', 'session-9999');
  });
  it('links completed A from progress while retaining B resume through report and back navigation', async () => {
    const storage = sessionStorage.getItem('viva-studio-tab-v1');
    show('/progress');
    const link = await screen.findByRole('link', { name: 'View interview report' });
    expect(link).toHaveAttribute('href', '/interviews?report=A');
    fireEvent.click(link);
    expect(location.pathname + location.search).toBe('/interviews?report=A');
    await screen.findByRole('heading', { name: 'Interview report', level: 2 });
    expect(screen.getByText('Recorded answer A')).toBeInTheDocument();
    expect(screen.getByText(/Completion is not proof/)).toBeInTheDocument();
    expect(interviewReads(fetcher).map(([url]) => url)).toEqual(['/api/v1/interviews/reports/A']);
    expectReadOnly();
    expect(sessionStorage.getItem('viva-studio-tab-v1')).toBe(storage);
    fireEvent.click(screen.getByRole('link', { name: 'Back to progress' }));
    expect(location.pathname).toBe('/progress');
    await screen.findByRole('link', { name: 'View interview report' });
    expect(sessionStorage.getItem(`viva-interview:${workspace.id}`)).toBe('B');
  });
  it('does not link lessons, active interviews, or invalid completed references', async () => {
    fetcher.mockImplementation(async () => response({ ...progress, recent_activity: [
      { kind: 'lesson.completed', title: 'Recorded lesson', session_id: 'lesson' },
      { kind: 'interview.started', title: 'Active interview', session_id: 'B' },
      { kind: 'interview.completed', title: 'Invalid interview', session_id: ' ' },
      { kind: 'interview.completed', title: 'Legacy interview' },
    ] }));
    show('/progress');
    await screen.findByText('Legacy interview');
    expect(screen.queryByRole('link', { name: 'View interview report' })).not.toBeInTheDocument();
  });
  it('encodes the optional session reference into a fixed internal report route', async () => {
    const id = "প্রতিবেদন-🙂?/#\\'";
    fetcher.mockImplementation(async () => response({ ...progress, recent_activity: [{ type: 'interview.completed', title: 'Special interview', session_id: id }] }));
    show('/progress');
    expect(await screen.findByRole('link', { name: 'View interview report' })).toHaveAttribute('href', `/interviews?report=${encodeURIComponent(id)}`);
  });
});

describe('read-only report query navigation', () => {
  it('shows loading with a back link, renders a completed report and leaves all storage untouched', async () => {
    const pending = deferred<Response>(); fetcher.mockImplementation(() => pending.promise);
    const sessionBefore = { ...sessionStorage }; const localBefore = { ...localStorage };
    const interval = vi.spyOn(window, 'setInterval');
    show('/interviews?report=A');
    expect(screen.getByRole('status')).toHaveTextContent('Loading interview report');
    expect(screen.getByRole('link', { name: 'Back to progress' })).toHaveAttribute('href', '/progress');
    await act(async () => pending.resolve(response(completed('A'))));
    expect(screen.getByText('Recorded answer A')).toBeInTheDocument();
    expect(interval).not.toHaveBeenCalled();
    expect({ ...sessionStorage }).toEqual(sessionBefore); expect({ ...localStorage }).toEqual(localBefore);
    expect(fetcher).toHaveBeenCalledWith('/api/v1/interviews/reports/A', expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-Workspace-Id': workspace.id, 'X-Workspace-Token': workspace.token }) }));
    expectReadOnly();
  });
  it('updates reports when only the report query changes and on history navigation', async () => {
    show('/interviews?report=A'); await screen.findByText('Recorded answer A');
    move('/interviews?report=C'); await screen.findByText('Recorded answer C');
    expect(screen.queryByText('Recorded answer A')).not.toBeInTheDocument();
    move('/interviews?report=A'); await screen.findByText('Recorded answer A');
    expectReadOnly();
  });
  it.each(['resolve', 'reject'] as const)('fences a delayed A %s after navigating to report C', async outcome => {
    const pending = deferred<Response>();
    fetcher.mockImplementation(async url => url.endsWith('/A') ? pending.promise : response(completed('C')));
    show('/interviews?report=A');
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    move('/interviews?report=C'); await screen.findByText('Recorded answer C');
    await act(async () => { if (outcome === 'resolve') pending.resolve(response(completed('A'))); else pending.reject(new Error('Old A failure')); });
    expect(screen.getByText('Recorded answer C')).toBeInTheDocument();
    expect(screen.queryByText('Recorded answer A')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expectReadOnly();
  });
  it('fences A after leaving the interview report route entirely', async () => {
    const pending = deferred<Response>();
    fetcher.mockImplementation(async url => url.endsWith('/A') ? pending.promise : response(progress));
    show('/interviews?report=A'); await waitFor(() => expect(fetcher).toHaveBeenCalled());
    move('/progress'); await screen.findByRole('heading', { name: 'Learning record' });
    await act(async () => pending.resolve(response(completed('A'))));
    expect(screen.queryByText('Recorded answer A')).not.toBeInTheDocument();
    expectReadOnly();
  });
  it('keeps the no-report interactive route resuming B after viewing A', async () => {
    show('/interviews?report=A'); await screen.findByText('Recorded answer A');
    expectReadOnly();
    move('/interviews'); await screen.findByText(question.text);
    expect(screen.getByLabelText('Your answer')).toBeInTheDocument();
    expect(sessionStorage.getItem(`viva-interview:${workspace.id}`)).toBe('B');
    expect(fetcher.mock.calls.some(([url]) => url === '/api/v1/interviews/sessions/B')).toBe(true);
    expect(fetcher.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
  });
  it.each([403, 404, 503])('shows a safe unavailable state and retries the same read after status %s', async status => {
    fetcher.mockResolvedValueOnce(response({ detail: 'Private backend detail must not be displayed.' }, status));
    show('/interviews?report=A');
    expect(await screen.findByRole('alert')).toHaveTextContent('Interview report unavailable');
    expect(screen.queryByText(/Private backend/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to progress' })).toBeInTheDocument();
    expectReadOnly();
    fireEvent.click(screen.getByRole('button', { name: 'Retry interview report' }));
    await screen.findByText('Recorded answer A');
    expect(interviewReads(fetcher).map(([url]) => url)).toEqual(['/api/v1/interviews/reports/A', '/api/v1/interviews/reports/A']);
    expectReadOnly();
  });
  it.each(['active', 'missing', 'session-payload', 'wrong-report'] as const)('does not render or finish an unavailable %s report', async kind => {
    const value = kind === 'active' ? { detail: 'Report unavailable' } : kind === 'missing' ? null : kind === 'session-payload' ? { ...active, state: 'completed', question: null, report: completed('A') } : completed('foreign');
    fetcher.mockResolvedValue(response(value, kind === 'active' ? 404 : 200));
    show('/interviews?report=A');
    expect(await screen.findByRole('alert')).toHaveTextContent('Interview report unavailable');
    expect(screen.queryByRole('heading', { name: 'Interview report', level: 2 })).not.toBeInTheDocument();
    expect(screen.queryByText('Recorded answer A')).not.toBeInTheDocument();
    expectReadOnly();
  });
  it('never loads or auto-expires an active interview session when its report is unavailable', async () => {
    const expiredActive = { ...active, deadline_at: '2020-01-01T00:00:00Z' };
    fetcher.mockImplementation(async url => {
      if (url === '/api/v1/interviews/reports/B') return response({ detail: 'Report unavailable' }, 404);
      if (url === '/api/v1/interviews/sessions/B') return response(expiredActive);
      throw new Error(`Unmocked request: ${url}`);
    });
    show('/interviews?report=B');
    await screen.findByRole('alert');
    expectReadOnly();
    fireEvent.click(screen.getByRole('button', { name: 'Retry interview report' }));
    await screen.findByRole('alert');
    expect(interviewReads(fetcher).map(([url]) => url)).toEqual(['/api/v1/interviews/reports/B', '/api/v1/interviews/reports/B']);
    expect(expiredActive.state).toBe('active'); expect(expiredActive.report).toBeNull();
    expectReadOnly();
  });
  it('does not create a workspace or change resume storage when the workspace capability is absent', async () => {
    sessionStorage.removeItem('viva-studio-tab-v1');
    show('/interviews?report=A');
    expect(await screen.findByRole('alert')).toHaveTextContent('Interview report unavailable');
    expect(fetcher).not.toHaveBeenCalled();
    expectReadOnly();
  });
  it.each(['?report', '?report=', '?report=.', '?report=..', '?report=%2e', '?report=%2E%2E', '?report=%20', '?report=A&report=C', '?report=A&report=A', '?report=A&%72eport=C', '?report=&report=A', '?report=%00A', '?report=A%0AB', '?report=A%E2%80%8BB', '?report=%', '?report=%E0%A4%A', '?report=%FF', '?report=%E0%A4', '?report=%C0%AF', `?report=${'x'.repeat(201)}`])('rejects malformed or repeated selector %s without network or interactive side effects', async search => {
    show(`/interviews${search}`);
    expect(await screen.findByRole('alert')).toHaveTextContent('Interview report unavailable');
    expect(screen.getByRole('link', { name: 'Back to progress' })).toHaveAttribute('href', '/progress');
    expect(fetcher).not.toHaveBeenCalled();
    expectReadOnly();
  });
  it.each(['x'.repeat(200), 'প্রতিবেদন-🙂', "report-'?/#\\", 'report%opaque'])('reads a single bounded identifier %s with safe path encoding', async id => {
    show(`/interviews?report=${encodeURIComponent(id)}&other=ignored`);
    await screen.findByText(`Recorded answer ${id}`);
    expect(interviewReads(fetcher).map(([url]) => url)).toEqual([`/api/v1/interviews/reports/${encodeURIComponent(id)}`]);
    expectReadOnly();
  });
});
