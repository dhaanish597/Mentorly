import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InterviewReportRoute } from '../features/interview/InterviewReportRoute';
import type { InterviewSession, Workspace } from '../features/interview/types';

const workspace: Workspace = { id: 'workspace-a', token: 'fixture-a' };
function completed(id: string, evidence: string): InterviewSession {
  return { id, type: 'cs', difficulty: 'beginner', topics: [], duration_minutes: 15, language_mode: 'en-IN', epoch: 2, state: 'completed', started_at: '2026-11-15T10:00:00Z', deadline_at: '2026-11-15T10:15:00Z', question: null, introduction: { text: 'Fixture introduction.', source_refs: [] }, acknowledgement: null, report: { session_id: id, completion_reason: 'finished', completed_at: '2026-11-15T10:15:00Z', answered_count: 1, semantic_validity: { status: 'unassessed', reason: 'Not graded.' }, technical_correctness: { status: 'unassessed_no_execution_evidence', reason: 'No execution.' }, psychology: { status: 'not_assessed', reason: 'Never inferred.' }, answers: [{ question_id: 'q1', question: 'Recorded question', answer: evidence, code: null, indicators: [] }], recommendations: [], limitations: ['Text only.'] } };
}
function response(session: InterviewSession): Response { return new Response(JSON.stringify(session.report)); }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('report workspace and request lifecycle', () => {
  it.each(['workspace-id', 'workspace-token'] as const)('fences a pending A response after changing %s with the same report selector', async change => {
    const pending = deferred<Response>();
    const fetcher = vi.fn().mockImplementationOnce(() => pending.promise).mockResolvedValue(response(completed('A', 'Current workspace evidence')));
    vi.stubGlobal('fetch', fetcher);
    const view = render(<InterviewReportRoute workspace={workspace} search="?report=A" />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const next = change === 'workspace-id' ? { ...workspace, id: 'workspace-c' } : { ...workspace, token: 'fixture-c' };
    view.rerender(<InterviewReportRoute workspace={next} search="?report=A" />);
    await screen.findByText('Current workspace evidence');
    await act(async () => pending.resolve(response(completed('A', 'Stale workspace evidence'))));
    expect(screen.queryByText('Stale workspace evidence')).not.toBeInTheDocument();
    expect(screen.getByText('Current workspace evidence')).toBeInTheDocument();
    expect(fetcher).toHaveBeenLastCalledWith('/api/v1/interviews/reports/A', expect.objectContaining({ headers: expect.objectContaining({ 'X-Workspace-Id': next.id, 'X-Workspace-Token': next.token }) }));
  });
  it('hides an already loaded report immediately when its workspace changes', async () => {
    const pending = deferred<Response>();
    const fetcher = vi.fn().mockResolvedValueOnce(response(completed('A', 'Previous workspace evidence'))).mockImplementationOnce(() => pending.promise);
    vi.stubGlobal('fetch', fetcher);
    const view = render(<InterviewReportRoute workspace={workspace} search="?report=A" />);
    await screen.findByText('Previous workspace evidence');
    view.rerender(<InterviewReportRoute workspace={{ ...workspace, id: 'workspace-c' }} search="?report=A" />);
    expect(screen.queryByText('Previous workspace evidence')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading interview report');
    await act(async () => pending.resolve(response(completed('A', 'New workspace evidence'))));
    await screen.findByText('New workspace evidence');
  });
  it.each(['selector', 'workspace'] as const)('fences A when %s becomes unavailable', async change => {
    const pending = deferred<Response>(); const fetcher = vi.fn(() => pending.promise);
    vi.stubGlobal('fetch', fetcher);
    const view = render(<InterviewReportRoute workspace={workspace} search="?report=A" />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    view.rerender(<InterviewReportRoute workspace={change === 'workspace' ? null : workspace} search={change === 'selector' ? '?report=A&report=C' : '?report=A'} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Interview report unavailable');
    await act(async () => pending.resolve(response(completed('A', 'Stale A evidence'))));
    expect(screen.queryByText('Stale A evidence')).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('does not request a missing selector even with an available workspace', () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    render(<InterviewReportRoute workspace={workspace} search="?other=A" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Interview report unavailable');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('ignores a delayed network failure after unmount', async () => {
    const pending = deferred<Response>(); const fetcher = vi.fn(() => pending.promise);
    vi.stubGlobal('fetch', fetcher);
    const view = render(<InterviewReportRoute workspace={workspace} search="?report=A" />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => pending.reject(new Error('Old network failure')));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('retries a network rejection and exposes no report mutation controls', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('Network offline')).mockResolvedValueOnce(response(completed('A', 'Recovered evidence')));
    vi.stubGlobal('fetch', fetcher);
    render(<InterviewReportRoute workspace={workspace} search="?report=A" />);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Retry interview report' }));
    await screen.findByText('Recovered evidence');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(fetcher.mock.calls.every(([, options]) => options.method === 'GET')).toBe(true);
  });
});
