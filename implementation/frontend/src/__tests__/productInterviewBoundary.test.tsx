import { afterEach, describe, expect, it, vi } from 'vitest';
import { createInterviewApi } from '../features/interview/api';
import { parseCatalog, parseConfig, parseReport, parseSession } from '../features/interview/validation';

const config = { types: ['dsa', 'cs', 'system_design', 'codebase_defense'], difficulties: ['beginner', 'intermediate', 'advanced'], duration_minutes: { minimum: 5, maximum: 60, default: 15 }, language_modes: ['en-IN', 'ta-IN,en-IN'], camera_default: false };
const catalog = { topics: { dsa: ['binary-search'], cs: ['databases'], system_design: ['capacity'], codebase_defense: ['ownership'] }, dsa_exercises: [{ exercise_id: 'ex2_binary_search', title: 'Lower bound', description: 'Find the first qualifying index.', difficulty: 'beginner', spec_version: 'v1', topics: ['binary-search'] }] };
const report = { session_id: 's1', completion_reason: 'finished', completed_at: '2026-11-15', answered_count: 1, semantic_validity: { status: 'unassessed', reason: 'Not graded.' }, technical_correctness: { status: 'unassessed_no_execution_evidence', reason: 'Code not run.' }, psychology: { status: 'not_assessed', reason: 'Never inferred.' }, answers: [{ question_id: 'q1', question: 'Explain.', answer: '🙂 because', code: 'pass', indicators: [{ id: 'reasoning_marker', label: 'Reasoning marker', value: 1, maximum: 1, status: 'observed_text_only', semantic_validity: 'unassessed', excerpts: [{ start: 2, end: 9, text: 'because' }] }] }], recommendations: [{ exercise_id: 'ex2_binary_search', spec_version: 'v1', lesson_id: null, reason: 'Practice.', missing_indicators: [] }], limitations: ['Text only.'] };
const session = { id: 's1', type: 'dsa', difficulty: 'beginner', topics: [], duration_minutes: 15, language_mode: 'en-IN', epoch: 1, state: 'active', started_at: '2026-11-15T10:00:00+00:00', deadline_at: '2026-11-15T10:15:00+00:00', introduction: { text: 'Welcome.', source_refs: [] }, acknowledgement: null, question: { id: 'q1', text: 'Explain.', kind: 'primary', parent_id: null, source_refs: [{ source: 'exercise_catalog', exercise_id: 'ex2_binary_search', spec_version: 'v1' }] }, report: null };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('interview transport and external data boundary', () => {
  it('uses existing workspace headers for every endpoint and sends no arbitrary owner body', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(config))).mockResolvedValueOnce(new Response(JSON.stringify(catalog))).mockResolvedValueOnce(new Response(JSON.stringify(session))).mockResolvedValueOnce(new Response(JSON.stringify(session))).mockResolvedValueOnce(new Response(JSON.stringify({ ...session, epoch: 2, acknowledgement: { text: 'Answer recorded.', source_refs: [] } }))).mockResolvedValueOnce(new Response(JSON.stringify(report)));
    vi.stubGlobal('fetch', fetcher);
    const api = createInterviewApi({ id: 'workspace', token: 'workspace-secret' });
    await api.getConfig(); await api.getCatalog(); await api.createSession({ type: 'dsa', difficulty: 'beginner', topics: [], duration_minutes: 15, language_mode: 'en-IN' }); await api.getSession('s1'); await api.answer('s1', { expected_epoch: 1, answer: '🙂 because' }); await api.finish('s1', 2);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v1/interviews/config', '/api/v1/interviews/catalog', '/api/v1/interviews/sessions', '/api/v1/interviews/sessions/s1', '/api/v1/interviews/sessions/s1/answers', '/api/v1/interviews/sessions/s1/finish']);
    for (const [, options] of fetcher.mock.calls) { expect(options.headers['X-Workspace-Id']).toBe('workspace'); expect(options.headers['X-Workspace-Token']).toBe('workspace-secret'); expect(options.body ?? '').not.toContain('user_id'); }
  });
  it('reads a completed report through the dedicated report endpoint without loading the session', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(report)));
    vi.stubGlobal('fetch', fetcher);
    const api = createInterviewApi({ id: 'workspace', token: 'fixture-capability' });
    const id = 'report/প্রতিবেদন?A';
    expect(await api.getReport(id)).toEqual(report);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(`/api/v1/interviews/reports/${encodeURIComponent(id)}`, expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-Workspace-Id': 'workspace', 'X-Workspace-Token': 'fixture-capability' }) }));
  });
  it.each([null, [], {}, session, { ...report, psychology: { status: 'confident', reason: 'Invented assessment.' } }])('rejects invalid report-only endpoint data %j', async value => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value)));
    vi.stubGlobal('fetch', fetcher);
    await expect(createInterviewApi({ id: 'workspace', token: 'fixture-capability' }).getReport('s1')).rejects.toThrow('invalid response');
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v1/interviews/reports/s1']);
  });
  it('does not fall back to the auto-expiring session endpoint when a report is unavailable', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Report unavailable' }), { status: 404 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(createInterviewApi({ id: 'workspace', token: 'fixture-capability' }).getReport('active')).rejects.toThrow('Report unavailable');
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v1/interviews/reports/active']);
  });
  it.each(['hi-IN', 'bn-IN', 'hi-IN,en-IN', 'bn-IN,en-IN'])('accepts canonical interview locale %s at the response boundary', language => {
    expect(parseConfig({ ...config, language_modes: [language] }).language_modes).toEqual([language]);
    expect(parseSession({ ...session, language_mode: language }).language_mode).toBe(language);
  });
  it.each(['fr-FR', 'te-IN,en-IN', 'ta-IN,hi-IN'])('rejects unsupported interview locale %s at the response boundary', language => {
    expect(() => parseConfig({ ...config, language_modes: [language] })).toThrow();
    expect(() => parseSession({ ...session, language_mode: language })).toThrow();
  });
  it('rejects invented correctness and psychological verdicts even in a server response', () => {
    expect(() => parseReport({ ...report, technical_correctness: { status: 'correct', reason: 'A model said so.' } })).toThrow();
    expect(() => parseReport({ ...report, psychology: { status: 'confident', reason: 'Camera appearance.' } })).toThrow();
  });
  it('validates exact codepoint excerpts including emoji and rejects unanchored or empty excerpts', () => {
    expect(parseReport(report).answers[0].indicators[0].excerpts[0].text).toBe('because');
    const changed = (excerpt: object) => ({ ...report, answers: [{ ...report.answers[0], indicators: [{ ...report.answers[0].indicators[0], excerpts: [excerpt] }] }] });
    expect(() => parseReport(changed({ start: 0, end: 7, text: 'because' }))).toThrow();
    expect(() => parseReport(changed({ start: 200, end: 201, text: '' }))).toThrow();
  });
  it.each([null, [], {}, { ...config, camera_default: true }, { ...config, types: ['unknown'] }, { ...config, duration_minutes: { minimum: 0, maximum: 1000, default: 15 } }])('rejects invalid setup response %j', value => { expect(() => parseConfig(value)).toThrow(); });
  it.each([{ ...session, state: 'completed' }, { ...session, epoch: 0 }, { ...session, duration_minutes: 100 }, { ...session, deadline_at: 'invalid' }, { ...session, question: null }, { ...session, language_mode: 'unrecognized' }])('rejects invalid session response %j', value => { expect(() => parseSession(value)).toThrow(); });
  it('validates completed sessions and catalog metadata without accepting missing topics', () => {
    expect(parseSession({ ...session, state: 'completed', epoch: 2, question: null, report }).report?.session_id).toBe('s1');
    expect(parseCatalog(catalog).dsa_exercises[0].exercise_id).toBe('ex2_binary_search');
    expect(() => parseCatalog({ ...catalog, topics: { dsa: [] } })).toThrow();
  });
  it('propagates API failure without substituting a fake session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Epoch conflict' }), { status: 409 })));
    await expect(createInterviewApi({ id: 'w', token: 't' }).answer('s1', { expected_epoch: 1, answer: 'text' })).rejects.toThrow('Epoch conflict');
  });
});
