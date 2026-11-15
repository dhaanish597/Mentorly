import { useEffect, useRef, useState } from 'react';
import type { RevisionRef } from '../types/api';
import { Icon } from './HorizonVisuals';
import './active-conversation.css';

export type ConversationEntry = {
  id: string; speaker: 'mentor' | 'student'; text: string;
  source?: 'model_assisted' | 'authored_public_contract' | 'authored_adaptive_fallback';
  timestamp?: string; revision?: RevisionRef;
};
export type ConversationStatus = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'playing' | 'interrupted' | 'error';
type Props = { speaker: ConversationEntry['speaker']; text: string; status: ConversationStatus; progress: number; history: readonly ConversationEntry[]; recordedFinalTranscript?: boolean; transcriptId?: string; isDraft?: boolean; mentorName?: string; mentorPortrait?: string };
const STATUS: Record<ConversationStatus, string> = {
  idle: 'Ready when you are', listening: 'Listening to you', transcribing: 'Transcribing your recording',
  thinking: 'Mentor thinking', playing: 'Mentor speaking', interrupted: 'Audio interrupted', error: 'Connection needs attention',
};
/** Retained for caption clients; conversation messages always show their complete text. */
export function revealTranscript(text: string, progress: number): string {
  if (progress >= 1) return text;
  if (progress <= 0) return '';
  const words = text.match(/\S+\s*/gu) ?? [];
  return words.slice(0, Math.floor(words.length * progress)).join('').trimEnd();
}
export function ActiveConversation({ speaker, text, status, history, recordedFinalTranscript = false, transcriptId = '', isDraft = false, mentorName = 'Astra', mentorPortrait }: Props) {
  const [copyStatus, setCopyStatus] = useState('');
  const [unread, setUnread] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const currentId = !isDraft && history.some(entry => entry.id === transcriptId && entry.speaker === speaker) ? transcriptId : undefined;
  const draft = isDraft && text.trim() && speaker === 'student' ? text : '';
  useEffect(() => {
    const node = scroll.current;
    if (!node) return;
    if (follow.current) { node.scrollTop = node.scrollHeight; setUnread(false); }
    else setUnread(true);
  }, [history, draft]);
  function jumpToLatest(): void {
    follow.current = true; setUnread(false);
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(history.map(entry => `${entry.speaker === 'mentor' ? mentorName : 'You'}: ${entry.text}`).join('\n\n'));
      setCopyStatus('Transcript copied.');
    } catch { setCopyStatus('Clipboard unavailable. Select the transcript text to copy it.'); }
  }
  return <section className="active-conversation" aria-label="Mentor–student conversation">
    <div className="conversation-header-row">
      <div className="conversation-status" role="status" aria-live="polite"><span className={`activity-dot ${status}`} />{STATUS[status]}</div>
      <div className="conversation-header-actions">
        {unread && <button type="button" className="jump-latest-button" onClick={jumpToLatest}>Jump to latest</button>}
        {history.length > 0 && (
          <button
            type="button"
            className="transcript-copy-button"
            onClick={() => { void copy(); }}
            aria-label="Copy transcript"
            title={copyStatus || 'Copy transcript'}
          >
            <Icon name={copyStatus === 'Transcript copied.' ? 'check' : 'copy'} />
          </button>
        )}
        {copyStatus && <span className="transcript-copy-status" role="status">{copyStatus}</span>}
      </div>
    </div>
    {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Keyboard users must be able to scroll the transcript independently. */}
    <div className="conversation-message-scroll" role="log" aria-live="off" ref={scroll} tabIndex={0} aria-label="Conversation history" onScroll={event => {
      const node = event.currentTarget;
      follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
      if (follow.current) setUnread(false);
    }}>
      {history.length ? <ol className="conversation-messages">{history.map(entry => <li key={entry.id} className={`conversation-message ${entry.speaker}`}>
        <div className="transcript-avatar" aria-hidden="true">{entry.speaker === 'mentor' && mentorPortrait ? <img src={mentorPortrait} alt="" /> : entry.speaker === 'mentor' ? 'A' : 'You'}</div>
        <div className="transcript-message-body"><div className="transcript-attribution"><strong>{entry.speaker === 'mentor' ? mentorName : 'You'}</strong><span>{entry.speaker === 'mentor' ? 'Mentor' : 'Student'}</span>{entry.timestamp && Number.isFinite(Date.parse(entry.timestamp)) && <time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>}</div>
          <p aria-label={entry.id === currentId ? 'Current speaker transcript' : undefined}>{entry.text}</p>
          {entry.source && entry.source !== 'model_assisted' && <span className="transcript-source">{entry.source === 'authored_public_contract' ? 'Problem guidance' : 'Guided fallback'}</span>}
        </div>
      </li>)}</ol> : <p className="transcript-empty">Your conversation will appear here when you send an explanation or receive a mentor reply.</p>}
      {draft && <div className="transcript-draft"><span>{recordedFinalTranscript ? 'Recognized text' : 'Unsent draft'}</span><p aria-label="Current speaker transcript">{draft}</p></div>}
      {status === 'listening' && <p className="transcript-note">Recognition returns a final transcript after you send. Listening is not an interim transcript.</p>}
    </div>
  </section>;
}
