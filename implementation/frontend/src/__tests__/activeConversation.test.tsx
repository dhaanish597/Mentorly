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
    render(<ActiveConversation speaker="student" text="My current explanation" isDraft status="listening" progress={1} history={[{id:'a',speaker:'mentor',text:'Previous mentor answer'}]} />);
    expect(screen.getByLabelText('Current speaker transcript').textContent).toBe('My current explanation');
    expect(screen.getByLabelText('Conversation history')).toBeTruthy();
    expect(screen.getByText('Recognition returns a final transcript after you send. Listening is not an interim transcript.')).toBeTruthy();
  });
  it('never labels a pending response as speaking', () => {
    render(<ActiveConversation speaker="mentor" text="One two three four" status="thinking" progress={0} history={[]} />);
    expect(screen.queryByText('Mentor speaking')).toBeNull();
    expect(screen.getByText('Mentor thinking')).toBeTruthy();
  });
  it('shows a complete received mentor message before playback completes', () => {
    render(<ActiveConversation speaker="mentor" text="One two three four" transcriptId="mentor" status="playing" progress={0.5} history={[{id:'mentor',speaker:'mentor',text:'One two three four'}]} />);
    expect(screen.getByLabelText('Current speaker transcript').textContent).toBe('One two three four');
  });
});
