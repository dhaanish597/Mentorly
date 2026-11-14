import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RedrivePanel } from '../features/redrive/RedrivePanel';
import { DefenseFollowup } from '../features/redrive/DefenseFollowup';
import { RepositoryPanel } from '../StudioRepository';

const recorder = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), dispose: vi.fn() }));
vi.mock('../services/audioRecorder', () => ({ AudioRecorder: class {
  startMicrophoneCapture = recorder.start;
  stopMicrophoneCapture = recorder.stop;
  dispose = recorder.dispose;
} }));
const workspace = { id: 'w', token: 'workspace-private' };
const session = { id: 'session', token: 'session-private', workspace };
const citation = { path: 'main.py', symbol: 'run', start_line: 1, end_line: 2, chunk_hash: 'a'.repeat(64) };
const step = { step_id: 'file', phase: 'fundamentals', concept: 'source_file', title: 'One source file',
  explanation: 'A file groups source text. Read the cited file before guessing.', question: 'Which source path is cited?',
  prerequisites: [], citations: [citation], facts: [{ kind: 'source_path', expected: 'main.py' }], mastery: 'not_established' };
const plan = { plan_id: 'p', snapshot_id: 's', snapshot_hash: 'b'.repeat(64), epoch: 1, status: 'learning',
  current_step: step, steps: [step], checkpoint: { cursor: 0, completed_step_ids: [] }, revisit_step_ids: [],
  attempts: [], evidence_events: [], limitations: ['Static source does not establish runtime behavior or author intent.'] };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  recorder.start.mockResolvedValue(undefined);
  recorder.stop.mockResolvedValue({ wavBytes: new Uint8Array([1, 2]) });
  recorder.dispose.mockResolvedValue(undefined);
  fetcher = vi.fn(async (url: string, options: RequestInit = {}) => {
    if (url.endsWith('/learning-plan') || url.endsWith('/learning-plans/p')) return json(plan);
    if (url.endsWith('/answers')) return json({ ...plan, epoch: 2, status: 'complete', current_step: null,
      checkpoint: { cursor: 1, completed_step_ids: ['file'] }, evidence_events: [{ sequence: 1, step_id: 'file', assessment: 'supported_observation', feedback: 'Source observation recorded; mastery is not established.', citations: [citation], question: '', mastery: 'not_established' }],
      attempts: [{ sequence: 1, step_id: 'file', answer: 'main.py', created_at: '2026-11-15' }] });
    if (url.endsWith('/speech')) return json({ epoch: 7, normalized_transcript: 'main.py' });
    if (url.endsWith('/map')) return json({ files: [] });
    if (url.endsWith('/evidence')) return json({ cards: [] });
    return json({ snapshot_id: 's', status: 'READY', files_indexed: 1, total_files: 1, coverage_ratio: 1 });
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { cleanup(); sessionStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const props = { workspace, snapshotId: 's', onOpenSource: vi.fn() };

it('shows one grounded concept and submits a reviewed answer with epoch and workspace headers', async () => {
  render(<RedrivePanel {...props} />);
  await screen.findByRole('heading', { name: 'One source file' });
  fireEvent.click(screen.getByRole('button', { name: /main.py, lines 1–2/ }));
  expect(props.onOpenSource).toHaveBeenCalledWith(citation);
  expect(screen.getByText(/Mastery is not established/i)).toBeTruthy();
  const submit = screen.getByRole('button', { name: 'Save comprehension answer' }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Your beginner answer'), { target: { value: 'main.py' } });
  fireEvent.click(submit);
  await screen.findByText('Plan completed. Revisit the cited source; completion is not mastery.');
  const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/answers'))!;
  expect(JSON.parse(options.body)).toEqual({ expected_epoch: 1, answer: 'main.py' });
  expect(options.headers['X-Workspace-Token']).toBe(workspace.token);
  expect(options.headers['X-Workspace-Id']).toBe(workspace.id);
});

it('embeds the requested beginner button and leaves existing defense intact', async () => {
  sessionStorage.setItem('viva-repo-tab-v1', JSON.stringify({ workspace_id: 'w', snapshot_id: 's' }));
  render(<RepositoryPanel workspace={workspace} ensureWorkspace={async () => workspace} onSnapshot={vi.fn()} />);
  await screen.findByText(/Coverage: 100%/);
  fireEvent.click(screen.getByRole('button', { name: 'Teach me from the beginning' }));
  await screen.findByRole('heading', { name: 'One source file' });
  expect(screen.getByRole('button', { name: 'Return to repository defense' })).toBeTruthy();
});

it('preserves drafts and refreshes checkpoint after a stale epoch conflict', async () => {
  fetcher.mockImplementation(async (url: string) => url.endsWith('/answers') ? json({ detail: 'learning epoch conflict; reload your checkpoint' }, 409) : json(plan));
  render(<RedrivePanel {...props} />);
  await screen.findByRole('heading', { name: 'One source file' });
  fireEvent.change(screen.getByLabelText('Your beginner answer'), { target: { value: 'preserve me' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save comprehension answer' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('epoch conflict');
  expect(screen.getByLabelText('Your beginner answer')).toHaveValue('preserve me');
  fireEvent.click(screen.getByRole('button', { name: 'Reload checkpoint' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/learning-plans/p'))).toBe(true));
});

it('ignores results after snapshot/capability replacement', async () => {
  let resolve!: (response: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  const view = render(<RedrivePanel {...props} />);
  view.rerender(<RedrivePanel {...props} snapshotId="new" workspace={{ id: 'new-w', token: 'new-token' }} />);
  await act(async () => resolve(json(plan)));
  expect(screen.queryByRole('heading', { name: 'One source file' })).toBeNull();
  expect(await screen.findByRole('alert')).toHaveTextContent(/snapshot|checkpoint/i);
});

it('voice uses the existing speech seam as a draft and never auto-submits', async () => {
  render(<RedrivePanel {...props} session={session} speechEpoch={7} />);
  await screen.findByRole('heading', { name: 'One source file' });
  fireEvent.click(screen.getByRole('button', { name: 'Talk' }));
  await screen.findByRole('button', { name: 'Stop' });
  fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
  await waitFor(() => expect(screen.getByLabelText('Your beginner answer')).toHaveValue('main.py'));
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/answers'))).toBe(false);
  const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/speech'))!;
  expect(JSON.parse(options.body).expected_epoch).toBe(7);
  expect(options.headers['X-Session-Token']).toBe(session.token);
});

it('renders source-adaptive defense followups from actual recorded phase feedback without grading', () => {
  render(<DefenseFollowup phase="derive" answer="The author intended perfect reliability" citations={[citation]} onOpenSource={props.onOpenSource} />);
  expect(screen.getByText(/author intent.*not established/i)).toBeTruthy();
  expect(screen.getByText(/Which cited fact/i)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /main.py/ }));
  expect(props.onOpenSource).toHaveBeenCalledWith(citation);
});

it('rejects malformed source references instead of rendering an invalid lesson', async () => {
  fetcher.mockResolvedValue(json({ ...plan, current_step: { ...step, citations: [{ ...citation, chunk_hash: 'bad' }] } }));
  render(<RedrivePanel {...props} />);
  expect(await screen.findByRole('alert')).toHaveTextContent(/checkpoint|reference/i);
  expect(screen.queryByRole('button', { name: 'Save comprehension answer' })).toBeNull();
});
