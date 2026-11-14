import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ActiveConversation, revealTranscript } from '../components/ActiveConversation';

describe('active conversation', () => {
  it('reveals word boundaries against audio progress without losing Unicode', () => {
    expect(revealTranscript('தமிழ் code remains intact.', 0)).toBe('');
    expect(revealTranscript('தமிழ் code remains intact.', 0.5)).toBe('தமிழ் code');
    expect(revealTranscript('தமிழ் code remains intact.', 1)).toBe('தமிழ் code remains intact.');
  });
  it('shows only current speaker prominently, with attributed history available', () => {
    render(<ActiveConversation speaker="student" text="My current explanation" status="listening" progress={1} history={[{id:'a',speaker:'mentor',text:'Previous mentor answer'}]} />);
    expect(screen.getByLabelText('Current speaker transcript').textContent).toBe('My current explanation');
    expect(screen.getByText('Conversation history')).toBeTruthy();
    expect(screen.getByText('Final transcript appears after recognition; no interim transcript is invented.')).toBeTruthy();
  });
  it('never labels a pending response as speaking', () => {
    render(<ActiveConversation speaker="mentor" text="One two three four" status="thinking" progress={0} history={[]} />);
    expect(screen.queryByText('Mentor speaking')).toBeNull();
    expect(screen.getByText('Mentor thinking')).toBeTruthy();
  });
  it('keeps speech revelation incomplete until playback completes', () => {
    render(<ActiveConversation speaker="mentor" text="One two three four" status="playing" progress={0.5} history={[]} />);
    expect(screen.getByLabelText('Current speaker transcript').textContent).toBe('One two');
  });
});
