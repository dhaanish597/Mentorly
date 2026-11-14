import { lazy, Suspense, useEffect, useState } from 'react';
import App from './App';
import { FALLBACK_BRANDING } from './config/branding';
import { LandingPage } from './components/LandingPage';
import { ProductShell, navigate } from './components/ProductShell';
import { Icon, MentorPortrait } from './components/HorizonVisuals';
import { apiClient } from './services/apiClient';
import { draftKey, loadProductState, problemUrl } from './state/productState';
import type { ExerciseMetadata } from './types/api';
import { QuizOfTheDay } from './components/QuizOfTheDay';
import { DailyGoalsAndMissions } from './components/DailyGoalsAndMissions';
import { MeetYourTeachers } from './components/MeetYourTeachers';
import { DashboardGraphs } from './components/DashboardGraphs';
import { LiveLeaderboard } from './components/LiveLeaderboard';
import { AchievementsSection } from './components/AchievementsSection';
import { SmartRecommendations } from './components/SmartRecommendations';
import { DashboardGamificationData, LearningPathItem, gamificationApi } from './services/gamificationApi';
import { TEACHERS } from './config/teachers';
import './gamification.css';

const StudioApp = lazy(() => import('./StudioApp').then(module => ({ default: module.StudioApp })));

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function Shell({ children, current }: { children: React.ReactNode; current: string }) {
  return (
    <ProductShell current={current}>
      <main id="product-main">{children}</main>
    </ProductShell>
  );
}

function CollectionCards({ exercises, collections }: { exercises: ExerciseMetadata[]; collections: string[] }) {
  return (
    <div className="collection-grid">
      {collections.map((name, index) => (
        <article className={`product-card collection-card collection-${index % 3}`} key={name}>
          <div className="collection-card-band">
            <Icon name="code" />
            <h2>{name}</h2>
          </div>
          <div className="collection-card-body">
            <p>{exercises.filter(e => (e.collection ?? 'Python practice') === name).length} available problems</p>
            <p>Build the idea. Explain the mechanism. Inspect what happens.</p>
            <a className="collection-action" href={`/paths/${encodeURIComponent(name)}`}>
              Explore collection <Icon name="arrow" />
            </a>
          </div>
        </article>
      ))}
    </div>
  );
}

let cachedExercises: ExerciseMetadata[] | null = null;
let cachedGamification: DashboardGamificationData | null = null;
let cachedLearningPaths: LearningPathItem[] | null = null;

