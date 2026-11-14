import type { MouseEvent } from 'react';
import type { ExerciseMetadata } from '../types/api';
import { catalogTopics, type CatalogExercise } from '../catalog/metadata';
import { draftKey, filterExercises, problemUrl, type ProductRoute, type ProductState } from '../state/productState';

type Props = {
  exercises: ExerciseMetadata[];
  product: ProductState;
  route: ProductRoute;
  onRouteChange: (route: ProductRoute) => void;
  onOpen: (problem: string, spec: string) => void;
  onBookmark: (problem: string) => void;
};
export function ProblemLibrary({ exercises, product, route, onRouteChange, onOpen, onBookmark }: Props) {
  const progress = route.progress ?? 'all';
  const filtered = filterExercises(exercises, route, product.bookmarks, product.drafts);
  const difficulties = [...new Set(exercises.map(exercise => exercise.difficulty))];
  const recent = Object.entries(product.drafts).sort(([, a], [, b]) => b.updatedAt - a.updatedAt).find(([key]) => exercises.some(e => e.spec_versions.some(s => draftKey(e.exercise_id, s.spec_version) === key)));
  const resume = recent && exercises.find(e => e.spec_versions.some(s => draftKey(e.exercise_id, s.spec_version) === recent[0]));
  const resumeSpec = resume?.spec_versions.find(s => draftKey(resume.exercise_id, s.spec_version) === recent?.[0]);
  function open(event: MouseEvent<HTMLAnchorElement>, exercise: string, spec: string): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); onOpen(exercise, spec);
  }
  return <section className="library-page" aria-labelledby="library-title">
    <div className="library-intro"><div><p className="eyebrow">The practice library</p><h1 id="library-title" tabIndex={-1}>Reason it out.<br />Then make it work.</h1><p>Small Python problems. Thoughtful explanations. Evidence you can inspect.</p></div><div className="library-notebook"><strong>{exercises.length} {exercises.length === 1 ? 'problem' : 'problems'}</strong><span>Explain → predict → confirm → verify</span><p>Progress means a bounded practice checkpoint, never proven mastery.</p>{resume && resumeSpec && <a href={problemUrl(resume.exercise_id, resumeSpec.spec_version)} onClick={e => open(e, resume.exercise_id, resumeSpec.spec_version)}>Resume {resume.title} <span aria-hidden="true">→</span></a>}</div></div>
    <form className="library-filters" role="search" onSubmit={event => event.preventDefault()}>
      <label className="library-search">Search problems<input type="search" value={route.query} onChange={e => onRouteChange({ ...route, query: e.target.value })} placeholder="Title, concept, or function…" /></label>
      <label>Difficulty<select value={route.difficulty} onChange={e => onRouteChange({ ...route, difficulty: e.target.value })}><option value="">All levels</option>{difficulties.map(d => <option key={d} value={d}>{d}</option>)}</select></label>
      <details className="library-filter-more"><summary>More filters</summary><div><label>Topic<select value={route.topic} onChange={e => onRouteChange({ ...route, topic: e.target.value })}><option value="">All topics</option>{catalogTopics(exercises).map(topic => <option key={topic} value={topic}>{topic}</option>)}</select></label>
      <label>Progress<select value={progress} onChange={e => onRouteChange({ ...route, progress: e.target.value as ProductRoute['progress'] })}><option value="all">All progress</option><option value="not_started">Not started</option><option value="draft">Drafts</option><option value="in_progress">In progress</option></select></label>
      <label>Sort<select value={route.sort} onChange={e => onRouteChange({ ...route, sort: e.target.value as ProductRoute['sort'] })}><option value="recommended">Library order</option><option value="title">Title A–Z</option><option value="difficulty">Difficulty</option></select></label>
      <button type="button" aria-pressed={route.bookmarked} onClick={() => onRouteChange({ ...route, bookmarked: !route.bookmarked })}>Bookmarks{route.bookmarked ? ' ✓' : ''}</button></div></details>
    </form>
    <div className="library-result-heading"><p aria-live="polite">Showing {filtered.length} of {exercises.length} problems</p>{(route.query || route.topic || route.difficulty || route.bookmarked || progress !== 'all') && <button type="button" onClick={() => onRouteChange({ ...route, query: '', topic: '', difficulty: '', bookmarked: false, progress: 'all' })}>Clear filters</button>}<span>Drafts stay on this device</span></div>
    {filtered.length ? <ol className="problem-list">{filtered.map((exercise, index) => {
      const latestDraftSpec = exercise.spec_versions.filter(s => product.drafts[draftKey(exercise.exercise_id, s.spec_version)]).sort((a,b) => product.drafts[draftKey(exercise.exercise_id,b.spec_version)].updatedAt - product.drafts[draftKey(exercise.exercise_id,a.spec_version)].updatedAt)[0];
      const spec = latestDraftSpec?.spec_version ?? exercise.default_spec_version;
      const draft = product.drafts[draftKey(exercise.exercise_id, spec)];
      const bookmarked = product.bookmarks.includes(exercise.exercise_id);
      return <li key={exercise.exercise_id} data-testid={`exercise-card-${exercise.exercise_id}`}><span className="problem-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span><div className="problem-list-content"><div className="problem-list-title"><a href={problemUrl(exercise.exercise_id, spec)} onClick={e => open(e, exercise.exercise_id, spec)}>{exercise.title}</a><span className="difficulty">{exercise.difficulty}</span>{draft && <span className="draft-label">{draft.status}{latestDraftSpec && exercise.spec_versions.length > 1 ? ` · ${latestDraftSpec.label}` : ''}</span>}</div><p>{exercise.description}</p><div className="problem-tags">{exercise.core_concepts.slice(0, 4).map(concept => <span key={concept}>{concept}</span>)}<span>{(exercise as CatalogExercise).collection ?? 'Python practice'}</span></div></div><div className="problem-list-actions"><button type="button" aria-label={`${bookmarked ? 'Remove bookmark for' : 'Bookmark'} ${exercise.title}`} aria-pressed={bookmarked} onClick={() => onBookmark(exercise.exercise_id)}><span aria-hidden="true">{bookmarked ? '◆' : '◇'}</span></button><a aria-label={`Open ${exercise.title}`} href={problemUrl(exercise.exercise_id, spec)} onClick={e => open(e, exercise.exercise_id, spec)}>Open <span aria-hidden="true">↗</span></a></div></li>;
    })}</ol> : <div className="library-empty"><h2>{exercises.length ? 'No matching problems' : 'No problems available yet'}</h2><p>{exercises.length ? 'Try a different search or clear your filters.' : 'The library is supplied by the coordinator. Retry loading when it is available.'}</p></div>}
  </section>;
}
