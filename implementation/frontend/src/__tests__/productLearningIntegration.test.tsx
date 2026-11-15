import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { LessonPractice } from '../features/curriculum/LessonPractice';
import { learningApi, parseLearningSession, type LearningLesson } from '../services/learningApi';

// Explicit component doubles: voice/provider and interview engine are tested separately.
vi.mock('../features/interview/InterviewPage', () => ({ InterviewPage: ({ workspace }: { workspace: { id: string } }) => <h1>Interview workspace {workspace.id}</h1> }));
vi.mock('../voice/ModuleVoice', () => ({ ModuleVoice: ({ onTranscript, messageId }: { onTranscript: (text: string) => void; messageId?: string }) => <button type="button" onClick={() => onTranscript('My spoken explanation')} aria-label={`Mock speak ${messageId ?? ''}`}>Speak fixture</button> }));
const workspace = { id: 'mock-workspace', token: 'mock-token' };
const lesson: LearningLesson = { id: 'objective', title: 'Objective reasoning', prerequisites: [], difficulty: 'beginner', estimated_minutes: 8, objectives: ['Observe a value'], explanation: 'Explanation', example: 'Example', hints: ['hint'], practice_url: '/library', question: { id: 'q', prompt: 'Choose the value', options: ['3', '4'] } };
const session = parseLearningSession({ id: 'mock-session', lesson_id: lesson.id, epoch: 1, mode: 'practice', state: 'active', question: lesson.question, coach_messages: [{ id: 'persisted-message', role: 'assistant', kind: 'question', text: 'Choose the value' }], answer_count: 0, hint_count: 0, deadline: null });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); localStorage.clear(); });

describe('product module integration', () => {
  it('mounts interviews with the exact existing tab workspace', async () => {
    sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ workspace, sessions: [] }));
    history.replaceState({}, '', '/interviews'); render(<ProductApp />);
    expect(await screen.findByRole('heading', { name: 'Interview workspace mock-workspace' })).toBeInTheDocument();
  });
  it('fills an unassessed explanation draft from voice without submitting', async () => {
    vi.spyOn(learningApi, 'createSession').mockResolvedValue(session);
    const answer = vi.spyOn(learningApi, 'answer').mockResolvedValue(session);
    render(<LessonPractice lesson={lesson} workspace={workspace} onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start practice' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Mock speak persisted-message' }));
    expect(screen.getByRole('textbox', { name: 'Your explanation (optional, unassessed)' })).toHaveValue('My spoken explanation');
    expect(answer).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Check answer' })).toBeDisabled();
    fireEvent.click(screen.getByRole('radio', { name: '3' })); fireEvent.click(screen.getByRole('button', { name: 'Check answer' }));
    await waitFor(() => expect(answer).toHaveBeenCalledWith(workspace, session, '3', expect.any(AbortSignal)));
  });
  it('restarts an exhausted practice session and clears its answer draft', async () => {
    vi.spyOn(learningApi, 'createSession').mockResolvedValue({ ...session, state: 'exhausted', answer_count: 5 });
    const restart = vi.spyOn(learningApi, 'restart').mockResolvedValue({ ...session, epoch: 6 });
    render(<LessonPractice lesson={lesson} workspace={workspace} onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start practice' }));
    expect(await screen.findByText('This practice round has ended. Review the example and try a fresh round.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check answer' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Restart practice' }));
    await waitFor(() => expect(restart).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: 'Check answer' })).toBeDisabled();
  });
});
