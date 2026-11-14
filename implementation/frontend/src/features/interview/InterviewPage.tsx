import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createInterviewApi } from './api';
import { CameraPreview } from './CameraPreview';
import { InterviewReportView } from './InterviewReportView';
import { InterviewSetup, TYPE_LABELS } from './InterviewSetup';
import type { InterviewApi, InterviewCatalog, InterviewConfig, InterviewConfiguration, InterviewSession, Recommendation, VoiceMessage, Workspace } from './types';
import './interview.css';

export interface InterviewVoiceContext { sessionId: string; epoch: number; messageId: string; onTranscript: (text: string) => void }
export type InterviewPageProps = {
  workspace: Workspace; api?: InterviewApi; initialSessionId?: string;
  onMessage?: (message: VoiceMessage) => void;
  onRecommendation?: (recommendation: Recommendation) => void;
  renderVoice?: (context: InterviewVoiceContext) => ReactNode;
};

/** Optional provider-neutral voice slot. Text-only interviewing needs no credentials. */
export function InterviewPage({ workspace, api, initialSessionId, onMessage, onRecommendation, renderVoice }: InterviewPageProps): JSX.Element {
  const helper = useMemo(() => api ?? createInterviewApi({ id: workspace.id, token: workspace.token }), [api, workspace.id, workspace.token]);
  const [setup, setSetup] = useState<{ config: InterviewConfig; catalog: InterviewCatalog } | null>(null);
  const [session, setSession] = useState<InterviewSession | null>(null);
  const [answer, setAnswer] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const mounted = useRef(false);
  const locked = useRef(false);
  const emitted = useRef(new Set<string>());
  const questionHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const [config, catalog] = await Promise.all([helper.getConfig(), helper.getCatalog()]);
        const resumed = initialSessionId ? await helper.getSession(initialSessionId) : null;
        if (cancelled) return;
        setSetup({ config, catalog }); setSession(resumed); setError('');
      } catch (error) { if (!cancelled) setError(error instanceof Error ? error.message : 'Interview setup unavailable.'); }
    };
    void load();
    return () => { cancelled = true; mounted.current = false; };
  }, [helper, initialSessionId, retry]);
  const reload = useCallback(async (): Promise<void> => {
    if (!session) return;
    try { const next = await helper.getSession(session.id); if (mounted.current) { setSession(next); setError(''); } }
    catch (error) { if (mounted.current) setError(error instanceof Error ? error.message : 'Unable to reload the interview.'); }
  }, [helper, session]);
  useEffect(() => {
    if (!session || session.state !== 'active') return;
    const tick = window.setInterval(() => setClock(Date.now()), 1000);
    const refresh = window.setInterval(() => { if (!locked.current) void reload(); }, 15000);
    return () => { window.clearInterval(tick); window.clearInterval(refresh); };
  }, [session, reload]);
  useEffect(() => {
    if (!session || !onMessage) return;
    const messages: VoiceMessage[] = [{ ...session.introduction, id: `${session.id}:intro`, session_id: session.id, epoch: session.epoch, kind: 'introduction' }];
    if (session.acknowledgement) messages.push({ ...session.acknowledgement, id: `${session.id}:ack:${session.epoch}`, session_id: session.id, epoch: session.epoch, kind: 'acknowledgement' });
    if (session.question) messages.push({ ...session.question, session_id: session.id, epoch: session.epoch, kind: 'question' });
    if (session.report) messages.push({ id: `${session.id}:end`, text: 'The interview has ended. Your report is ready. Its observations are evidence-limited, not correctness or mastery judgments.', source_refs: [], session_id: session.id, epoch: session.epoch, kind: 'end' });
    for (const message of messages) if (!emitted.current.has(message.id)) { emitted.current.add(message.id); onMessage(message); }
  }, [session, onMessage]);
  useEffect(() => { questionHeading.current?.focus(); }, [session?.question?.id]);
  async function perform(operation: () => Promise<void>): Promise<void> {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError('');
    try { await operation(); }
    catch (error) { if (mounted.current) setError(error instanceof Error ? error.message : 'Interview request failed.'); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  function start(config: InterviewConfiguration): void {
    void perform(async () => { const next = await helper.createSession(config); if (mounted.current) { setSession(next); setClock(Date.now()); } });
  }
  function submit(): void {
    if (!session || !answer.trim()) return;
    void perform(async () => {
      const next = await helper.answer(session.id, { expected_epoch: session.epoch, answer, code: code || undefined });
      if (mounted.current) { setSession(next); setAnswer(''); setCode(''); }
    });
  }
  function finish(): void {
    if (!session) return;
    void perform(async () => { const report = await helper.finish(session.id, session.epoch); if (mounted.current) setSession({ ...session, state: 'completed', question: null, report }); });
  }
  const remaining = session ? Math.max(0, Math.ceil((Date.parse(session.deadline_at) - clock) / 1000)) : 0;
  const voice = session?.question && renderVoice ? renderVoice({ sessionId: session.id, epoch: session.epoch, messageId: session.question.id, onTranscript: text => setAnswer(previous => `${previous}${previous ? '\n' : ''}${text}`.slice(0, 12000)) }) : null;
  return <section className="interview-page" aria-labelledby="interview-title">
    <header className="interview-page-heading"><p>Practice under interview conditions</p><h1 id="interview-title">Make your reasoning heard.</h1><p>DSA · computer science · system design · codebase defense</p></header>
    {error && <div role="alert" className="interview-error"><p>{error}</p>{session ? <button type="button" disabled={busy} onClick={() => void reload()}>Reload session</button> : <button type="button" onClick={() => setRetry(n => n+1)}>Retry setup</button>}</div>}
    {!setup && !error && <p role="status">Loading interview setup…</p>}
    <div className="interview-desk">
      <div className="interview-paper">
        {!session && setup && <InterviewSetup config={setup.config} catalog={setup.catalog} busy={busy} onStart={start} />}
        {session?.state === 'active' && <>
          <div className="interview-session-meta"><span>{TYPE_LABELS[session.type]} · {session.difficulty}</span><span role="timer" aria-label="Time remaining">{Math.floor(remaining/60)}:{String(remaining%60).padStart(2, '0')} remaining</span></div>
          <p className="interview-note">{session.introduction.text}</p>
          {session.acknowledgement && <p role="status">{session.acknowledgement.text}</p>}
          <article className="interview-question" aria-labelledby="interview-question-title"><p>{session.question?.kind === 'followup' ? 'Follow-up question' : 'Current question'}</p><h2 id="interview-question-title" ref={questionHeading} tabIndex={-1}>{session.question?.text}</h2></article>
          {voice}
          <form onSubmit={event => { event.preventDefault(); submit(); }}>
            <label>Your answer<textarea required maxLength={12000} value={answer} disabled={busy || remaining === 0} onChange={event => setAnswer(event.target.value)} rows={7} /></label>
            {session.type === 'dsa' && <details><summary>Include code (optional, not executed)</summary><label>Your code<textarea maxLength={24000} value={code} disabled={busy} onChange={event => setCode(event.target.value)} rows={5} spellCheck={false} /></label></details>}
            <div className="interview-actions"><button type="submit" className="primary" disabled={busy || !answer.trim() || remaining === 0}>Submit answer</button><button type="button" disabled={busy} onClick={finish}>Finish interview</button>{!error && <button type="button" disabled={busy} onClick={() => void reload()}>Reload session</button>}</div>
          </form>
          {remaining === 0 && <p role="status">Time is up. Reload the session to retrieve your durable report.</p>}
        </>}
        {session?.report && <InterviewReportView report={session.report} onRecommendation={onRecommendation} />}
      </div>
      {!session?.report && <CameraPreview />}
    </div>
  </section>;
}
