import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ModuleVoice } from '../../voice/ModuleVoice';
import { StudioError, studioRequest, type StudioSession, type Workspace } from '../../studioApi';
import { parseLearningPlan, type LearningPlan, type SourceCitation } from './types';
import './redrive.css';

export type RedrivePanelProps = {
  workspace: Workspace;
  snapshotId: string;
  onOpenSource: (citation: SourceCitation) => void;
  session?: StudioSession | null;
  speechEpoch?: number;
  active?: boolean;
};
export function RedrivePanel(props: RedrivePanelProps) {
  // Capability and snapshot replacement destroy drafts, consent and in-flight work.
  const key = JSON.stringify([props.workspace.id, props.workspace.token, props.snapshotId, props.session?.id, props.session?.token]);
  return <LearningPanel key={key} {...props} />;
}
function LearningPanel({ workspace, snapshotId, onOpenSource, active = true }: RedrivePanelProps) {
  const [plan, setPlan] = useState<LearningPlan | null>(null);
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const mounted = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const label = useId();
  const oversized = answer.length > 4000;
  const current = plan?.current_step;
  const lastEvidence = plan && plan.evidence_events[plan.evidence_events.length - 1];

  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    pending.current = controller;
    studioRequest<unknown>(`/repos/${encodeURIComponent(snapshotId)}/learning-plan`, { method: 'POST', workspace: { id: workspace.id, token: workspace.token }, signal: controller.signal })
      .then(value => { if (mounted.current && !controller.signal.aborted) setPlan(parseLearningPlan(value, snapshotId)); })
      .catch(reason => { if (mounted.current && !controller.signal.aborted) setError(message(reason)); })
      .finally(() => { if (mounted.current && !controller.signal.aborted) { pending.current = null; setBusy(false); } });
    return () => controller.abort();
  }, [snapshotId, workspace.id, workspace.token]);
  useEffect(() => { if (active) heading.current?.focus(); }, [plan?.epoch, active]);

  async function run(kind: 'answer' | 'reload') {
    if (!plan || pending.current || !active) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError('');
    try {
      const path = `/repos/learning-plans/${encodeURIComponent(plan.plan_id)}`;
      const value = await studioRequest<unknown>(kind === 'answer' ? `${path}/answers` : path, {
        method: kind === 'answer' ? 'POST' : 'GET', workspace, signal: controller.signal,
        ...(kind === 'answer' ? { body: { expected_epoch: plan.epoch, answer: answer.trim() } } : {}),
      });
      if (!mounted.current || controller.signal.aborted) return;
      const updated = parseLearningPlan(value, snapshotId);
      if (updated.plan_id !== plan.plan_id) throw new Error('Learning checkpoint identity changed. Reopen the current snapshot.');
      setPlan(updated); setConflict(false);
      if (kind === 'answer') setAnswer('');
    } catch (reason) {
      if (!mounted.current || controller.signal.aborted) return;
      setError(message(reason));
      if (reason instanceof StudioError && reason.status === 409) setConflict(true);
    } finally {
      if (mounted.current && !controller.signal.aborted) { pending.current = null; setBusy(false); }
    }
  }
  function exportRecord() {
    if (!plan) return;
    const record = { version: 'redrive-v1', plan, basis: 'Source-cited observations and learner attempts; completion does not establish mastery.' };
    const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }));
    try { const link = document.createElement('a'); link.href = url; link.download = 'redrive-learning-record.json'; link.click(); }
    finally { URL.revokeObjectURL(url); }
  }
  return <section className="redrive-panel" aria-label="Beginner codebase learning" aria-busy={busy}>
    {error && <p role="alert" className="studio-error">{error}</p>}
    {busy && !plan && <p role="status">Preparing your source-grounded first lesson…</p>}
    {!busy && !plan && <p className="repo-note">No learning checkpoint is available. Return to the repository and try again after indexing.</p>}
    {plan && <>
      <p className="repo-phase">From the beginning · {plan.status === 'review' ? 'Revisiting a mistake' : `Lesson ${Math.min(plan.checkpoint.cursor + 1, plan.steps.length)} of ${plan.steps.length}`} · checkpoint {plan.epoch}</p>
      <h4 ref={heading} tabIndex={-1}>{current?.title ?? 'Learning record'}</h4>
      <p className="repo-note">Mastery is not established. A short answer records an observation, not proof that you understand the whole codebase.</p>
      {lastEvidence && <aside className="redrive-feedback" aria-label="Last answer feedback" aria-live="polite"><strong>{assessmentLabel(lastEvidence.assessment)}</strong><p>{lastEvidence.feedback}</p></aside>}
      {current ? <>
        <p className="redrive-explanation">{current.explanation}</p>
        <ul className="repo-citations">{current.citations.map(citation => <li key={`${citation.path}:${citation.start_line}:${citation.chunk_hash}`}>
          <button type="button" disabled={busy || !active} onClick={() => onOpenSource(citation)}>{citation.path}, lines {citation.start_line}–{citation.end_line}</button>
          <span className="redrive-hash">sha256:{citation.chunk_hash}</span>
        </li>)}</ul>
        <p className="repo-mentor-question">{current.question}</p>
        {active && !busy && !conflict && <ModuleVoice key={`${plan.plan_id}:${plan.epoch}`} module="redrive" sessionId={plan.plan_id} epoch={plan.epoch} workspace={workspace}
          messageId={`${current.step_id}:explanation`} onTranscript={text => setAnswer(previous => previous ? `${previous}\n${text}` : text)} />}
        <form onSubmit={event => { event.preventDefault(); if (!busy && !conflict && !oversized && answer.trim()) void run('answer'); }}>
          <label htmlFor={label}>Your beginner answer</label>
          <textarea id={label} value={answer} maxLength={4000} disabled={!active || busy} onChange={event => setAnswer(event.target.value)} />
          <p className="repo-note">Review your draft before saving. Voice never submits for you. {plan.revisit_step_ids.length > 0 && `${plan.revisit_step_ids.length} topic(s) queued to revisit.`}</p>
          {oversized && <p role="alert">Your transcript is preserved. Shorten it to 4,000 characters before saving.</p>}
          <button type="submit" className="primary repo-submit" disabled={!active || busy || conflict || !answer.trim() || oversized}>Save comprehension answer</button>
        </form>
      </> : <p role="status">Plan completed. Revisit the cited source; completion is not mastery.</p>}
      <div className="studio-actions"><button type="button" disabled={!active || busy} onClick={() => void run('reload')}>Reload checkpoint</button>
        <button type="button" disabled={busy} onClick={exportRecord}>Export beginner learning record</button></div>
      <details className="repo-disclosure"><summary>Plan and recorded attempts</summary>
        <ol>{plan.steps.map(step => <li key={step.step_id}>{step.phase.replace('_', ' / ')} — {step.title}{plan.checkpoint.completed_step_ids.includes(step.step_id) ? ' · observation recorded' : ''}</li>)}</ol>
        {plan.attempts.length ? <ol>{plan.attempts.map(attempt => <li key={attempt.sequence}><p>{attempt.answer}</p></li>)}</ol> : <p>No attempts yet.</p>}
      </details>
      <details className="repo-disclosure"><summary>Coverage and limits</summary><ul>{plan.limitations.map(item => <li key={item}>{item}</li>)}</ul></details>
    </>}
  </section>;
}
function message(reason: unknown): string { return reason instanceof Error ? reason.message : 'The learning request failed. Your draft is preserved.'; }
function assessmentLabel(assessment: string): string {
  return ({ supported_observation: 'Source observation recorded', unsupported_claim: 'Unsupported, not necessarily wrong',
    contradicted_by_source: 'Source-path mismatch', needs_support: 'Let’s inspect one fact together' })[assessment] ?? 'Attempt recorded';
}
