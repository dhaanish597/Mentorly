import { useState } from 'react';
import './active-conversation.css';

export type ConversationEntry = { id: string; speaker: 'mentor' | 'student'; text: string };
export type ConversationStatus = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'playing' | 'interrupted' | 'error';
type Props = { speaker: ConversationEntry['speaker']; text: string; status: ConversationStatus; progress: number; history: readonly ConversationEntry[] };
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
export function ActiveConversation({ speaker, text, status, progress, history }: Props) {
  const [copyStatus, setCopyStatus] = useState('');
  const visible = status === 'playing' ? revealTranscript(text, progress) : text;
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
    {status === 'listening' && <p className="transcript-note">Final transcript appears after recognition; no interim transcript is invented.</p>}
    {status === 'playing' && <p className="transcript-note">Text follows the audio clock; word timing is estimated.</p>}
    <details className="conversation-history"><summary>Conversation history</summary>
      {history.length ? <><ol>{history.map(entry => <li key={entry.id}><strong>{entry.speaker === 'student' ? 'You' : 'Mentor'}</strong><p>{entry.text}</p></li>)}</ol><button type="button" onClick={() => { void copy(); }}>Copy transcript</button></> : <p>Your completed exchanges will appear here.</p>}
      {copyStatus && <p role="status">{copyStatus}</p>}
    </details>
  </section>;
}
