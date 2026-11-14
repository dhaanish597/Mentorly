import { useEffect, useRef, useState } from 'react';
import { learningApi, type LearningLesson, type LearningSession } from '../../services/learningApi';
import { loadSpeechPreferences } from '../../voice/preferences';
import { resolveLanguageMode } from '../../voice/languages';
import { StudioError, type Workspace } from '../../studioApi';
import { forgetLessonSession, readLessonSession, rememberLessonSession } from './lessonSession';

export interface LessonPracticeProps { lesson: LearningLesson; workspace: Workspace; onComplete: () => void }
export function LessonPractice({ lesson, workspace, onComplete }: LessonPracticeProps) {
  const [session, setSession] = useState<LearningSession | null>(null);
  const [answer, setAnswer] = useState('');
  const [hint, setHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [storageNotice, setStorageNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [loadRevision, setLoadRevision] = useState(0);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const textarea = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const saved = readLessonSession(workspace, lesson.id);
    setError(null); setBusy(true);
    if (!saved) { setBusy(false); return () => controller.abort(); }
    learningApi.getSession(workspace, saved, controller.signal).then(data => {
      if (!controller.signal.aborted) { setSession(data); setBusy(false); }
    }).catch(error => {
      if (controller.signal.aborted) return;
      if (error instanceof StudioError && error.status === 404) {
        try { forgetLessonSession(workspace, lesson.id); } catch { setStorageNotice('Saved practice could not be cleared on this device.'); }
        setSession(null);
      } else setError(error instanceof Error ? error.message : 'Saved practice is unavailable. Retry loading it.');
      setBusy(false);
    });
    return () => controller.abort();
  }, [workspace, lesson.id, loadRevision]);

  async function run(action: () => Promise<LearningSession>, kind: 'start' | 'answer' | 'hint') {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const data = await action();
      if (!mounted.current) return;
      setSession(data);
      if (kind === 'start' && !rememberLessonSession(workspace, lesson.id, data.id)) setStorageNotice('Practice is saved on the server, but this tab cannot remember the session. Keep it open.');
      if (kind === 'hint') setHint(data.hint ?? data.coach_messages[data.coach_messages.length - 1] ?? data.feedback?.hint ?? 'No further hint is available. Review the explanation above.');
      if (kind === 'answer' && (data.report?.lesson_completed || data.state === 'completed')) onComplete();
      if (kind === 'answer' && !data.feedback?.correct) textarea.current?.focus();
    } catch (error) {
      if (!mounted.current || error instanceof DOMException && error.name === 'AbortError') return;
      setError(error instanceof StudioError && error.status === 409 ? 'Your session changed. Reload practice before answering again.' : error instanceof Error ? error.message : 'Practice could not be saved. Please retry.');
    } finally { if (mounted.current) setBusy(false); }
  }
  function signal(): AbortSignal { request.current?.abort(); request.current = new AbortController(); return request.current.signal; }
  const completed = session?.state === 'completed' || session?.report?.lesson_completed;
  return <section className="lesson-practice" aria-labelledby="practice-heading">
    <header><p className="learning-eyebrow">Try it yourself</p><h2 id="practice-heading">Check your understanding</h2><p>Explain your reasoning. Hints are here when you need a nudge.</p></header>
    {storageNotice && <p role="status">{storageNotice}</p>}
    {error && <div className="learning-notice" role="alert"><p>{error}</p><button type="button" onClick={() => setLoadRevision(value => value + 1)}>Reload practice</button></div>}
    {busy && !session && <p role="status">Loading practice…</p>}
    {!session && !busy && !error && <button type="button" className="product-button" onClick={() => void run(() => learningApi.createSession(workspace, lesson.id, resolveLanguageMode(loadSpeechPreferences().sttLanguage, loadSpeechPreferences().codeMixing), signal()), 'start')}>Start practice</button>}
    {session && <>
      {session.coach_messages.length > 0 && <div className="lesson-coach">{session.coach_messages.map((message, index) => <p key={`${index}:${message}`}>{message}</p>)}</div>}
      <form onSubmit={event => { event.preventDefault(); if (answer.trim() && !completed) void run(() => learningApi.answer(workspace, session, answer.trim(), signal()), 'answer'); }}>
        <fieldset disabled={busy || !!completed}><legend>{session.question.prompt}</legend>
          {session.question.options?.length ? <div className="lesson-options">{session.question.options.map(option => <label key={option}><input type="radio" name="answer" value={option} checked={answer === option} onChange={() => setAnswer(option)} /><span>{option}</span></label>)}</div> : <label className="lesson-answer-label">Your explanation<textarea ref={textarea} value={answer} onChange={event => setAnswer(event.target.value)} maxLength={12000} rows={5} placeholder="Walk through what happens and why…" /></label>}
        </fieldset>
        {!completed && <div className="lesson-actions"><button className="product-button" type="submit" disabled={busy || !answer.trim()}>{busy ? 'Saving…' : 'Check answer'}</button><button type="button" disabled={busy} onClick={() => void run(() => learningApi.hint(workspace, session, signal()), 'hint')}>Get a hint</button></div>}
      </form>
      {hint && <aside className="lesson-hint" aria-label="Practice hint" role="status"><strong>A little nudge</strong><p>{hint}</p></aside>}
      {session.feedback && <div className={`lesson-feedback ${session.feedback.correct ? 'feedback-correct' : ''}`} role="status"><strong>{session.feedback.correct ? 'Nicely reasoned' : 'Keep exploring'}</strong><p>{session.feedback.message}</p></div>}
      {completed && <div className="lesson-completed"><h3>Lesson completed</h3>{session.report?.summary && <p>{session.report.summary}</p>}<p>Your progress is saved in this workspace.</p></div>}
    </>}
  </section>;
}
