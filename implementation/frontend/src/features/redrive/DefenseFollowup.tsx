import { isSourceCitation, type SourceCitation } from './types';
import './redrive.css';

type Props = {
  phase: string;
  answer: string;
  citations: unknown[];
  onOpenSource: (citation: SourceCitation) => void;
};
/** Followups use a real recorded defense answer, never an invented assessment. */
export function DefenseFollowup({ phase, answer, citations, onOpenSource }: Props) {
  const references = citations.filter(isSourceCitation);
  if (!answer.trim() || !references.length) return null;
  const intent = /\bauthor|\bintended|\bwanted|\bguarantee/i.test(answer);
  const question = intent
    ? 'Which cited fact supports your claim, and which part remains an unsupported hypothesis?'
    : /\b(?:fail|error|except|retry|timeout)\b/i.test(answer)
      ? 'Which cited condition relates to that failure, and what runtime evidence would you still need?'
      : phase === 'reflect'
        ? 'Which cited constraint would your changed requirement affect, and what remains unknown?'
        : 'Which cited fact supports your explanation, and what alternative would you compare?';
  return <aside className="redrive-defense-followup" aria-label="Recorded defense followup">
    <h4>One follow-up on your recorded answer</h4>
    <p>{question}</p>
    <p className="repo-note">This is a discussion prompt, not a correctness grade. Runtime behavior and author intent are not established by static source.</p>
    <ul className="repo-citations">{references.map(citation => <li key={`${citation.path}:${citation.start_line}:${citation.chunk_hash}`}>
      <button type="button" onClick={() => onOpenSource(citation)}>{citation.path}, lines {citation.start_line}–{citation.end_line}</button>
    </li>)}</ul>
  </aside>;
}
