import { lazy, Suspense, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import App from './App';
import { FALLBACK_BRANDING } from './config/branding';
import { LandingPage } from './components/LandingPage';
import { ProductShell, navigate } from './components/ProductShell';
import { Icon, MentorPortrait } from './components/HorizonVisuals';
import { MeetYourTeachers } from './components/MeetYourTeachers';
import { apiClient } from './services/apiClient';
import { draftKey, loadProductState, problemUrl } from './state/productState';
import type { ExerciseMetadata } from './types/api';
import { CurriculumPage } from './features/curriculum/CurriculumPage';
import { LessonPage } from './features/curriculum/LessonPage';
import { SettingsPage } from './features/settings/SettingsPage';
import { LearningProgressSection, ProgressPage } from './features/progress/ProgressPage';
import './gamification.css';
import './product-learning.css';

const StudioApp = lazy(() => import('./StudioApp').then(module => ({ default: module.StudioApp })));
function safeDecode(value: string): string { try { return decodeURIComponent(value); } catch { return value; } }
export function Shell({ children, current }: { children: ReactNode; current: string }) {
  return <ProductShell current={current}><main id="product-main">{children}</main></ProductShell>;
}
function CollectionCards({ exercises, collections }: { exercises: ExerciseMetadata[]; collections: string[] }) {
  return <div className="collection-grid">{collections.map((name, index) => <article className={`product-card collection-card collection-${index % 3}`} key={name}>
    <div className="collection-card-band"><Icon name="code" /><h2>{name}</h2></div><div className="collection-card-body"><p>{exercises.filter(e => (e.collection ?? 'Python practice') === name).length} available problems</p><p>Build the idea. Explain the mechanism. Inspect what happens.</p><a className="collection-action" href={`/paths/${encodeURIComponent(name)}`}>Explore collection <Icon name="arrow" /></a></div>
  </article>)}</div>;
}
let cachedExercises: ExerciseMetadata[] | null = null;
function ProductPage({ page }: { page: string }) {
  const [exercises, setExercises] = useState<ExerciseMetadata[]>(() => cachedExercises ?? []);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(() => cachedExercises ? 'ready' : 'loading');
  const [retry, setRetry] = useState(0);
  const [product] = useState(loadProductState);
  useEffect(() => {
    let live = true;
    if (!cachedExercises || retry > 0) setStatus('loading');
    apiClient.getExercises().then(data => { if (live) { cachedExercises = data; setExercises(data); setStatus('ready'); } }).catch(() => { if (live) { cachedExercises = null; setStatus('error'); } });
    return () => { live = false; };
  }, [retry]);
  const collections = Array.from(new Set(exercises.map(e => e.collection ?? 'Python practice')));
  const selectedCollection = page.startsWith('/paths/') ? safeDecode(page.slice('/paths/'.length)) : null;
  const validDrafts = Object.entries(product.drafts).filter(([key]) => exercises.some(e => e.spec_versions.some(s => key === draftKey(e.exercise_id, s.spec_version)))).sort((a, b) => b[1].updatedAt - a[1].updatedAt);
  const latest = validDrafts[0];
  const resume = latest && exercises.find(e => e.spec_versions.some(s => latest[0] === draftKey(e.exercise_id, s.spec_version)));
  const resumeSpec = resume?.spec_versions.find(s => latest[0] === draftKey(resume.exercise_id, s.spec_version));
  const notice = status === 'loading' ? <p role="status">Loading the practice library…</p> : status === 'error' ? <div role="alert">The practice library is unavailable. <button type="button" onClick={() => setRetry(n => n + 1)}>Retry</button></div> : null;
  if (page === '/progress') return <ProgressPage />;
  if (selectedCollection) return <>
    <header className="product-page-heading"><p><a href="/paths">Learning paths</a></p><h1>{selectedCollection}</h1><span>Go deeper, one conversation at a time.</span></header>{notice}
    {status === 'ready' && <div className="collection-grid">{exercises.filter(e => (e.collection ?? 'Python practice') === selectedCollection).map(e => <article className="product-card" key={e.exercise_id}><h2>{e.title}</h2><p>{e.description}</p><a className="collection-action" href={problemUrl(e.exercise_id, e.default_spec_version)}>Open problem <Icon name="arrow" /></a></article>)}{!collections.includes(selectedCollection) && <p>No collection found. <a href="/paths">View learning paths</a></p>}</div>}
  </>;
  if (page === '/paths') return <>
    <header className="product-page-heading"><p>Learn at your own pace</p><h1>Learning paths</h1><span>Practice collections for exploring an idea from different angles.</span></header>
    <section className="learning-next"><div><p className="learning-eyebrow">Looking for a guided start?</p><h2>Build your foundations</h2><p>Published lessons, clear prerequisites, and practice that remembers your progress.</p></div><a href="/learn" className="product-button">Open curriculum <Icon name="arrow" /></a></section>
    {notice}{status === 'ready' && <CollectionCards exercises={exercises} collections={collections} />}
    <section className="engineering-entry"><div><h2>From code to systems</h2><p>Explore the authored bridge and progressive design scenarios.</p></div><a className="collection-action" href="/studio">Explore design studio <Icon name="arrow" /></a></section>
  </>;
  return <>
    <header className="product-page-heading"><p>Welcome to your workspace</p><h1>What will you explore today?</h1><span>One question. One conversation. A little more understanding.</span></header>
    <section className="dashboard-hero"><div><p className="hero-kicker">Your mentor is ready</p><h2>{resume ? `Continue ${resume.title}` : 'Let’s think it through.'}</h2><p>{resume ? 'Your saved draft is ready. Pick up where your thinking left off.' : 'Choose a problem, explain your idea, and build it together. Start with what you know.'}</p><a className="product-button" href={resume && resumeSpec ? problemUrl(resume.exercise_id, resumeSpec.spec_version) : '/library'}>{resume ? 'Resume practice' : 'Browse problems'}<Icon name="arrow" /></a></div><div className="dashboard-mentor"><MentorPortrait eager /><p>“What would you check first?”</p></div></section>
    <LearningProgressSection compact /><MeetYourTeachers />
    <section className="product-section"><div className="section-title"><h2>Your practice collections</h2><a href="/paths">View all paths <Icon name="arrow" /></a></div>{notice}{status === 'ready' && <CollectionCards exercises={exercises} collections={collections.slice(0, 3)} />}</section>
    <section className="engineering-entry"><div><Icon name="design" /><h2>Take the next step</h2><p>Move from code to architectures, or explain a decision from your own repository.</p></div><a href="/studio" className="collection-action">Open design studio <Icon name="arrow" /></a></section>
    <section className="product-section"><div className="section-title"><h2>Continue learning</h2><a href="/progress">Your practice data</a></div>{validDrafts.length ? <ul className="recent-practice">{validDrafts.slice(0, 5).map(([key, draft]) => { const exercise = exercises.find(item => item.spec_versions.some(s => key === draftKey(item.exercise_id, s.spec_version))); const spec = exercise?.spec_versions.find(s => key === draftKey(exercise.exercise_id, s.spec_version)); return exercise && spec ? <li key={key}><span className="recent-icon"><Icon name="code" /></span><a href={problemUrl(exercise.exercise_id, spec.spec_version)}>{exercise.title}<small>{spec.label}</small></a><span>{draft.status}</span></li> : null; })}</ul> : <p className="quiet-empty">No saved practice yet. Your work will appear here as you begin.</p>}</section>
  </>;
}

export default function ProductApp() {
  const [url, setUrl] = useState(() => window.location.pathname + window.location.search);
  const path = url.split('?')[0];
  const search = url.includes('?') ? url.slice(url.indexOf('?')) : '';
  useEffect(() => {
    const update = () => setUrl(window.location.pathname + window.location.search);
    window.addEventListener('popstate', update);
    window.addEventListener('viva:route-change', update);
    return () => { window.removeEventListener('popstate', update); window.removeEventListener('viva:route-change', update); };
  }, []);
  useEffect(() => {
    const handleGlobalClick = (event: MouseEvent) => {
      if (event.defaultPrevented) return;
      const anchor = (event.target as HTMLElement)?.closest?.('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (href && href.startsWith('/') && !href.startsWith('//') && !anchor.hasAttribute('download') && (!anchor.target || anchor.target === '_self') && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey) { event.preventDefault(); navigate(href); }
    };
    document.addEventListener('click', handleGlobalClick);
    return () => document.removeEventListener('click', handleGlobalClick);
  }, []);
  useEffect(() => {
    document.title = FALLBACK_BRANDING.productName;
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    const apply = () => { const preference = loadProductState().theme; document.documentElement.dataset.theme = preference === 'system' ? media?.matches ? 'dark' : 'light' : preference; };
    apply(); media?.addEventListener?.('change', apply); window.addEventListener('viva:preferences-changed', apply);
    return () => { media?.removeEventListener?.('change', apply); window.removeEventListener('viva:preferences-changed', apply); };
  }, []);
  useEffect(() => {
    const heading = document.querySelector<HTMLElement>('.product-main h1');
    if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
  }, [path]);
  if (path === '/') {
    let legacy = false;
    try { legacy = !!sessionStorage.getItem('vcc-session'); } catch { /* Storage denial must not hide the landing. */ }
    return legacy && new URLSearchParams(search).get('resume') === '1' ? <ProductShell current="/library" workspace><App /></ProductShell> : <LandingPage hasLegacySession={legacy} />;
  }
  const isWorkspace = path === '/library' || path.startsWith('/practice/') || path === '/studio' || path.startsWith('/studio/');
  const current = path.startsWith('/practice/') ? '/library' : path.startsWith('/studio') ? '/studio' : path.startsWith('/paths/') ? '/paths' : path.startsWith('/learn/') ? '/learn' : path;
  return <ProductShell current={current} workspace={isWorkspace}>
    {path === '/dashboard' || path === '/paths' || path.startsWith('/paths/') || path === '/progress' ? <ProductPage page={path} />
      : path === '/learn' ? <CurriculumPage />
      : path.startsWith('/learn/') ? <LessonPage key={path} lessonId={safeDecode(path.slice('/learn/'.length))} />
      : path === '/settings' ? <SettingsPage search={search} />
      : path === '/studio' || path.startsWith('/studio/') ? <Suspense fallback={<p role="status">Loading design studio…</p>}><StudioApp /></Suspense>
      : path === '/library' || path.startsWith('/practice/') ? <App />
      : <header className="product-page-heading"><h1>Page not found</h1><p>That page is unavailable.</p><a href="/dashboard">Go to your workspace</a></header>}
  </ProductShell>;
}
