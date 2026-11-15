import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ActiveConversation } from '../components/ActiveConversation';

// This is visual reveal of an already returned final transcript, not interim ASR.
const final = 'One two தமிழ் 🙂 five six seven eight.';
const base = { speaker: 'student' as const, text: final, status: 'idle' as const, progress: 1, history: [{ id: 'final-1', speaker: 'student' as const, text: final }] };
function current() { return screen.getByLabelText('Current speaker transcript'); }
let motion: { matches: boolean; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };
let write: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.useFakeTimers();
  motion = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  vi.stubGlobal('matchMedia', () => motion);
  write = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText: write } });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function advance(ms: number) { await act(async () => vi.advanceTimersByTimeAsync(ms)); }

describe('final recorded transcript visual reveal', () => {
  it('leaves default typed text fully visible and does not schedule a visual reveal', () => {
    render(<ActiveConversation {...base} />);
    expect(current()).toHaveTextContent(final);
    expect(screen.queryByText(/Final transcript — visual reveal/)).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('reveals only returned final words, completes promptly, and keeps full history copyable throughout', async () => {
    render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="voice-1" />);
    expect(current()).toHaveTextContent('One');
    expect(current()).not.toHaveTextContent(final);
    expect(screen.getByText('Final transcript — visual reveal, not live recognition')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Conversation history'));
    expect(within(screen.getByRole('list')).getByText(final)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Copy transcript' }));
    await act(async () => Promise.resolve());
    expect(write).toHaveBeenCalledExactlyOnceWith(`You: ${final}`);
    await advance(600);
    expect(current()).toHaveTextContent('One two தமிழ் 🙂');
    expect(current()).not.toHaveTextContent(final);
    await advance(1400);
    expect(current()).toHaveTextContent(final);
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['', '   '])('never schedules reveal or claims final ASR words for an empty transcript %j', text => {
    render(<ActiveConversation {...base} text={text} history={[]} recordedFinalTranscript transcriptId="empty" />);
    expect(screen.queryByText(/Final transcript — visual reveal/)).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('shows the entire final transcript immediately under reduced motion', () => {
    motion.matches = true;
    render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="reduced" />);
    expect(current()).toHaveTextContent(final);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('switching to reduced motion ends visual reveal immediately and releases the listener', async () => {
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="motion" />);
    await advance(200);
    const changed = motion.addEventListener.mock.calls[0][1] as () => void;
    act(() => { motion.matches = true; changed(); });
    expect(current()).toHaveTextContent(final);
    expect(vi.getTimerCount()).toBe(0);
    view.unmount(); expect(motion.removeEventListener).toHaveBeenCalled();
  });
  it('a new transcript cancels the old reveal rather than delivering stale words', async () => {
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="old" />);
    await advance(600);
    const next = 'Different response with its own final words.';
    view.rerender(<ActiveConversation {...base} text={next} recordedFinalTranscript transcriptId="new" />);
    expect(current()).toHaveTextContent('Different');
    expect(current()).not.toHaveTextContent('One two');
    expect(current()).not.toHaveTextContent(next);
    await advance(2000);
    expect(current()).toHaveTextContent(next);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('a new turn with identical final text starts a fresh reveal', async () => {
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="first" />);
    await advance(600);
    expect(current()).toHaveTextContent('One two தமிழ்');
    view.rerender(<ActiveConversation {...base} recordedFinalTranscript transcriptId="second" />);
    expect(current()).toHaveTextContent('One');
    expect(current()).not.toHaveTextContent('One two');
  });
  it('typing or cancellation stops the old visual reveal without delaying replacement text', async () => {
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="voice" />);
    await advance(200);
    view.rerender(<ActiveConversation {...base} text="My edited explanation is immediately visible." recordedFinalTranscript={false} transcriptId="edited" />);
    expect(current()).toHaveTextContent('My edited explanation is immediately visible.');
    expect(vi.getTimerCount()).toBe(0);
    await advance(2000);
    expect(current()).not.toHaveTextContent(final);
  });
  it.each(['interrupted', 'error', 'transcribing'] as const)('status %s cancels visual reveal without implying interim ASR', status => {
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="voice" />);
    view.rerender(<ActiveConversation {...base} status={status} recordedFinalTranscript transcriptId="voice" />);
    expect(vi.getTimerCount()).toBe(0);
    expect(screen.queryByText(/Final transcript — visual reveal/)).not.toBeInTheDocument();
  });
  it('mentor audio still follows only the actual audio clock and cancels student reveal', () => {
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="student" />);
    view.rerender(<ActiveConversation {...base} speaker="mentor" text="Measure this boundary carefully." status="playing" progress={.5} recordedFinalTranscript transcriptId="mentor" />);
    expect(current()).toHaveTextContent('Measure this');
    expect(current()).not.toHaveTextContent('boundary carefully');
    expect(screen.queryByText(/Final transcript — visual reveal/)).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('unmount cancels pending reveal even when motion preferences are unavailable', async () => {
    vi.stubGlobal('matchMedia', undefined);
    const view = render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="no-media" />);
    await advance(200); view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('reports clipboard failure while leaving the full final history available', async () => {
    write.mockRejectedValue(new Error('Clipboard denied'));
    render(<ActiveConversation {...base} recordedFinalTranscript transcriptId="copy-failure" />);
    fireEvent.click(screen.getByText('Conversation history'));
    fireEvent.click(screen.getByRole('button', { name: 'Copy transcript' }));
    await act(async () => Promise.resolve());
    expect(screen.getByText('Clipboard unavailable. Select the history text to copy it.')).toBeInTheDocument();
    expect(within(screen.getByRole('list')).getByText(final)).toBeInTheDocument();
  });
});
