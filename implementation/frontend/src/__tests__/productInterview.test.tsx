import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InterviewPage } from '../features/interview/InterviewPage';
import type { InterviewApi, InterviewReport, InterviewSession } from '../features/interview/types';
import { SPEECH_LANGUAGES, CODE_MIXING_LANGUAGES, resolveLanguageMode } from '../voice/languages';
import { loadSpeechPreferences, saveSpeechPreferences } from '../voice/preferences';

const workspace = { id: 'workspace', token: 'secret' };
const question = { id: 'q1', text: 'Explain your approach.', kind: 'primary' as const, parent_id: null, source_refs: [{ source: 'exercise_catalog', exercise_id: 'ex2_binary_search', spec_version: 'v1' }] };
const session: InterviewSession = { id: 'session', type: 'dsa', difficulty: 'beginner', topics: [], duration_minutes: 15, language_mode: 'en-IN', epoch: 1, state: 'active', deadline_at: '2099-01-01T00:00:00+00:00', started_at: '2026-01-01T00:00:00+00:00', question, introduction: { text: 'One question at a time. Feedback after finishing.', source_refs: [] }, acknowledgement: null, report: null };
const report: InterviewReport = { session_id: 'session', completion_reason: 'finished', completed_at: '2026-01-01', answered_count: 1, semantic_validity: { status: 'unassessed', reason: 'No semantic grader.' }, technical_correctness: { status: 'unassessed_no_execution_evidence', reason: 'No server execution evidence.' }, psychology: { status: 'not_assessed', reason: 'No psychological inference.' }, answers: [{ question_id: 'q1', question: question.text, answer: 'because I scan', code: null, indicators: [{ id: 'reasoning_marker', label: 'Reasoning marker mentioned', value: 1, maximum: 1, status: 'observed_text_only', excerpts: [{ start: 0, end: 7, text: 'because' }], semantic_validity: 'unassessed' }] }], recommendations: [{ exercise_id: 'ex2_binary_search', spec_version: 'v1', lesson_id: null, reason: 'Practice boundaries.', missing_indicators: [] }], limitations: ['Keyword presence does not establish correctness.'] };
function api(): InterviewApi {
  return { getConfig: vi.fn().mockResolvedValue({ types: ['dsa', 'cs', 'system_design', 'codebase_defense'], difficulties: ['beginner', 'intermediate', 'advanced'], duration_minutes: { minimum: 5, maximum: 60, default: 15 }, language_modes: [...SPEECH_LANGUAGES.map(l => l.code), ...CODE_MIXING_LANGUAGES.map(code => resolveLanguageMode(code, true))], camera_default: false }), getCatalog: vi.fn().mockResolvedValue({ topics: { dsa: ['binary-search'], cs: ['operating-systems'], system_design: ['capacity'], codebase_defense: ['ownership'] }, dsa_exercises: [] }), createSession: vi.fn().mockResolvedValue(session), getSession: vi.fn().mockResolvedValue(session), answer: vi.fn().mockResolvedValue({ ...session, epoch: 2, acknowledgement: { text: 'Answer recorded.', source_refs: [] }, question: { ...question, id: 'q2', text: 'What reasoning supports your choice?', kind: 'followup', parent_id: 'q1' } }), finish: vi.fn().mockResolvedValue(report) };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); localStorage.clear(); });
