import { Icon } from '../../components/HorizonVisuals';
import { loadProductState } from '../../state/productState';
import type { LearningProgress } from '../../services/learningApi';
import { LearningNotice } from '../curriculum/CurriculumPage';
import { useLearningData } from '../curriculum/useLearningData';
import { lessonUrl } from '../curriculum/curriculum';

export function LearningProgressSection({ compact = false }: { compact?: boolean }) {
  const data = useLearningData();
  return <section className="learning-progress-section" aria-labelledby={compact ? 'home-progress-title' : 'workspace-progress-title'}>
    <div className="section-title"><h2 id={compact ? 'home-progress-title' : 'workspace-progress-title'}>{compact ? 'Your learning, one step at a time' : 'Learning record'}</h2>{compact && <a href="/progress">View progress <Icon name="arrow" /></a>}</div>
    <LearningNotice loading={data.loading} error={data.error} onRetry={data.reload} politeError={compact} />
    {data.progress && !data.error && <ProgressRecord progress={data.progress} compact={compact} />}
  </section>;
}
function ProgressRecord({ progress, compact }: { progress: LearningProgress; compact: boolean }) {
  const started = progress.attempts + progress.practice_sessions + progress.interviews_completed + progress.lessons_completed > 0;
  return <>
    {!started ? <div className="learning-beginner"><Icon name="compass" /><div><h3>Your first lesson is a good place to start.</h3><p>No completed lessons or recorded practice yet. There’s no score to catch up with—just a next step.</p><a href="/learn" className="collection-action">Explore the curriculum <Icon name="arrow" /></a></div></div> : <div className="progress-record"><p>Progress from recorded workspace activity, not an estimated score.</p><dl className="progress-count-list"><div><dt>Lessons completed</dt><dd>{progress.lessons_completed}</dd></div><div><dt>Practice sessions</dt><dd>{progress.practice_sessions}</dd></div><div><dt>Interviews completed</dt><dd>{progress.interviews_completed}</dd></div>{!compact && <><div><dt>Answer attempts</dt><dd>{progress.attempts}</dd></div><div><dt>Topics with recorded mastery</dt><dd>{progress.topics_mastered}</dd></div><div><dt>Study time</dt><dd>{Math.floor(progress.study_seconds / 60)} minutes</dd></div><div><dt>Current study streak</dt><dd>{progress.streak} {progress.streak === 1 ? 'day' : 'days'}</dd></div></>}</dl></div>}
    {progress.recommendations.length > 0 && <section className="progress-recommendations"><h3>A useful next step</h3><ul>{progress.recommendations.slice(0, compact ? 2 : 5).map(item => <li key={item.lesson_id}><a href={lessonUrl(item.lesson_id)}>{item.title}</a><p>{item.reason}</p></li>)}</ul></section>}
    {!compact && <div className="progress-history"><section><h3>Earned achievements</h3>{progress.achievements.length ? <ul className="earned-achievements">{progress.achievements.map(item => <li key={item.id}><Icon name="award" /><div><strong>{item.title}</strong><small>Earned {formatDate(item.earned_at)}</small></div></li>)}</ul> : <p>No achievements earned yet. They appear only after a recorded milestone.</p>}</section><section><h3>Recent activity</h3>{progress.recent_activity.length ? <ul className="progress-activity">{progress.recent_activity.map((item, index) => <li key={item.id ?? `${index}:${item.title}`}><span>{item.title}</span>{item.occurred_at && <small>{formatDate(item.occurred_at)}</small>}</li>)}</ul> : <p>Your recorded learning activity will appear here.</p>}</section></div>}
  </>;
}
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? 'recorded milestone' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); }
export function ProgressPage() {
  const product = loadProductState();
  return <><header className="product-page-heading"><p>The evidence of your effort</p><h1>Progress</h1><span>Real lessons, practice, and milestones from this workspace.</span></header><LearningProgressSection />
    <section className="local-practice-record"><h2>Saved on this device</h2><dl className="progress-count-list"><div><dt>Saved drafts</dt><dd>{Object.keys(product.drafts).length}</dd></div><div><dt>Bookmarks</dt><dd>{product.bookmarks.length}</dd></div></dl><p>Practice checkpoints describe bounded evidence, not proven mastery. Local drafts are not counted as completed lessons.</p><a href="/library" className="collection-action">Open the library <Icon name="arrow" /></a></section>
  </>;
}
