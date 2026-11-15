import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LessonPractice } from '../features/curriculum/LessonPractice';
import { InterviewReportView } from '../features/interview/InterviewReportView';
import type { InterviewReport } from '../features/interview/types';
import { learningApi, parseLearningSession, type LearningLesson } from '../services/learningApi';
import { parseExplanationReview, parseSemanticReview } from '../services/semanticReview';

vi.mock('../voice/ModuleVoice', () => ({ ModuleVoice: () => null }));
const semantic = {
  schema_version: '1.0', status: 'SUPPORTED', criteria: [{ id: 'reasoning_coherence', status: 'SUPPORTED', explanation: 'The answer describes retained state.', evidence_refs: [{ source: 'answer', start: 0, end: 5, excerpt: 'State' }] }],
  evidence_refs: [{ source: 'answer', start: 0, end: 5, excerpt: 'State' }], uncertainty: 'No execution proof was provided.', explanation: 'This is a reasoning quality interpretation.', followup: 'How does that state change?',
  reviewed_answer_revision: 1, answer_sha256: 'a'.repeat(64), context_sha256: 'b'.repeat(64), rubric_version: 'semantic-quality-v1', model_provenance: { provider: 'groq', model: 'fixture-model', request_id: 'fixture-request', status: 'MODEL_ASSISTED' }, correctness_assessed: false,
};
const explanation = { status: 'SUPPORTED', review: semantic, changes_objective_credit: false };
const workspace = { id: 'fixture-workspace', token: 'fixture-capability' };
const lesson: LearningLesson = { id: 'fixture-lesson', title: 'Objective lesson', prerequisites: [], difficulty: 'beginner', estimated_minutes: 8, objectives: ['Check the state'], explanation: 'Explain the state', example: 'State example', hints: ['Hint'], practice_url: '/library', question: { id: 'q', prompt: 'Choose the count', options: ['3', '4'], option_ids: ['a', 'b'] } };
const session = parseLearningSession({ id: 'fixture-session', lesson_id: lesson.id, epoch: 1, mode: 'practice', state: 'active', question: lesson.question, coach_messages: [], answer_count: 0, deadline: null });
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); });

describe('separate explanation review contract', () => {
  it('rejects model statuses or credit flags outside the canonical contract', () => {
    expect(parseSemanticReview(semantic).status).toBe('SUPPORTED');
    expect(() => parseSemanticReview({ ...semantic, correctness_assessed: true })).toThrow();
    expect(() => parseSemanticReview({ ...semantic, model_provenance: { ...semantic.model_provenance, status: 'PASSED_EXECUTION' } })).toThrow();
    expect(() => parseExplanationReview({ ...explanation, changes_objective_credit: true })).toThrow();
  });
  it('submits explanation only after objective confirmation and explicitly opts into external feedback', async () => {
    vi.spyOn(learningApi, 'createSession').mockResolvedValue(session);
    const answer = vi.spyOn(learningApi, 'answer').mockResolvedValue(parseLearningSession({ ...session, epoch: 2, coach_messages: [], feedback: { correct: false, message: 'Not verified.', explanation_review: explanation }, report: { lesson_completed: false, summary: 'No completion awarded.' } }));
    const complete = vi.fn();
    render(<LessonPractice lesson={lesson} workspace={workspace} onComplete={complete} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start practice' }));
    const draft = await screen.findByRole('textbox', { name: 'Your explanation (optional)' });
    fireEvent.change(draft, { target: { value: 'State is retained.' } });
    expect(answer).not.toHaveBeenCalled();
    expect(screen.getByRole('checkbox', { name: 'Send my explanation to the configured model for feedback' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Send my explanation to the configured model for feedback' }));
    fireEvent.click(screen.getByRole('radio', { name: '4' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }));
    await waitFor(() => expect(answer).toHaveBeenCalledWith(workspace, session, '4', expect.any(AbortSignal), 'State is retained.', true));
    expect(await screen.findByRole('heading', { name: 'Explanation feedback' })).toBeInTheDocument();
    expect(screen.getByText('SUPPORTED · MODEL ASSISTED')).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: 'Lesson completed' })).not.toBeInTheDocument();
  });
  it('renders semantic review in the completed report with execution limits and provenance', () => {
    const report: InterviewReport = { session_id: 'fixture', completion_reason: 'finished', completed_at: '2026-11-15T00:00:00Z', answered_count: 1, semantic_validity: { status: 'unassessed', reason: 'Quality interpretations only.' }, technical_correctness: { status: 'unassessed_no_execution_evidence', reason: 'Code was not executed.' }, psychology: { status: 'not_assessed', reason: 'No inference.' }, answers: [{ question_id: 'q', question: 'What state is retained?', answer: 'State', code: null, indicators: [], semantic_review: parseSemanticReview(semantic) }], recommendations: [], limitations: ['Model quality is not execution proof.'] };
    render(<InterviewReportView report={report} />);
    expect(screen.getByRole('heading', { name: 'Explanation quality' })).toBeInTheDocument();
    expect(screen.getByText('SUPPORTED · MODEL ASSISTED')).toBeInTheDocument();
    expect(screen.getByText('Code was not executed.')).toBeInTheDocument();
    expect(screen.getByText(/Answer revision 1/)).toBeInTheDocument();
  });
});
