import { useEffect, useState } from 'react';
import './active-conversation.css';

export type ConversationEntry = { id: string; speaker: 'mentor' | 'student'; text: string; source?: 'model_assisted' | 'authored_public_contract' | 'authored_adaptive_fallback' };
export type ConversationStatus = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'playing' | 'interrupted' | 'error';
type Props = { speaker: ConversationEntry['speaker']; text: string; status: ConversationStatus; progress: number; history: readonly ConversationEntry[]; recordedFinalTranscript?: boolean; transcriptId?: string };
const FINAL_REVEAL_DURATION_MS = 1200;
const FINAL_REVEAL_STEP_MS = 100;
function useFinalTranscriptReveal(source: string, enabled: boolean, initialProgress: number): number {
  const [reveal, setReveal] = useState({ source: '', progress: 1 });
  useEffect(() => {
    if (!enabled) return;
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    let timer: number | undefined;
    const finish = () => { setReveal({ source, progress: 1 }); if (timer !== undefined) window.clearInterval(timer); };
    if (media?.matches) { finish(); return; }
    const started = Date.now();
    setReveal({ source, progress: initialProgress });
    timer = window.setInterval(() => {
      const progress = Math.max(initialProgress, Math.min(1, (Date.now() - started) / FINAL_REVEAL_DURATION_MS));
      setReveal({ source, progress });
      if (progress >= 1) window.clearInterval(timer);
    }, FINAL_REVEAL_STEP_MS);
    const changed = () => { if (media?.matches) finish(); };
    media?.addEventListener('change', changed);
    return () => { window.clearInterval(timer); media?.removeEventListener('change', changed); };
  }, [source, enabled, initialProgress]);
  if (!enabled || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 1;
  return reveal.source === source ? reveal.progress : initialProgress;
}
const STATUS: Record<ConversationStatus, string> = {
  idle: 'Ready when you are', listening: 'Listening to you', transcribing: 'Transcribing your recording',
  thinking: 'Mentor thinking', playing: 'Mentor speaking', interrupted: 'Audio interrupted', error: 'Connection needs attention',
};
/** Word-boundary estimate from playback progress, not provider word timestamps. */
export function revealTranscript(text: string, progress: number): string {
  if (progress >= 1) return text;
  if (progress <= 0) return '';
  const words = text.match(/\S+\s*/gu) ?? [];
  return words.slice(0, Math.floor(words.length * progress)).join('').trimEnd();
}
export function ActiveConversation({ speaker, text, status, progress, history, recordedFinalTranscript = false, transcriptId = '' }: Props) {
  const [copyStatus, setCopyStatus] = useState('');
  const finalRecorded = speaker === 'student' && recordedFinalTranscript && !!text.trim() && !['playing', 'interrupted', 'error', 'transcribing'].includes(status);
  const source = JSON.stringify([transcriptId, text]);
  const visualProgress = useFinalTranscriptReveal(source, finalRecorded, 1 / (text.match(/\S+/gu)?.length || 1));
  const visible = status === 'playing' ? revealTranscript(text, progress) : finalRecorded ? revealTranscript(text, visualProgress) : text;
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(history.map(entry => `${entry.speaker === 'mentor' ? 'Mentor' : 'You'}: ${entry.text}`).join('\n\n'));
      setCopyStatus('Transcript copied.');
    } catch { setCopyStatus('Clipboard unavailable. Select the history text to copy it.'); }
  }
  return <section className={`active-conversation speaker-${speaker}`} aria-label="Mentor–student conversation">
    <div className="conversation-status" role="status" aria-live="polite"><span className={`activity-dot ${status}`} />{STATUS[status]}</div>
    <div className="active-utterance"><p className="speaker-label">{speaker === 'student' ? 'You' : 'Your mentor'}</p>
      <p className="active-transcript" aria-label="Current speaker transcript" aria-live="off">{visible || (status === 'listening' ? 'Take your time. Your next explanation belongs here.' : status === 'playing' ? '…' : 'Ask a question, explain an approach, or explore an edge case.')}</p>
    </div>
    {finalRecorded && <p className="transcript-note">Final transcript — visual reveal, not live recognition</p>}
    {status === 'listening' && !finalRecorded && <p className="transcript-note">Final transcript appears after recognition; no interim transcript is invented.</p>}
    {status === 'playing' && <p className="transcript-note">Text follows the audio clock; word timing is estimated.</p>}
    <details className="conversation-history"><summary>Conversation history</summary>
      {history.length ? <><ol>{history.map(entry => <li key={entry.id}><strong>{entry.speaker === 'student' ? 'You' : 'Mentor'}</strong><p>{entry.text}</p></li>)}</ol><button type="button" onClick={() => { void copy(); }}>Copy transcript</button></> : <p>Your completed exchanges will appear here.</p>}
      {copyStatus && <p role="status">{copyStatus}</p>}
    </details>
  </section>;
}
