import type { LearningCatalog, LearningLesson } from '../../services/learningApi';

export function moduleLabel(module: string): string {
  const labels: Record<string, string> = { dsa: 'Data structures & algorithms', cs: 'Computer science', aptitude: 'Aptitude & reasoning', system_design: 'System design' };
  return labels[module] ?? module;
}
export function allLessons(catalog: LearningCatalog): LearningLesson[] { return catalog.tracks.flatMap(track => track.lessons); }
export function lessonUrl(id: string): string { return `/learn/${encodeURIComponent(id)}`; }
export function missingPrerequisites(lesson: LearningLesson, completed: string[]): string[] { return lesson.prerequisites.filter(id => !completed.includes(id)); }
export function prerequisiteMessage(lesson: LearningLesson, catalog: LearningCatalog, completed: string[]): string {
  const lessons = allLessons(catalog);
  return `Complete ${missingPrerequisites(lesson, completed).map(id => lessons.find(item => item.id === id)?.title ?? id).join(', ')} to unlock.`;
}
