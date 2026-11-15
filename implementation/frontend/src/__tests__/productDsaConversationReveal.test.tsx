import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ActiveConversation, type ConversationEntry } from '../components/ActiveConversation';
const text = 'One two தமிழ் 🙂 five six seven eight.';
const entries: ConversationEntry[] = [{ id: 'student', speaker: 'student', text, timestamp: '2026-11-15T10:00:00Z' }, { id: 'mentor', speaker: 'mentor', text: 'Measure this boundary carefully.', timestamp: '2026-11-15T10:01:00Z' }];
const base = { speaker: 'mentor' as const, text: entries[1].text, status: 'playing' as const, progress: 0, history: entries, transcriptId: 'mentor' };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe('chronological conversation transcript', () => {
  it('keeps an identical new draft separate from the earlier submitted learner message', () => {
    const repeated = 'Please explain again';
    const history: ConversationEntry[] = [{ id: 'old-student', speaker: 'student', text: repeated }, { id: 'new-mentor', speaker: 'mentor', text: 'Which part should we revisit?' }];
    render(<ActiveConversation {...base} speaker="student" text={repeated} history={history} transcriptId="old-student" isDraft />);
    expect(screen.getByText('Unsent draft')).toBeInTheDocument();
    expect(screen.getByLabelText('Current speaker transcript')).toHaveTextContent(repeated);
    expect(within(screen.getByRole('list')).getByText(repeated)).not.toHaveAttribute('aria-label', 'Current speaker transcript');
    expect(screen.getAllByText(repeated)).toHaveLength(2);
  });
  it('uses the explicit message identity when multiple submitted messages have equal text', () => {
    const history: ConversationEntry[] = [{ id: 'first', speaker: 'student', text: 'Again' }, { id: 'second', speaker: 'student', text: 'Again' }];
    render(<ActiveConversation {...base} speaker="student" text="Again" history={history} transcriptId="first" />);
    expect(screen.getAllByRole('listitem')[0].querySelector('p')).toHaveAttribute('aria-label', 'Current speaker transcript');
    expect(screen.getAllByRole('listitem')[1].querySelector('p')).not.toHaveAttribute('aria-label');
    expect(screen.queryByText('Unsent draft')).not.toBeInTheDocument();
  });

  it('shows both full messages in received order before mentor playback completes', () => {
    render(<ActiveConversation {...base} />);
    const messages = within(screen.getByRole('list')).getAllByRole('listitem');
    expect(messages).toHaveLength(2); expect(messages[0]).toHaveTextContent(text); expect(messages[1]).toHaveTextContent(entries[1].text);
    expect(screen.getByLabelText('Current speaker transcript')).toHaveTextContent(entries[1].text);
    expect(messages[0].querySelector('time')).toHaveAttribute('datetime', entries[0].timestamp);
    expect(messages[1]).toHaveTextContent('Astra');
  });
  it('keeps empty listening state honest and creates no fabricated interim message', () => {
    render(<ActiveConversation {...base} speaker="student" text="" status="listening" history={[]} />);
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(screen.getByText(/Listening is not an interim transcript/)).toBeInTheDocument();
  });
  it('separates unsent edited text from submitted chronological messages', () => {
    render(<ActiveConversation {...base} speaker="student" text="My corrected draft" isDraft status="idle" />);
    expect(screen.getByText('Unsent draft')).toBeInTheDocument();
    expect(screen.getByLabelText('Current speaker transcript')).toHaveTextContent('My corrected draft');
    expect(within(screen.getByRole('list')).queryByText('My corrected draft')).not.toBeInTheDocument();
  });
  it.each(['transcribing', 'thinking', 'interrupted', 'error', 'idle'] as const)('retains completed text in %s state', status => {
    render(<ActiveConversation {...base} status={status} />);
    expect(screen.getByLabelText('Current speaker transcript')).toHaveTextContent(entries[1].text);
  });
  it('does not invent a timestamp for legacy entries or render an invalid timestamp', () => {
    render(<ActiveConversation {...base} history={[{ ...entries[0], timestamp: undefined }, { ...entries[1], timestamp: 'invalid' }]} />);
    expect(screen.getByRole('list').querySelectorAll('time')).toHaveLength(0);
  });
  it('preserves user scroll position when another real message arrives', () => {
    const view = render(<ActiveConversation {...base} />);
    const scroll = screen.getByLabelText('Conversation history');
    Object.defineProperties(scroll, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
    scroll.scrollTop = 100; fireEvent.scroll(scroll);
    view.rerender(<ActiveConversation {...base} history={[...entries, { id: 'third', speaker: 'student', text: 'A new explanation' }]} />);
    expect(scroll.scrollTop).toBe(100);
    fireEvent.click(screen.getByRole('button', { name: 'Jump to latest' }));
    expect(scroll.scrollTop).toBe(1000);
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument();
  });
  it('follows new messages while already at the bottom', () => {
    const view = render(<ActiveConversation {...base} />);
    const scroll = screen.getByLabelText('Conversation history');
    Object.defineProperties(scroll, { scrollHeight: { configurable: true, value: 600 }, clientHeight: { configurable: true, value: 200 } });
    scroll.scrollTop = 400; fireEvent.scroll(scroll);
    view.rerender(<ActiveConversation {...base} history={[...entries, { id: 'third', speaker: 'student', text: 'Another reply' }]} />);
    expect(scroll.scrollTop).toBe(600);
  });
  it.each([false, true])('copies full attributed messages and keeps history available after clipboard failure %s', async failed => {
    const writeText = vi.fn(); if (failed) writeText.mockRejectedValue(new Error('denied')); else writeText.mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<ActiveConversation {...base} />); fireEvent.click(screen.getByRole('button', { name: 'Copy transcript' }));
    await act(async () => Promise.resolve());
    expect(writeText).toHaveBeenCalledWith(`You: ${text}\n\nAstra: ${entries[1].text}`);
    expect(screen.getByRole('list')).toHaveTextContent(text);
    expect(screen.getByText(failed ? 'Clipboard unavailable. Select the transcript text to copy it.' : 'Transcript copied.')).toBeInTheDocument();
  });
});
