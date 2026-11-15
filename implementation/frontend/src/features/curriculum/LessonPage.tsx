import { Icon } from '../../components/HorizonVisuals';
import { LearningNotice } from './CurriculumPage';
import { allLessons, lessonUrl, missingPrerequisites, prerequisiteMessage } from './curriculum';
import { LessonPractice } from './LessonPractice';
import { useLearningData } from './useLearningData';

export function LessonPage({ lessonId, search = '' }: { lessonId: string; search?: string }) {
  const data = useLearningData();
  const lessons = data.catalog ? allLessons(data.catalog) : [];
  const lesson = lessons.find(item => item.id === lessonId);
  const track = data.catalog?.tracks.find(item => item.lessons.some(item => item.id === lessonId));
  const completed = data.progress?.completed_lesson_ids ?? [];
  const locked = lesson && missingPrerequisites(lesson, completed).length > 0;
  const index = lessons.findIndex(item => item.id === lessonId);
  const next = lessons[index + 1];
  const previous = lessons[index - 1];
  if (!data.loading && !data.error && !lesson) return <header className="product-page-heading"><h1>Lesson not found</h1><p>This lesson is not in the current curriculum.</p><a href="/learn">Back to curriculum</a></header>;
  return <>
    <LearningNotice loading={data.loading} error={data.error} onRetry={data.reload} />
    {lesson && data.catalog && data.progress && data.workspace && !data.error && <>
      <header className="product-page-heading"><p><a href="/learn">Curriculum</a> / {track?.title}</p><h1>{lesson.title}</h1><span>{lesson.difficulty} · {lesson.estimated_minutes} minutes · {completed.includes(lesson.id) ? 'Completed' : 'Learn at your own pace'}</span></header>
      <div className="lesson-layout"><aside className="lesson-outline"><p className="learning-eyebrow">In this track</p><nav aria-label="Lesson navigation">{track?.lessons.map(item => {
        const itemLocked = missingPrerequisites(item, completed).length > 0;
        return itemLocked ? <span key={item.id}>{item.title}<small>Locked</small></span> : <a key={item.id} href={lessonUrl(item.id)} aria-current={item.id === lesson.id ? 'page' : undefined}>{item.title}<small>{completed.includes(item.id) ? 'Completed' : 'Ready'}</small></a>;
      })}</nav><a className="collection-action" href="/learn">All modules <Icon name="arrow" /></a></aside>
      <div className="lesson-content">{locked ? <section className="learning-empty"><h2>Build the foundation first</h2><p>{prerequisiteMessage(lesson, data.catalog, completed)}</p><a href="/learn">Back to curriculum</a></section> : <>
        <section className="lesson-reading"><p className="learning-eyebrow">What you’ll understand</p><ul>{lesson.objectives.map(item => <li key={item}>{item}</li>)}</ul><h2>The idea</h2><p className="lesson-explanation">{lesson.explanation}</p><h3>A worked example</h3><pre><code>{lesson.example}</code></pre></section>
        <LessonPractice key={lesson.id} lesson={lesson} workspace={data.workspace} initialSessionId={new URLSearchParams(search).get('session') ?? undefined} onComplete={data.reload} />
        <section className="lesson-transfer"><div><h2>Take it into practice</h2><p>Use this idea in a problem, and explain the decisions you make.</p></div><a href={lesson.practice_url} className="collection-action">Open practice <Icon name="arrow" /></a></section>
      </>}
      <nav className="lesson-pagination" aria-label="Previous and next lesson">{previous && !missingPrerequisites(previous, completed).length && <a href={lessonUrl(previous.id)}>Previous lesson: {previous.title}</a>}{next && !missingPrerequisites(next, completed).length && <a href={lessonUrl(next.id)}>Next lesson: {next.title} <Icon name="arrow" /></a>}</nav></div></div>
    </>}
  </>;
}
