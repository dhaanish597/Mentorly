import { describe, expect, it } from 'vitest';
import { learningUrl, parseLearningProgress } from '../services/learningApi';

const progress = { lessons_completed: 0, attempts: 0, topics_mastered: 0, practice_sessions: 0, interviews_completed: 0, study_seconds: 0, streak: 0, completed_lesson_ids: [], achievements: [], recent_activity: [] };

describe('learning destination normalization boundary', () => {
  it.each(['/a/..//example.org', '/a/%2e%2e//example.org', '/a/.%2e//example.org', '/a/%2e.//example.org', '/a/%2E%2E//example.org?report=A#evidence', '/a/b/../..//example.org'])('rejects a reconstructed network-path destination from %s', value => {
    expect(learningUrl(value)).toBe('/learn');
    expect(learningUrl(value, '/library')).toBe('/library');
  });
  it.each(['/a/..//example.org', '/a/%2e%2e//example.org'])('does not publish an external recommendation href after normalizing %s', url => {
    const parsed = parseLearningProgress({ ...progress, recommendations: [{ lesson_id: 'l1', title: 'Next lesson', reason: 'Fixture recommendation', url }] });
    expect(parsed.recommendations[0].url).toBe('/learn');
  });
  it.each([
    ['/learn/a/../b?module=dsa#evidence', '/learn/b?module=dsa#evidence'],
    ['/learn/a/%2e%2e/b', '/learn/b'],
    ['/interviews?report=A', '/interviews?report=A'],
    ['/learn/a//b', '/learn/a//b'],
    ['/learn?next=%2F%2Fexample.org', '/learn?next=%2F%2Fexample.org'],
  ])('preserves internal normalization of %s', (value, expected) => {
    const href = learningUrl(value);
    expect(href).toBe(expected);
    expect(new URL(href, 'https://viva.invalid').origin).toBe('https://viva.invalid');
  });
});
