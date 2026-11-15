import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { MeetYourTeachers } from '../components/MeetYourTeachers';
import { learningApi, type LearningLesson } from '../services/learningApi';
import { apiClient } from '../services/apiClient';

// Explicit API fixtures using published foundation IDs; not a live-server assertion.
const roots: LearningLesson[] = [
  { id: 'apt-percent', title: 'Percentage change and changing bases', prerequisites: [], difficulty: 'beginner', estimated_minutes: 10, objectives: ['Track the changing base'], explanation: 'Percentage changes depend on the current base.', example: '100 increased by 10% is 110.', hints: [], practice_url: '/library', question: { id: 'apt-question', prompt: 'Choose the base.', options: ['100', '110'] } },
  { id: 'cs-processes', title: 'Processes, threads and isolation', prerequisites: [], difficulty: 'beginner', estimated_minutes: 10, objectives: ['Distinguish processes from threads'], explanation: 'Processes isolate address spaces.', example: 'Two threads can share memory in one process.', hints: [], practice_url: '/library', question: { id: 'cs-question', prompt: 'Choose the isolation boundary.', options: ['Process', 'Thread'] } },
];
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); localStorage.clear(); });

describe('teacher discovery reaches the curriculum', () => {
  it.each([['Veda', 'apt-percent'], ['Corel', 'cs-processes']])('opens %s’s published foundation lesson', async (name, id) => {
    sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ workspace: { id: 'mock-workspace', token: 'mock-token' }, sessions: [] }));
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
    vi.spyOn(learningApi, 'getCatalog').mockResolvedValue({ version: 'mock-v1', tracks: [{ id: 'foundations', module: 'Foundations', title: 'Foundation lessons', description: 'Published roots', lessons: roots }] });
    vi.spyOn(learningApi, 'getProgress').mockResolvedValue({ lessons_completed: 0, attempts: 0, topics_mastered: 0, practice_sessions: 0, interviews_completed: 0, study_seconds: 0, streak: 0, completed_lesson_ids: [], achievements: [], recommendations: [], recent_activity: [] });
    history.replaceState({}, '', '/dashboard'); render(<ProductApp />);
    const link = screen.getByRole('link', { name: `Practice with ${name}` });
    expect(link).toHaveAttribute('href', `/learn/${id}`);
    fireEvent.click(link);
    expect(location.pathname).toBe(`/learn/${id}`);
    expect(await screen.findByRole('heading', { name: roots.find(lesson => lesson.id === id)!.title })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start practice' })).toBeEnabled();
  });
  it('keeps DSA and studio destinations and makes no human-mentor claim', () => {
    render(<MeetYourTeachers />);
    expect(screen.getByRole('link', { name: 'Practice with Astra' })).toHaveAttribute('href', '/library');
    expect(screen.getByRole('link', { name: 'Practice with Nexus' })).toHaveAttribute('href', '/studio');
    expect(screen.queryByText(/human AI mentors/)).not.toBeInTheDocument();
  });
});
