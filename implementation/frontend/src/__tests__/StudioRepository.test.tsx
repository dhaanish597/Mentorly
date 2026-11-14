import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { RepositoryPanel } from '../StudioRepository';

const recorder = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), dispose: vi.fn() }));
vi.mock('../services/audioRecorder', () => ({
  AudioRecorder: class {
    startMicrophoneCapture = recorder.start;
    stopMicrophoneCapture = recorder.stop;
    dispose = recorder.dispose;
  },
}));
const workspace = { id: 'w', token: 'workspace-private' };
const session = { id: 'session', token: 'session-private', workspace };
const props = { workspace, ensureWorkspace: async () => workspace, onSnapshot: vi.fn() };
const snapshot = (id = 's', status = 'READY') => ({ snapshot_id: id, status, files_indexed: 2, total_files: 4, coverage_ratio: .5 });
const citation = { path: 'src/service.ts', symbol: 'serve', start_line: 1, end_line: 2, chunk_hash: 'a'.repeat(64), text: 'export function serve() {\n  return queue;\n}' };
const card = { evidence_card_id: 'card-1', topic: 'Queue boundary', origin: 'manual', observed_code: [citation], inferred_rationale: [] };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}
type Handler = (url: string, options: RequestInit) => Response | Promise<Response> | undefined;
let fetcher: ReturnType<typeof vi.fn>;
function server(handler?: Handler) {
  fetcher = vi.fn(async (url: string, options: RequestInit = {}) => {
    const custom = handler?.(url, options);
    if (custom) return custom;
    if (url.endsWith('/map')) return json({ files: [{ path: citation.path, rank: 1, imports: [], calls: [], symbols: ['serve'] }] });
    if (url.includes('/search?')) return json({ results: [citation] });
    if (url.includes('/files?')) return json({ path: citation.path, content: citation.text });
    if (url.endsWith('/evidence')) return options.method === 'POST' ? json(card) : json({ cards: [card] });
    if (url.endsWith('/decisions')) return json({ decisions: [] });
    if (url.endsWith('/defense/start')) return json({ phase: 'map', mode: 'repo_exploration', history: [], synthesis: {} });
    if (url.endsWith('/defense/answer')) return json({ phase: 'derive', mode: 'repo_exploration', history: [], synthesis: {} });
    if (url.endsWith('/defense')) return json({ phase: 'derive', prompt: 'Separate observed code from hypotheses.', uncertainty: 'Intent is not established.' });
    if (options.method === 'DELETE') return new Response(null, { status: 204 });
    return json(snapshot());
  });
  vi.stubGlobal('fetch', fetcher);
}
function restore() { sessionStorage.setItem('viva-repo-tab-v1', JSON.stringify({ workspace_id: workspace.id, snapshot_id: 's' })); }
async function ready(bound = false) {
  restore();
  const view = render(<RepositoryPanel {...props} session={bound ? session : undefined} speechEpoch={7} speechEvents={[]} />);
  await screen.findByText(/Coverage: 50%/);
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/evidence'))).toBe(true));
  return view;
}
function disclose(name: string) { fireEvent.click(screen.getByText(name, { selector: 'summary' })); }
async function selectCitation() {
  disclose('Search source');
  fireEvent.change(screen.getByLabelText('Search code'), { target: { value: 'queue' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  fireEvent.click(await screen.findByLabelText('Use this citation'));
}
function deleteSnapshot() {
  disclose('Snapshot tools');
  fireEvent.click(screen.getByRole('button', { name: 'Delete snapshot' }));
}
beforeEach(() => {
  props.onSnapshot.mockClear();
  recorder.start.mockResolvedValue(undefined);
  recorder.stop.mockResolvedValue({ wavBytes: new Uint8Array([1, 2]) });
  recorder.dispose.mockResolvedValue(undefined);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  server();
});
afterEach(() => { cleanup(); sessionStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('compact repository import', () => {
  it('defaults to a public URL and only reveals the chosen optional source', () => {
    render(<RepositoryPanel {...props} />);
    expect(screen.getByLabelText('Public HTTPS URL')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Public URL' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByLabelText('ZIP archive')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: 'ZIP archive' }));
    expect(screen.getByLabelText('ZIP archive', { selector: 'input' })).toBeTruthy();
    expect(screen.queryByLabelText('Public HTTPS URL')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: 'Curated example' }));
    expect(screen.getByLabelText('Example')).toBeTruthy();
    expect(screen.queryByLabelText('Inferred rationale')).toBeNull();
  });

  it('waits for READY, then loads map and saved cards without load buttons', async () => {
    server((url, options) => url.endsWith('/ingest') ? json(snapshot('s', 'QUEUED')) :
      url.endsWith('/s') && options.method === 'GET' ? json(snapshot()) : undefined);
    render(<RepositoryPanel {...props} />);
    fireEvent.change(screen.getByLabelText('Public HTTPS URL'), { target: { value: 'https://github.com/example/repo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await screen.findByText('Indexing in progress…');
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/map'))).toBe(false);
    await screen.findByText(/Coverage: 50%/, {}, { timeout: 3000 });
    await screen.findByRole('button', { name: citation.path });
    expect(props.onSnapshot).toHaveBeenCalledWith('s');
    expect(screen.queryByRole('button', { name: /Load repository map|Load saved evidence cards/ })).toBeNull();
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/ingest'))!;
    expect(JSON.parse(options.body)).toEqual({ source_kind: 'public_git_url', source_locator: 'https://github.com/example/repo' });
    expect(options.headers['X-Workspace-Token']).toBe(workspace.token);
    expect(sessionStorage.getItem('viva-repo-tab-v1')).toBe(JSON.stringify({ workspace_id: 'w', snapshot_id: 's' }));
  });

  it('finishes first import when ensureWorkspace publishes the newly created capability', async () => {
    function Parent() {
      const [created, setCreated] = useState<typeof workspace>();
      return <RepositoryPanel workspace={created} ensureWorkspace={async () => { setCreated(workspace); return workspace; }} onSnapshot={props.onSnapshot} />;
    }
    render(<Parent />);
    fireEvent.click(screen.getByRole('tab', { name: 'Curated example' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await screen.findByText(/Coverage: 50%/);
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/ingest'))).toHaveLength(1);
    expect(props.onSnapshot).toHaveBeenCalledWith('s');
  });

  it('keeps ZIP ingestion multipart and requires a chosen archive', async () => {
    render(<RepositoryPanel {...props} />);
    fireEvent.click(screen.getByRole('tab', { name: 'ZIP archive' }));
    expect((screen.getByRole('button', { name: 'Import and index' }) as HTMLButtonElement).disabled).toBe(true);
    const zip = new File(['archive'], 'source.zip', { type: 'application/zip' });
    fireEvent.change(screen.getByLabelText('ZIP archive', { selector: 'input' }), { target: { files: [zip] } });
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await screen.findByText(/Coverage: 50%/);
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/ingest'))!;
    expect(options.body).toBeInstanceOf(FormData);
    expect((options.body as FormData).get('file')).toBe(zip);
    expect(options.headers['Content-Type']).toBeUndefined();
  });

  it('does not restore an old indexing poll after replacement', async () => {
    const old = deferred(); let imports = 0;
    server(url => {
      if (url.endsWith('/ingest')) return json(snapshot(++imports === 1 ? 'old' : 'new', imports === 1 ? 'QUEUED' : 'READY'));
      if (url.endsWith('/old')) return old.promise;
      return undefined;
    });
    render(<RepositoryPanel {...props} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Curated example' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await screen.findByText('Indexing in progress…');
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/old'))).toBe(true), { timeout: 2500 });
    disclose('Replace repository');
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await waitFor(() => expect(props.onSnapshot).toHaveBeenCalledWith('new'));
    await act(async () => old.resolve(json(snapshot('old'))));
    expect(props.onSnapshot).not.toHaveBeenCalledWith('old');
  });
});

describe('bound repository session isolation', () => {
  it('uses the active session binding instead of a newer exploration tab snapshot', async () => {
    sessionStorage.setItem('viva-repo-tab-v1', JSON.stringify({ workspace_id: 'w', snapshot_id: 'explore-b' }));
    server(url => url.endsWith('/bound-a') ? json(snapshot('bound-a')) : undefined);
    render(<RepositoryPanel {...props} session={session} boundSnapshotId="bound-a" speechEpoch={7} speechEvents={[]} />);
    await screen.findByText(/Coverage: 50%/);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: map');
    await selectCitation();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Reasoning about bound A.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit defense answer' }));
    await screen.findByText('Current stage: derive');
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('/explore-b'))).toBe(false);
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/bound-a/defense/answer'))).toBe(true);
    expect(sessionStorage.getItem('viva-repo-tab-v1')).toContain('explore-b');
    expect(props.onSnapshot).not.toHaveBeenCalledWith('bound-a');
  });

  it('keeps a newly imported exploration snapshot separate until the bound session is cleared', async () => {
    sessionStorage.setItem('viva-repo-tab-v1', JSON.stringify({ workspace_id: 'w', snapshot_id: 'explore-b' }));
    server(url => url.endsWith('/bound-a') ? json(snapshot('bound-a')) : url.endsWith('/ingest') || url.endsWith('/explore-c') ? json(snapshot('explore-c')) : undefined);
    const view = render(<RepositoryPanel {...props} session={session} boundSnapshotId="bound-a" />);
    await screen.findByText(/Coverage: 50%/);
    disclose('Replace repository');
    fireEvent.click(screen.getByRole('tab', { name: 'Curated example' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await waitFor(() => expect(props.onSnapshot).toHaveBeenCalledWith('explore-c'));
    await selectCitation();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('/bound-a/search?'))).toBe(true);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('/explore-c/search?'))).toBe(false);
    view.rerender(<RepositoryPanel {...props} session={null} boundSnapshotId="bound-a" />);
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/explore-c/map'))).toBe(true));
    expect(sessionStorage.getItem('viva-repo-tab-v1')).toContain('explore-c');
  });

  it('refreshes validated coach events after releasing busy voice state so enabled coach speech can play', async () => {
    restore();
    const create = vi.fn().mockReturnValue('blob:coach');
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = vi.fn(); });
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
    server(url => url.endsWith('/speech/tts') ? json({ epoch: 7, audio_base64: 'AQI=' }) : undefined);
    function Parent() {
      const [events, setEvents] = useState<{ sequence: number; type: string; payload: { epoch: number; text: string } }[]>([]);
      return <RepositoryPanel {...props} session={session} speechEpoch={7} speechEvents={events} onSessionChange={() => setEvents([{ sequence: 1, type: 'coach.action', payload: { epoch: 7, text: 'Which files own this behavior?' } }])} />;
    }
    render(<Parent />);
    await screen.findByText(/Coverage: 50%/);
    fireEvent.click(screen.getByRole('button', { name: 'Enable coach speech' }));
    await screen.findByText(/Coach speech enabled/);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/speech/tts'))).toBe(true));
    expect(create).toHaveBeenCalledOnce();
  });

  it('notifies the shell after defense transitions so validated coach events can refresh', async () => {
    restore(); const refresh = vi.fn();
    render(<RepositoryPanel {...props} session={session} onSessionChange={refresh} />);
    await screen.findByText(/Coverage: 50%/);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    await selectCitation();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Cited responsibility.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit defense answer' }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  });
});

describe('voice-first learning workspace', () => {
  it('shows the real microphone for a session, one draft, and hides manual controls', async () => {
    await ready(true);
    expect(screen.getByRole('button', { name: 'Enable voice and talk' })).toBeTruthy();
    expect(screen.getByAltText('Your VIVA mentor')).toBeTruthy();
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    expect(screen.getByLabelText('Your explanation')).toBeTruthy();
    expect(screen.queryByLabelText('Topic')).toBeNull();
    expect(screen.queryByLabelText('Inferred rationale')).toBeNull();
    expect(recorder.start).not.toHaveBeenCalled();
    disclose('Advanced evidence tools');
    expect(screen.getByLabelText('Topic')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create evidence card' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save decision from selected evidence' })).toBeTruthy();
  });

  it('moves Gnani transcripts to the sole draft with the supplied auth and epoch, never autosubmitting', async () => {
    server(url => url.endsWith('/speech/stt') ? json({ epoch: 7, normalized_transcript: 'The queue separates request handling.' }) : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop and transcribe' }));
    await waitFor(() => expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('The queue separates request handling.'));
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/defense/answer'))).toBe(false);
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/speech/stt'))!;
    expect(JSON.parse(options.body).epoch).toBe(7);
    expect(options.headers.Authorization).toBe('Bearer session-private');
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
  });

  it('appends a late transcript to the latest typed draft rather than overwriting it', async () => {
    const pending = deferred(); server(url => url.endsWith('/speech/stt') ? pending.promise : undefined);
    await ready(true);
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Earlier draft.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop and transcribe' }));
    await screen.findByText('Transcribing with Gnani…');
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Newer typed draft.' } });
    await act(async () => pending.resolve(json({ epoch: 7, normalized_transcript: 'Spoken reasoning.' })));
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('Newer typed draft.\nSpoken reasoning.');
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/defense/answer'))).toBe(false);
  });

  it('cancels voice while hidden but retains the one draft and source selections', async () => {
    const view = await ready(true); await selectCitation();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Keep this reasoning.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    await screen.findByRole('button', { name: 'Stop and transcribe' });
    view.rerender(<RepositoryPanel {...props} session={session} speechEpoch={7} speechEvents={[]} active={false} />);
    await waitFor(() => expect(recorder.dispose).toHaveBeenCalled());
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('Keep this reasoning.');
    expect(screen.getByText('Selected source spans')).toBeTruthy();
    const mic = screen.getByRole('button', { name: 'Talk' }) as HTMLButtonElement;
    expect(mic.disabled).toBe(true);
    view.rerender(<RepositoryPanel {...props} session={session} speechEpoch={7} speechEvents={[]} active />);
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('Keep this reasoning.');
    expect((screen.getByLabelText('Use this citation') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('button', { name: 'Talk' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps legacy derive prompts available before a bound session', async () => {
    await ready();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Why is this queue separate?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Get mentor prompt' }));
    await screen.findByText('Separate observed code from hypotheses.');
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/defense'))!;
    expect(JSON.parse(options.body)).toEqual({ phase: 'derive', topic: 'Why is this queue separate?', citations: [], learner_alternative: null });
  });

  it('requires a selected source and explicit submit; sends answer claims separately from source excerpts', async () => {
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: map');
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'The queue separates request handling.' } });
    expect((screen.getByRole('button', { name: 'Submit defense answer' }) as HTMLButtonElement).disabled).toBe(true);
    await selectCitation();
    fireEvent.click(screen.getByRole('button', { name: 'Submit defense answer' }));
    await screen.findByText('Current stage: derive');
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/defense/answer'))!;
    const body = JSON.parse(options.body);
    expect(body.answer).toBe('The queue separates request handling.');
    expect(body.citations).toEqual([{ ...citation, text: undefined }]);
    expect(body.evidence_links[0]).toEqual({ kind: 'observed_code', claim: body.answer, citation: body.citations[0], excerpt: citation.text });
    expect(options.headers['X-Session-Token']).toBe(session.token);
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('');
  });

  it('shows only project defense reflect requirement fields and never guesses them from voice text', async () => {
    server(url => url.endsWith('/defense/start') ? json({ phase: 'reflect', mode: 'project_defense', history: [], synthesis: {} }) : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: reflect');
    expect(screen.queryByLabelText('Changed requirement')).toBeNull();
    disclose('Reflection details');
    expect(screen.getByLabelText('Changed requirement')).toBeTruthy();
    expect(screen.getByLabelText('Your alternative')).toBeTruthy();
    expect(screen.getByLabelText('Unknowns (optional)')).toBeTruthy();
    expect(screen.queryByLabelText('Topic')).toBeNull();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'I would use a durable queue.' } });
    await selectCitation();
    expect((screen.getByRole('button', { name: 'Submit defense answer' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Changed requirement'), { target: { value: 'Survive a process restart' } });
    fireEvent.change(screen.getByLabelText('Your alternative'), { target: { value: 'A durable queue' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit defense answer' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/defense/answer'))).toBe(true));
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/defense/answer'))!;
    expect(JSON.parse(options.body)).toMatchObject({ changed_requirement: 'Survive a process restart', learner_alternative: 'A durable queue' });
  });

  it('preserves an oversized transcript for editing instead of silently truncating it', async () => {
    const transcript = 'A'.repeat(4001);
    server(url => url.endsWith('/speech/stt') ? json({ epoch: 7, normalized_transcript: transcript }) : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: map');
    fireEvent.click(screen.getByRole('button', { name: 'Enable voice and talk' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop and transcribe' }));
    await screen.findByText(/Your transcript is preserved/);
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe(transcript);
    expect((screen.getByRole('button', { name: 'Submit defense answer' }) as HTMLButtonElement).disabled).toBe(true);
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/defense/answer'))).toBe(false);
  });

  it('validates optional reflection unknowns without changing learner reasoning', async () => {
    server(url => url.endsWith('/defense/start') ? json({ phase: 'reflect', mode: 'project_defense', history: [], synthesis: {} }) : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: reflect');
    disclose('Reflection details');
    fireEvent.change(screen.getByLabelText('Changed requirement'), { target: { value: 'Restart safely' } });
    fireEvent.change(screen.getByLabelText('Your alternative'), { target: { value: 'Durable queue' } });
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Try a durable queue.' } });
    await selectCitation();
    fireEvent.change(screen.getByLabelText('Unknowns (optional)'), { target: { value: Array.from({ length: 11 }, (_, index) => `Unknown ${index}`).join('\n') } });
    expect(screen.getByText(/Keep unknowns to ten lines/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Submit defense answer' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Unknowns (optional)'), { target: { value: ' Runtime throughput \n Failure recovery ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit defense answer' }));
    await screen.findByText('Current stage: derive');
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/defense/answer'))!;
    expect(JSON.parse(options.body).unknowns).toEqual(['Runtime throughput', 'Failure recovery']);
  });

  it('does not impose project reflect forms on legacy exploration', async () => {
    server(url => url.endsWith('/defense/start') ? json({ phase: 'reflect', mode: 'repo_exploration', history: [], synthesis: {} }) : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: reflect');
    expect(screen.queryByText('Reflection details')).toBeNull();
  });
});

describe('repository capability and generation boundaries', () => {
  it('preserves the snapshot and tab metadata when deletion is rejected as in use', async () => {
    server((_url, options) => options.method === 'DELETE' ? json({ detail: 'snapshot is in use' }, 409) : undefined);
    await ready();
    deleteSnapshot();
    await screen.findByRole('alert');
    expect(screen.getByText(/Coverage: 50%/)).toBeTruthy();
    expect(sessionStorage.getItem('viva-repo-tab-v1')).toContain('"snapshot_id":"s"');
    expect(props.onSnapshot).not.toHaveBeenCalledWith(null);
  });

  it('does not duplicate destructive requests while deletion is pending', async () => {
    const pending = deferred(); server((_url, options) => options.method === 'DELETE' ? pending.promise : undefined);
    await ready(); deleteSnapshot();
    fireEvent.click(screen.getByRole('button', { name: 'Delete snapshot' }));
    expect(fetcher.mock.calls.filter(([, options]) => options.method === 'DELETE')).toHaveLength(1);
    await act(async () => pending.resolve(new Response(null, { status: 204 })));
  });

  it('can retry failed automatic repository data loads from the disclosed tools', async () => {
    let mapCalls = 0;
    server(url => url.endsWith('/map') && ++mapCalls === 1 ? json({ detail: 'map unavailable' }, 503) : undefined);
    await ready();
    await screen.findByText('map unavailable');
    disclose('Snapshot tools');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh repository data' }));
    await screen.findByRole('button', { name: citation.path });
    expect(mapCalls).toBe(2);
  });

  it('requires deletion confirmation before sending DELETE', async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    await ready(); deleteSnapshot();
    expect(fetcher.mock.calls.some(([, options]) => options.method === 'DELETE')).toBe(false);
  });

  it.each(['map', 'search', 'files', 'evidence', 'defense/start', 'defense/answer'])('ignores late %s responses after deletion', async endpoint => {
    const pending = deferred(); let hold = false;
    server((url, options) => {
      const matches = endpoint === 'files' ? url.includes('/files?') : endpoint === 'search' ? url.includes('/search?') : url.endsWith(`/${endpoint}`);
      if (matches && (endpoint !== 'evidence' || options.method === 'POST') && (hold || endpoint === 'map')) return pending.promise;
      return undefined;
    });
    await ready(endpoint.startsWith('defense'));
    if (endpoint === 'search') {
      hold = true; disclose('Search source');
      fireEvent.change(screen.getByLabelText('Search code'), { target: { value: 'queue' } });
      fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    } else if (endpoint === 'files') {
      hold = true; fireEvent.click(screen.getByRole('button', { name: citation.path }));
    } else if (endpoint === 'evidence') {
      hold = true; disclose('Advanced evidence tools');
      fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Late evidence' } });
      fireEvent.click(screen.getByRole('button', { name: 'Create evidence card' }));
    } else if (endpoint === 'defense/start') {
      hold = true; fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    } else if (endpoint === 'defense/answer') {
      fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
      await screen.findByText('Current stage: map'); await selectCitation();
      fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'Late defense' } });
      hold = true; fireEvent.click(screen.getByRole('button', { name: 'Submit defense answer' }));
    }
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).includes(`/${endpoint}`))).toBe(true));
    deleteSnapshot();
    await waitFor(() => expect(props.onSnapshot).toHaveBeenCalledWith(null));
    await act(async () => pending.resolve(json(endpoint === 'map' ? { files: [{ path: 'late.ts' }] } : endpoint === 'search' ? { results: [{ ...citation, text: 'Late source' }] } : endpoint === 'files' ? { path: 'late.ts', content: 'Late source' } : endpoint === 'evidence' ? { ...card, topic: 'Late evidence' } : { phase: 'reflect', history: [], synthesis: {} })));
    expect(screen.queryByText('Late source')).toBeNull();
    expect(screen.queryByRole('button', { name: 'late.ts' })).toBeNull();
    expect(screen.queryByText('Late evidence')).toBeNull();
    expect(screen.queryByText('Current stage: reflect')).toBeNull();
    expect(sessionStorage.getItem('viva-repo-tab-v1')).toBeNull();
  });

  it('ignores a defense response from a replaced session capability', async () => {
    const pending = deferred(); server(url => url.endsWith('/defense/start') ? pending.promise : undefined);
    const view = await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    view.rerender(<RepositoryPanel {...props} session={{ ...session, token: 'rotated-private' }} speechEpoch={8} speechEvents={[]} />);
    await act(async () => pending.resolve(json({ phase: 'derive', history: [], synthesis: {} })));
    expect(screen.queryByText('Current stage: derive')).toBeNull();
    expect((screen.getByLabelText('Your explanation') as HTMLTextAreaElement).value).toBe('');
  });

  it('guards against duplicate submissions while a defense answer is pending', async () => {
    const pending = deferred(); server(url => url.endsWith('/defense/answer') ? pending.promise : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Current stage: map'); await selectCitation();
    fireEvent.change(screen.getByLabelText('Your explanation'), { target: { value: 'The queue separates responsibilities.' } });
    const submit = screen.getByRole('button', { name: 'Submit defense answer' });
    fireEvent.click(submit); fireEvent.click(submit);
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/defense/answer'))).toHaveLength(1);
    await act(async () => pending.resolve(json({ phase: 'derive', history: [], synthesis: {} })));
  });

  it('creates a manual evidence card with code and exact documentation kept separate', async () => {
    const doc = { ...citation, path: 'README.md', symbol: '', text: 'Documented queue behavior.' };
    server(url => url.includes('/search?') ? json({ results: [citation, doc] }) : undefined);
    await ready();
    disclose('Search source');
    fireEvent.change(screen.getByLabelText('Search code'), { target: { value: 'queue' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText(doc.text);
    screen.getAllByLabelText('Use this citation').forEach(input => fireEvent.click(input));
    disclose('Advanced evidence tools');
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Queue boundary' } });
    fireEvent.change(screen.getByLabelText('Inferred rationale'), { target: { value: 'Could isolate failures.' } });
    fireEvent.change(screen.getByLabelText('Your alternative'), { target: { value: 'A durable stream.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create evidence card' }));
    await screen.findByText('Inference does not establish author intent.');
    const [, options] = fetcher.mock.calls.find(([url, options]) => String(url).endsWith('/evidence') && options.method === 'POST')!;
    expect(JSON.parse(options.body)).toEqual({ topic: 'Queue boundary', observed_code: [{ ...citation, text: undefined }], explicit_docs: [{ ...doc, text: undefined, excerpt: doc.text }], inferred_rationale: ['Could isolate failures.'], learner_alternative: 'A durable stream.' });
  });

  it('saves a decision from a selected saved card and retrieves its record', async () => {
    server((url, options) => url.endsWith('/decisions') && options.method === 'GET' ? json({ decisions: [{ topic: 'Saved queue decision', inferred_rationale: 'Isolation hypothesis', learner_alternative: 'Stream', uncertainty: 'Unknown intent' }] }) : undefined);
    await ready(); disclose('Advanced evidence tools');
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Queue decision' } });
    fireEvent.change(screen.getByLabelText('Inferred rationale'), { target: { value: 'Isolation hypothesis' } });
    fireEvent.change(screen.getByLabelText('Your alternative'), { target: { value: 'Stream' } });
    fireEvent.click(screen.getByLabelText('Queue boundary — use in a decision'));
    fireEvent.click(screen.getByRole('button', { name: 'Save decision from selected evidence' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url, options]) => String(url).endsWith('/decisions') && options.method === 'GET')).toBe(true));
    const [, options] = fetcher.mock.calls.find(([url, options]) => String(url).endsWith('/decisions') && options.method === 'POST')!;
    expect(JSON.parse(options.body)).toEqual({ topic: 'Queue decision', evidence_card_ids: ['card-1'], inferred_rationale: 'Isolation hypothesis', learner_alternative: 'Stream' });
    disclose('Saved evidence and decisions');
    await screen.findByText('Saved queue decision');
  });

  it('keeps all legacy manual prompt phases reachable without grading', async () => {
    await ready(); disclose('Advanced evidence tools');
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Request lifecycle' } });
    fireEvent.change(screen.getByLabelText('Your alternative'), { target: { value: 'Another queue' } });
    fireEvent.change(screen.getByLabelText('Defense stage'), { target: { value: 'reflect' } });
    fireEvent.click(screen.getByRole('button', { name: 'Get defense prompt' }));
    await screen.findAllByText('Separate observed code from hypotheses.');
    const [, options] = fetcher.mock.calls.find(([url]) => String(url).endsWith('/defense'))!;
    expect(JSON.parse(options.body)).toEqual({ phase: 'reflect', topic: 'Request lifecycle', citations: [], learner_alternative: 'Another queue' });
  });

  it('opens numbered source and lets learners remove a selected citation', async () => {
    await ready(); await selectCitation();
    fireEvent.click(screen.getByRole('button', { name: citation.path }));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Open source file' }).textContent).toContain('1  export function'));
    fireEvent.click(screen.getByRole('button', { name: `Remove citation ${citation.path}:1` }));
    expect(screen.queryByText('Selected source spans')).toBeNull();
    expect((screen.getByLabelText('Use this citation') as HTMLInputElement).checked).toBe(false);
  });

  it('exports source learning data but never workspace or session capability tokens', async () => {
    let exported!: Blob;
    const create = vi.fn((blob: Blob) => { exported = blob; return 'blob:repo-record'; });
    const revoke = vi.fn();
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
    const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    await ready(true); disclose('Snapshot tools');
    fireEvent.click(screen.getByRole('button', { name: 'Export learning record' }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    const text = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(exported); });
    expect(JSON.parse(text).snapshot.snapshot_id).toBe('s');
    expect(text).toContain('Queue boundary');
    expect(text).not.toContain(workspace.token);
    expect(text).not.toContain(session.token);
    expect(download).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith('blob:repo-record');
  });

  it('renders complete defense history and leaves the voice control visible but disabled', async () => {
    server(url => url.endsWith('/defense/start') ? json({ phase: 'complete', history: [{ phase: 'reflect', answer: 'Use a durable queue.', citations: [citation], changed_requirement: 'Restart safely', learner_alternative: 'Durable queue', unknowns: ['Runtime throughput'] }], synthesis: { basis: 'Learner statements, not truth grading.' } }) : undefined);
    await ready(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start or resume defense' }));
    await screen.findByText('Defense completed. Review the cited history below.');
    expect(screen.queryByLabelText('Your explanation')).toBeNull();
    expect((screen.getByRole('button', { name: 'Enable voice and talk' }) as HTMLButtonElement).disabled).toBe(true);
    disclose('Defense history');
    expect(screen.getByText('Restart safely')).toBeTruthy();
    expect(screen.getByText('Durable queue')).toBeTruthy();
    expect(screen.getByText('Runtime throughput')).toBeTruthy();
  });

  it('fences an in-flight source request when the workspace changes', async () => {
    const pending = deferred(); server(url => url.includes('/search?') ? pending.promise : undefined);
    const view = await ready(); disclose('Search source');
    fireEvent.change(screen.getByLabelText('Search code'), { target: { value: 'queue' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    view.rerender(<RepositoryPanel {...props} workspace={{ id: 'other', token: 'other-private' }} />);
    await act(async () => pending.resolve(json({ results: [{ ...citation, text: 'Old workspace source' }] })));
    expect(screen.queryByText('Old workspace source')).toBeNull();
    expect(screen.queryByText(/Coverage: 50%/)).toBeNull();
    expect(props.onSnapshot).toHaveBeenCalledWith(null);
  });

  it('ignores invalid metadata and reports import failures without false READY notifications', async () => {
    sessionStorage.setItem('viva-repo-tab-v1', '{broken');
    server(url => url.endsWith('/ingest') ? json({ detail: 'repository import rejected' }, 422) : undefined);
    render(<RepositoryPanel {...props} />);
    await screen.findByText(/Invalid repository tab metadata/);
    fireEvent.click(screen.getByRole('tab', { name: 'Curated example' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import and index' }));
    await screen.findByText('repository import rejected');
    expect(props.onSnapshot).not.toHaveBeenCalledWith('s');
  });

  it('keeps manual decisions, source history, and export reachable through disclosures', async () => {
    await ready();
    await act(async () => disclose('Saved evidence and decisions'));
    const saved = screen.getByRole('group', { name: 'Saved evidence and decisions' });
    expect(within(saved).getByText('Queue boundary')).toBeTruthy();
    disclose('Snapshot tools');
    expect(screen.getByRole('button', { name: 'Export learning record' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Delete snapshot' })).toBeTruthy();
  });
});
