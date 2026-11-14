import type { LearningCatalog, LearningLesson } from '../../services/learningApi';

export function allLessons(catalog: LearningCatalog): LearningLesson[] { return catalog.tracks.flatMap(track => track.lessons); }
export function lessonUrl(id: string): string { return `/learn/${encodeURIComponent(id)}`; }
export function missingPrerequisites(lesson: LearningLesson, completed: string[]): string[] { return lesson.prerequisites.filter(id => !completed.includes(id)); }
export function prerequisiteMessage(lesson: LearningLesson, catalog: LearningCatalog, completed: string[]): string {
  const lessons = allLessons(catalog);
  return `Complete ${missingPrerequisites(lesson, completed).map(id => lessons.find(item => item.id === id)?.title ?? id).join(', ')} to unlock.`;
}