function ProductPage({ page }: { page: string }) {
  const [exercises, setExercises] = useState<ExerciseMetadata[]>(() => cachedExercises ?? []);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>(() => cachedExercises ? 'ready' : 'loading');
  const [retry, setRetry] = useState(0);
  const [product] = useState(loadProductState);
  const [gamification, setGamification] = useState<DashboardGamificationData | null>(() => cachedGamification);
  const [learningPaths, setLearningPaths] = useState<LearningPathItem[]>(() => cachedLearningPaths ?? []);

  useEffect(() => {
    let live = true;
    if (!cachedExercises || retry > 0) {
      setStatus('loading');
    }
    apiClient
      .getExercises()
      .then(data => {
        if (live) {
          cachedExercises = data;
          setExercises(data);
          setStatus('ready');
        }
      })
      .catch(() => {
        if (live) {
          cachedExercises = null;
          setStatus('error');
        }
      });
    return () => {
      live = false;
    };
  }, [retry]);

  useEffect(() => {
    let live = true;
    gamificationApi
      .getDashboard()
      .then(data => {
        if (live) {
          cachedGamification = data;
          setGamification(data);
        }
      })
      .catch(() => {});
    gamificationApi
      .getLearningPaths()
      .then(paths => {
        if (live) {
          cachedLearningPaths = paths;
          setLearningPaths(paths);
        }
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [retry]);

  const collections = Array.from(new Set(exercises.map(e => e.collection ?? 'Python practice')));
  const selectedCollection = page.startsWith('/paths/') ? safeDecode(page.slice('/paths/'.length)) : null;
  const validDrafts = Object.entries(product.drafts)
    .filter(([key]) => exercises.some(e => e.spec_versions.some(s => key === draftKey(e.exercise_id, s.spec_version))))
    .sort((a, b) => b[1].updatedAt - a[1].updatedAt);
  const latest = validDrafts[0];
  const resume = latest && exercises.find(e => e.spec_versions.some(s => latest[0] === draftKey(e.exercise_id, s.spec_version)));
  const resumeSpec = resume?.spec_versions.find(s => latest[0] === draftKey(resume.exercise_id, s.spec_version));
  const notice =
    status === 'loading' ? (
      <p role="status">Loading the practice library…</p>
    ) : status === 'error' ? (
      <div role="alert">
        The practice library is unavailable. <button onClick={() => setRetry(n => n + 1)}>Retry</button>
      </div>
    ) : null;

  let body: React.ReactNode;
  if (page === '/dashboard') {
    body = (
      <>
        <header className="product-page-heading">
          <p>Welcome to your workspace</p>
          <h1>What will you explore today?</h1>
          <span>One question. One conversation. A little more understanding.</span>
        </header>

        <section className="dashboard-hero">
          <div>
            <p className="hero-kicker">Your mentor is ready</p>
            <h2>{resume ? `Continue ${resume.title}` : 'Let’s think it through.'}</h2>
            <p>
              {resume
                ? 'Your saved draft is ready. Pick up where your thinking left off.'
                : 'Choose a problem, explain your idea, and build it together. Start with what you know.'}
            </p>
            <a
              className="product-button"
              href={resume && resumeSpec ? problemUrl(resume.exercise_id, resumeSpec.spec_version) : '/library'}
            >
              {resume ? 'Resume practice' : 'Browse problems'}
              <Icon name="arrow" />
            </a>
          </div>
          <div className="dashboard-mentor">
            <MentorPortrait eager />
            <p>“What would you check first?”</p>
          </div>
        </section>

        {gamification && (
          <div className="gamification-dashboard">
            <div className="dashboard-row-grid-2">
              <QuizOfTheDay
                initialQuiz={gamification.daily_quiz}
                countdownSeconds={gamification.countdown_seconds}
                onAnswerSubmitted={() => {
                  gamificationApi
                    .getDashboard()
                    .then(data => setGamification(data))
                    .catch(() => {});
                }}
              />
              <DailyGoalsAndMissions
                goal={gamification.daily_goal}
                streak={gamification.user_streak}
                missions={gamification.weekly_missions}
              />
            </div>

            <MeetYourTeachers />

            <DashboardGraphs data={gamification.graphs} />

            <div className="dashboard-row-grid-2">
              <LiveLeaderboard
                initialLeaderboard={gamification.leaderboard}
                userRank={gamification.user_rank}
              />
              <AchievementsSection achievements={gamification.achievements} />
            </div>

            {gamification.recommendations.length > 0 && (
              <SmartRecommendations recommendations={gamification.recommendations} />
            )}
          </div>
        )}

        <section className="product-section">
          <div className="section-title">
            <h2>Your learning paths</h2>
            <a href="/paths">
              View all paths <Icon name="arrow" />
            </a>
          </div>
          {notice}
          {status === 'ready' && <CollectionCards exercises={exercises} collections={collections.slice(0, 3)} />}
        </section>

        <section className="engineering-entry">
          <div>
            <Icon name="design" />
            <h2>Take the next step</h2>
            <p>Move from code to architectures, or explain a decision from your own repository.</p>
          </div>
          <a href="/studio" className="collection-action">
            Open design studio <Icon name="arrow" />
          </a>
        </section>

        <section className="product-section">
          <div className="section-title">
            <h2>Continue learning</h2>
            <a href="/progress">Your practice data</a>
          </div>
          {validDrafts.length ? (
            <ul className="recent-practice">
              {validDrafts.slice(0, 5).map(([key, draft]) => {
                const e = exercises.find(item => item.spec_versions.some(s => key === draftKey(item.exercise_id, s.spec_version)));
                const spec = e?.spec_versions.find(s => key === draftKey(e.exercise_id, s.spec_version));
                return e && spec ? (
                  <li key={key}>
                    <span className="recent-icon">
                      <Icon name="code" />
                    </span>
                    <a href={problemUrl(e.exercise_id, spec.spec_version)}>
                      {e.title}
                      <small>{spec.label}</small>
                    </a>
                    <span>{draft.status}</span>
                  </li>
                ) : null;
              })}
            </ul>
          ) : (
            <p className="quiet-empty">No saved practice yet. Your work will appear here as you begin.</p>
          )}
        </section>
      </>
    );
  } else if (selectedCollection) {
    body = (
      <>
        <header className="product-page-heading">
          <p>
            <a href="/paths">Learning paths</a>
          </p>
          <h1>{selectedCollection}</h1>
          <span>Go deeper, one conversation at a time.</span>
        </header>
        {notice}
        {status === 'ready' && (
          <div className="collection-grid">
            {exercises
              .filter(e => (e.collection ?? 'Python practice') === selectedCollection)
              .map(e => (
                <article className="product-card" key={e.exercise_id}>
                  <h2>{e.title}</h2>
                  <p>{e.description}</p>
                  <a className="collection-action" href={problemUrl(e.exercise_id, e.default_spec_version)}>
                    Open problem <Icon name="arrow" />
                  </a>
                </article>
              ))}
            {!collections.includes(selectedCollection) && (
              <p>
                No collection found. <a href="/paths">View learning paths</a>
              </p>
            )}
          </div>
        )}
      </>
    );
  } else if (page === '/paths') {
    body = (
      <>
        <header className="product-page-heading">
          <p>Learn at your own pace</p>
          <h1>Learning paths</h1>
          <span>Follow a concept from a small problem to a stronger explanation.</span>
        </header>

        {learningPaths.length > 0 && (
          <section className="product-section">
            <div className="section-title">
              <h2>All Curricula &amp; Mentors</h2>
              <span style={{ fontSize: '0.88rem', color: '#685a73' }}>
                Guided step-by-step by your domain AI mentor
              </span>
            </div>
            <div className="collection-grid">
              {learningPaths.map(p => {
                const t = TEACHERS[p.teacher_id as keyof typeof TEACHERS] ?? TEACHERS.astra;
                return (
                  <article
                    key={p.id}
                    className="product-card collection-card"
                    style={{ borderTop: `4px solid ${t.accentColor}` }}
                  >
                    <div className="collection-card-band">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span
                          style={{
                            width: '36px',
                            height: '36px',
                            borderRadius: '50%',
                            overflow: 'hidden',
                            background: '#fff8ef',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            border: '1.5px solid #e2dacd',
                            flexShrink: 0,
                          }}
                        >
                          <img
                            src={t.avatarUrl}
                            alt={t.name}
                            style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                          />
                        </span>
                        <div>
                          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>{p.title}</h2>
                          <span className="curriculum-mentor-subtitle">
                            Mentor: {t.name}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="collection-card-body">
                      <p>{p.description}</p>
                      <div className="curriculum-levels-meta">
                        {p.levels_count} Progressive Levels • {p.xp_reward} Total XP
                      </div>
                      <div className="curriculum-challenges-wrap">
                        {p.challenges.map(c => {
                          const isEasy = c.difficulty.toLowerCase() === 'easy';
                          const isMed = c.difficulty.toLowerCase() === 'medium';
                          const targetUrl = c.id === 'ex1_shortest_subarray'
                            ? '/practice/dsa-second-largest'
                            : t.defaultPath;
                          return (
                            <a
                              key={c.id}
                              href={targetUrl}
                              className="curriculum-challenge-pill"
                              title={`${c.difficulty} challenge • +${c.xp} XP • Click to practice`}
                            >
                              <span className={`curriculum-pill-dot ${isEasy ? 'easy' : isMed ? 'med' : 'hard'}`} aria-hidden="true" />
                              <span className="curriculum-pill-title">{c.title}</span>
                              <span className="curriculum-pill-xp">+{c.xp} XP</span>
                            </a>
                          );
                        })}
                      </div>
                      <a className="collection-action" href={t.defaultPath}>
                        Start Curriculum with {t.name} <Icon name="arrow" />
                      </a>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}

        {notice}
        {status === 'ready' && <CollectionCards exercises={exercises} collections={collections} />}
        <section className="engineering-entry">
          <div>
            <h2>From code to systems</h2>
            <p>Explore the authored bridge and progressive design scenarios.</p>
          </div>
          <a className="collection-action" href="/studio">
            Explore design studio <Icon name="arrow" />
          </a>
        </section>
      </>
    );
  } else {
    body = (
      <>
        <header className="product-page-heading">
          <p>Your practice</p>
          <h1>Progress</h1>
          <span>Your saved work, without invented scores.</span>
        </header>
        <div className="practice-counts">
          <article className="product-card">
            <Icon name="code" />
            <div>
              <h2>Saved drafts</h2>
              <p className="data-number">{Object.keys(product.drafts).length}</p>
            </div>
            <p>Drafts and in-progress work saved locally.</p>
          </article>
          <article className="product-card">
            <Icon name="book" />
            <div>
              <h2>Bookmarks</h2>
              <p className="data-number">{product.bookmarks.length}</p>
            </div>
            <p>Problems you have saved for later.</p>
          </article>
        </div>
        <section className="product-card quiet-card">
          <h2>Keep practicing</h2>
          <p>
            Practice checkpoints describe bounded evidence, not proven mastery. Session results stay inside each
            practice session.
          </p>
          <a className="collection-action" href="/library">
            Open the library <Icon name="arrow" />
          </a>
        </section>
      </>
    );
  }

  return <>{body}</>;
}

export default function ProductApp() {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);

  useEffect(() => {
    const handleGlobalClick = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement)?.closest?.('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (
        href &&
        href.startsWith('/') &&
        !href.startsWith('//') &&
        !anchor.hasAttribute('download') &&
        anchor.target !== '_blank' &&
        event.button === 0 &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey &&
        !event.shiftKey
      ) {
        event.preventDefault();
        navigate(href);
      }
    };
    document.addEventListener('click', handleGlobalClick);
    return () => document.removeEventListener('click', handleGlobalClick);
  }, []);

  useEffect(() => {
    document.title = FALLBACK_BRANDING.productName;
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    const apply = () => {
      const preference = loadProductState().theme;
      document.documentElement.dataset.theme =
        preference === 'system' ? (media?.matches ? 'dark' : 'light') : preference;
    };
    apply();
    media?.addEventListener?.('change', apply);
    return () => media?.removeEventListener?.('change', apply);
  }, []);

  if (path === '/') {
    let legacy = false;
    try {
      legacy = !!sessionStorage.getItem('vcc-session');
    } catch {
      /* Storage denial must not hide the public landing. */
    }
    return legacy && new URLSearchParams(location.search).get('resume') === '1' ? (
      <ProductShell current="/library" workspace>
        <App />
      </ProductShell>
    ) : (
      <LandingPage hasLegacySession={legacy} />
    );
  }

  const isWorkspace = path === '/library' || path.startsWith('/practice/') || path === '/studio' || path.startsWith('/studio/');
  const current = path.startsWith('/practice/')
    ? '/library'
    : path.startsWith('/studio')
    ? '/studio'
    : path.startsWith('/paths/')
    ? '/paths'
    : path;

  return (
    <ProductShell current={current} workspace={isWorkspace}>
      {path === '/dashboard' || path === '/paths' || path.startsWith('/paths/') || path === '/progress' ? (
        <ProductPage page={path} />
      ) : path === '/studio' || path.startsWith('/studio/') ? (
        <Suspense fallback={<p role="status">Loading design studio…</p>}>
          <StudioApp />
        </Suspense>
      ) : path === '/library' || path.startsWith('/practice/') ? (
        <App />
      ) : (
        <header className="product-page-heading">
          <h1>Page not found</h1>
          <p>That page is unavailable.</p>
          <a href="/dashboard">Go to your workspace</a>
        </header>
      )}
    </ProductShell>
  );
}