async function start(helper: InterviewApi) {
  render(<InterviewPage api={helper} workspace={workspace} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Start interview' }));
  await screen.findByText(question.text);
}
describe('interview assessment flow', () => {
  it('blocks new creation until deferred resume settles, then keeps the new session ID and question stable', async () => {
    sessionStorage.setItem('viva-interview:workspace', 'old-session');
    let resolveResume!: (value: InterviewSession) => void;
    const helper = api();
    vi.mocked(helper.getSession).mockImplementationOnce(() => new Promise<InterviewSession>(resolve => { resolveResume = resolve; }));
    const next = { ...session, id: 'new-session', question: { ...question, id: 'new-question', text: 'New session question.' } };
    vi.mocked(helper.createSession).mockResolvedValue(next);
    render(<InterviewPage api={helper} workspace={workspace} />);
    await waitFor(() => expect(helper.getSession).toHaveBeenCalledWith('old-session'));
    const startPending = screen.getByRole('button', { name: /^(Start interview|Starting…)$/ });
    expect(startPending).toBeDisabled();
    fireEvent.click(startPending);
    expect(helper.createSession).not.toHaveBeenCalled();
    await act(async () => resolveResume({ ...session, id: 'old-session', state: 'completed', epoch: 2, question: null, report: { ...report, session_id: 'old-session' } }));
    fireEvent.click(await screen.findByRole('button', { name: 'Start another interview' }));
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    await screen.findByText('New session question.');
    expect(sessionStorage.getItem('viva-interview:workspace')).toBe('new-session');
    expect(screen.queryByText(question.text)).not.toBeInTheDocument();
  });
  it('ignores a deferred old-session reload after another interview has started', async () => {
    const helper = api(); await start(helper);
    let resolveReload!: (value: InterviewSession) => void;
    vi.mocked(helper.getSession).mockImplementationOnce(() => new Promise<InterviewSession>(resolve => { resolveReload = resolve; }));
    fireEvent.click(screen.getByRole('button', { name: 'Reload session' }));
    await waitFor(() => expect(helper.getSession).toHaveBeenCalledWith('session'));
    fireEvent.click(screen.getByRole('button', { name: 'Finish interview' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Start another interview' }));
    vi.mocked(helper.createSession).mockResolvedValue({ ...session, id: 'new-session', question: { ...question, id: 'new-question', text: 'New session question.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    await screen.findByText('New session question.');
    await act(async () => resolveReload(session));
    expect(screen.getByText('New session question.')).toBeInTheDocument();
    expect(sessionStorage.getItem('viva-interview:workspace')).toBe('new-session');
    expect(screen.queryByText(question.text)).not.toBeInTheDocument();
  });
  it('initializes from shared speech preferences and exposes all canonical native locale choices', async () => {
    saveSpeechPreferences({ ...loadSpeechPreferences(), sttLanguage: 'hi-IN', spokenLanguage: 'hi-IN', codeMixing: true, voice: 'Lakshmi' });
    render(<InterviewPage api={api()} workspace={workspace} />);
    expect(await screen.findByLabelText('Language preference')).toHaveValue('hi-IN,en-IN');
    expect(screen.getAllByRole('option').filter(option => option.parentElement === screen.getByLabelText('Language preference'))).toHaveLength(13);
    expect(screen.getByRole('option', { name: /^Hindi · हिन्दी$/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /^Bengali · বাংলা$/ })).toBeInTheDocument();
    expect(screen.getByText(/Question text is currently English/)).toBeInTheDocument();
  });
  it.each(['hi-IN', 'bn-IN', 'hi-IN,en-IN', 'bn-IN,en-IN'] as const)('persists %s to shared STT/TTS preferences and outbound session without changing voice', async language => {
    saveSpeechPreferences({ ...loadSpeechPreferences(), voice: 'Lakshmi' });
    const helper = api(); render(<InterviewPage api={helper} workspace={workspace} />);
    fireEvent.change(await screen.findByLabelText('Language preference'), { target: { value: language } });
    const locale = language.startsWith('hi-IN') ? 'hi-IN' : 'bn-IN';
    expect(loadSpeechPreferences()).toEqual(expect.objectContaining({ sttLanguage: locale, spokenLanguage: locale, codeMixing: language.includes(','), voice: 'Lakshmi' }));
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    await screen.findByText(question.text);
    expect(helper.createSession).toHaveBeenCalledWith(expect.objectContaining({ language_mode: language }));
  });
  it('resumes a durable session after remount and can start another after finishing', async () => {
    sessionStorage.clear();
    const helper = api(); await start(helper);
    cleanup();
    render(<InterviewPage api={helper} workspace={workspace} />);
    await waitFor(() => expect(helper.getSession).toHaveBeenCalledWith('session'));
    await screen.findByText(question.text);
    fireEvent.click(screen.getByRole('button', { name: 'Finish interview' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Start another interview' }));
    await screen.findByRole('button', { name: 'Start interview' });
    expect(screen.queryByRole('heading', { name: 'Interview report' })).not.toBeInTheDocument();
  });
  it('allows distinct configurations and does not auto-submit a voice transcript', async () => {
    sessionStorage.clear();
    const helper = api(); const onMessage = vi.fn();
    render(<InterviewPage api={helper} workspace={workspace} onMessage={onMessage} renderVoice={context => <button type="button" onClick={() => context.onTranscript('spoken draft')}>Dictate test</button>} />);
    fireEvent.change(await screen.findByLabelText('Interview type'), { target: { value: 'system_design' } });
    fireEvent.change(screen.getByLabelText('Difficulty'), { target: { value: 'advanced' } });
    fireEvent.change(screen.getByLabelText('Duration in minutes'), { target: { value: '30' } });
    fireEvent.change(screen.getByLabelText('Language preference'), { target: { value: 'ta-IN,en-IN' } });
    fireEvent.click(screen.getByLabelText('capacity'));
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Dictate test' }));
    expect(screen.getByLabelText('Your answer')).toHaveValue('spoken draft');
    expect(helper.answer).not.toHaveBeenCalled();
    expect(helper.createSession).toHaveBeenCalledWith({ type: 'system_design', difficulty: 'advanced', duration_minutes: 30, language_mode: 'ta-IN,en-IN', topics: ['capacity'] });
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ id: 'q1', kind: 'question', text: question.text }));
  });
  it('camera denial leaves the typed interview usable and turning preview off stops tracks', async () => {
    sessionStorage.clear();
    const stop = vi.fn(); const media = vi.fn().mockRejectedValueOnce(new Error('permission denied')).mockResolvedValueOnce({ getTracks: () => [{ stop }] });
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: media } });
    const helper = api(); await start(helper);
    fireEvent.click(screen.getByRole('button', { name: 'Enable local camera preview' }));
    await screen.findByText('permission denied');
    expect(screen.getByLabelText('Your answer')).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Enable local camera preview' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Turn camera off' }));
    expect(stop).toHaveBeenCalled();
  });
  it('allows a fresh interview when a saved session can no longer be resumed', async () => {
    sessionStorage.setItem('viva-interview:workspace', 'gone');
    const helper = api(); vi.mocked(helper.getSession).mockRejectedValue(new Error('Interview session not found'));
    render(<InterviewPage api={helper} workspace={workspace} />);
    await screen.findByRole('alert');
    expect(await screen.findByRole('button', { name: 'Start interview' })).toBeEnabled();
  });
  it('renders an empty completed report without fabricating recommendations or camera access', async () => {
    const helper = api(); vi.mocked(helper.getSession).mockResolvedValue({ ...session, state: 'completed', epoch: 2, question: null, report: { ...report, answers: [], recommendations: [], answered_count: 0 } });
    render(<InterviewPage api={helper} workspace={workspace} initialSessionId="session" />);
    await screen.findByText('No answers were submitted before the interview ended.');
    expect(screen.getByText(/No catalog-backed lesson mapping/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enable local camera preview' })).not.toBeInTheDocument();
  });
  it('includes code only when explicitly entered and provides a recommendation hook', async () => {
    const helper = api(); const recommendation = vi.fn(); const onMessage = vi.fn();
    render(<InterviewPage api={helper} workspace={workspace} onRecommendation={recommendation} onMessage={onMessage} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Start interview' }));
    await screen.findByText(question.text);
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'because I scan' } });
    fireEvent.change(screen.getByLabelText('Your code'), { target: { value: 'return 0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));
    await screen.findByText('Answer recorded.');
    expect(helper.answer).toHaveBeenCalledWith('session', { expected_epoch: 1, answer: 'because I scan', code: 'return 0' });
    fireEvent.click(screen.getByRole('button', { name: 'Finish interview' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open recommended practice' }));
    expect(recommendation).toHaveBeenCalledWith(report.recommendations[0]);
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ kind: 'end', epoch: 3 }));
  });
  it('works without tab storage or a camera API', async () => {
    const helper = api(); vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage disabled'); });
    vi.stubGlobal('navigator', {});
    render(<InterviewPage api={helper} workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Enable local camera preview' }));
    await screen.findByText(/Camera preview is unavailable/);
    expect(screen.getByRole('button', { name: 'Start interview' })).toBeEnabled();
    expect(screen.getByText(/Tab storage is unavailable/)).toBeInTheDocument();
  });
  it('cancels a pending camera request and stops the eventual stream', async () => {
    let resolve!: (stream: MediaStream) => void; const stop = vi.fn();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => new Promise<MediaStream>(r => { resolve = r; })) } });
    render(<InterviewPage api={api()} workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Enable local camera preview' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel camera request' }));
    await act(async () => resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream));
    expect(stop).toHaveBeenCalled();
    expect(screen.getByText('Camera off')).toBeInTheDocument();
  });
  it('starts without requesting camera or credentials and submits selected configuration', async () => {
    const media = vi.fn(); vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: media } });
    const helper = api(); await start(helper);
    expect(media).not.toHaveBeenCalled();
    expect(helper.createSession).toHaveBeenCalledWith({ type: 'dsa', difficulty: 'beginner', topics: [], duration_minutes: 15, language_mode: 'en-IN' });
    expect(screen.queryByText('correct')).not.toBeInTheDocument();
  });
  it('records only current epoch answers and shows report only after finishing', async () => {
    const helper = api(); await start(helper);
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'because I scan' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));
    await screen.findByText('Answer recorded.');
    expect(helper.answer).toHaveBeenCalledWith('session', { expected_epoch: 1, answer: 'because I scan', code: undefined });
    expect(screen.queryByRole('heading', { name: 'Interview report' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Finish interview' }));
    await screen.findByRole('heading', { name: 'Interview report' });
    expect(helper.finish).toHaveBeenCalledWith('session', 2);
    expect(screen.getByText('unassessed_no_execution_evidence')).toBeInTheDocument();
    expect(screen.getByText('because')).toBeInTheDocument();
  });
  it('retains an answer after error and explicitly reloads a conflicted epoch', async () => {
    const helper = api(); vi.mocked(helper.answer).mockRejectedValueOnce(new Error('Epoch conflict. Reload the session.'));
    await start(helper);
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: 'draft retained' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Your answer')).toHaveValue('draft retained');
    fireEvent.click(screen.getByRole('button', { name: 'Reload session' }));
    await waitFor(() => expect(helper.getSession).toHaveBeenCalledWith('session'));
  });
  it('supports recovery from configuration failure', async () => {
    const helper = api(); vi.mocked(helper.getConfig).mockRejectedValueOnce(new Error('offline'));
    render(<InterviewPage api={helper} workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry setup' }));
    await screen.findByRole('button', { name: 'Start interview' });
  });
  it('requests a local preview only after permission and stops tracks on unmount', async () => {
    const stop = vi.fn(); const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] });
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    const helper = api(); const { unmount } = render(<InterviewPage api={helper} workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Enable local camera preview' }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ video: true, audio: false }));
    await screen.findByRole('button', { name: 'Turn camera off' });
    unmount(); expect(stop).toHaveBeenCalled();
  });
  it('cleans a pending camera permission stream if the page leaves first', async () => {
    const stop = vi.fn(); let resolve!: (stream: MediaStream) => void;
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => new Promise<MediaStream>(r => { resolve = r; })) } });
    const helper = api(); const { unmount } = render(<InterviewPage api={helper} workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Enable local camera preview' }));
    unmount();
    await act(async () => resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream));
    expect(stop).toHaveBeenCalled();
  });
});
