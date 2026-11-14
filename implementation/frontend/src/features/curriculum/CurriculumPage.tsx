import { Icon } from '../../components/HorizonVisuals';
import type { LearningCatalog, LearningProgress } from '../../services/learningApi';
import { allLessons, lessonUrl, missingPrerequisites, prerequisiteMessage } from './curriculum';
import { useLearningData } from './useLearningData';

export function LearningNotice({ loading, error, onRetry }: { loading: boolean; error: string | null; onRetry: () => void }) {
  if (error) return <div className="learning-notice" role="alert"><p>{error}</p><button type="button" onClick={onRetry}>Retry learning</button></div>;
  return loading ? <p className="learning-notice" role="status">Loading your learning workspace…</p> : null;
}
export function CurriculumPage() {
  const data = useLearningData();
  return <>
    <header className="product-page-heading"><p>Small steps. Strong foundations.</p><h1>Your curriculum</h1><span>Learn the idea, test your understanding, then put it into practice.</span></header>
    <LearningNotice loading={data.loading} error={data.error} onRetry={data.reload} />
    {data.catalog && data.progress && !data.error && <Curriculum catalog={data.catalog} progress={data.progress} />}
  </>;
}
function Curriculum({ catalog, progress }: { catalog: LearningCatalog; progress: LearningProgress }) {
  const lessons = allLessons(catalog);
  const completed = lessons.filter(lesson => progress.completed_lesson_ids.includes(lesson.id)).length;
  const next = lessons.find(lesson => !progress.completed_lesson_ids.includes(lesson.id) && !missingPrerequisites(lesson, progress.completed_lesson_ids).length);
  const modules = [...new Set(catalog.tracks.map(track => track.module))];
  return <div className="learning-layout">
    <aside className="learning-outline"><p className="learning-eyebrow">Your route forward</p><p>{completed} of {lessons.length} lessons completed</p>
      <nav aria-label="Curriculum modules">{modules.map((module, index) => <a key={module} href={`#module-${index}`}><span>{String(index + 1).padStart(2, '0')}</span>{module}</a>)}</nav>
      <a href="/paths" className="collection-action">Browse practice collections <Icon name="arrow" /></a>
    </aside>
    <div className="learning-tracks">
      {next && <section className="learning-next"><div><p className="learning-eyebrow">{completed ? 'Continue your journey' : 'Begin here'}</p><h2>{next.title}</h2><p>{next.estimated_minutes} minutes · {next.difficulty}</p></div><a href={lessonUrl(next.id)} className="product-button">{completed ? 'Continue learning' : 'Start learning'} <Icon name="arrow" /></a></section>}
      {!lessons.length && <section className="learning-empty"><h2>No lessons published yet</h2><p>The curriculum will appear here when lessons are available.</p><a href="/library">Explore practice problems</a></section>}
      {modules.map((module, index) => <section key={module} id={`module-${index}`} className="learning-module"><p className="learning-eyebrow">Module {index + 1} · {module}</p>
        {catalog.tracks.filter(track => track.module === module).map(track => <article className="learning-track" key={track.id}><header><h2>{track.title}</h2><p>{track.description}</p></header>
          <ol className="lesson-list">{track.lessons.map(lesson => {
            const locked = missingPrerequisites(lesson, progress.completed_lesson_ids).length > 0;
            const complete = progress.completed_lesson_ids.includes(lesson.id);
            return <li key={lesson.id} className={locked ? 'lesson-locked' : complete ? 'lesson-complete' : ''}><span className="lesson-marker" aria-hidden="true"><Icon name={locked ? 'lock' : complete ? 'check' : 'book'} /></span><div>
              {locked ? <h3>{lesson.title}</h3> : <h3><a href={lessonUrl(lesson.id)}>{lesson.title}</a></h3>}
              <p>{lesson.difficulty} · {lesson.estimated_minutes} minutes</p>
              {locked && <small>{prerequisiteMessage(lesson, catalog, progress.completed_lesson_ids)}</small>}
            </div><span className="lesson-state">{locked ? 'Locked' : complete ? 'Completed' : 'Ready'}</span></li>;
          })}</ol>
        </article>)}
      </section>)}
    </div>
  </div>;
}
