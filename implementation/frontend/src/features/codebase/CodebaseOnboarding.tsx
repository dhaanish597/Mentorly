import { useEffect, useRef, useState } from 'react';
import { Icon } from '../../components/HorizonVisuals';
import type { Workspace } from '../../studioApi';
import { ingestRepoUrl, ingestGoldenRepo, pollSnapshot, createSession, type CodebaseSession, type CodebaseSnapshot } from './codebaseApi';

export type CodebaseOnboardingProps = {
  workspace: Workspace;
  onSessionReady: (session: CodebaseSession) => void;
  onViewHistory?: () => void;
  hasExistingSessions?: boolean;
};

const SAMPLE_REPOS = [
  { label: 'FastAPI (Python)', url: 'https://github.com/fastapi/fastapi' },
  { label: 'Flask (Python)', url: 'https://github.com/pallets/flask' },
  { label: 'Architecture Baseline', url: 'REPO-EXP-01', isGolden: true },
];

type PendingAttempt = { identity: string; key: string; snapshot?: CodebaseSnapshot };
const PENDING_KEY = 'viva-codebase-pending-v1';
function readPending(): PendingAttempt | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(PENDING_KEY) ?? 'null');
    return value && typeof value.identity === 'string' && typeof value.key === 'string' ? value : null;
  } catch { return null; }
}
function savePending(value: PendingAttempt | null): boolean {
  try {
    if (value) sessionStorage.setItem(PENDING_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(PENDING_KEY);
    return true;
  } catch { return false; }
}
function ownsPending(attempt: PendingAttempt): boolean {
  const stored = readPending();
  return stored?.identity === attempt.identity && stored.key === attempt.key;
}
async function workspaceFingerprint(token: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

export function CodebaseOnboarding({
  workspace,
  onSessionReady,
  onViewHistory,
  hasExistingSessions = false,
}: CodebaseOnboardingProps) {
  const [url, setUrl] = useState(() => {
    try { return JSON.parse(readPending()?.identity ?? '[]')[2] ?? ''; } catch { return ''; }
  });
  const [status, setStatus] = useState<'idle' | 'validating' | 'indexing' | 'preparing' | 'error'>('idle');
  const [progressMsg, setProgressMsg] = useState('');
  const [error, setError] = useState<string | null>(null);

  const pending = useRef<PendingAttempt | null>(readPending());
  const inFlight = useRef(false);
  const mounted = useRef(false);
  const currentWorkspace = useRef(workspace);
  currentWorkspace.current = workspace;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);


  async function handleStartLearning(targetUrl?: string) {
    if (inFlight.current) return;
    const inputUrl = (targetUrl || url).trim();
    if (!inputUrl) {
      setError('Please enter a GitHub repository URL.');
      return;
    }

    const isGolden = inputUrl === 'REPO-EXP-01' || inputUrl === 'REPO-EXP-02';
    if (!isGolden && !/github\.com\/[^/]+\/[^/]+/i.test(inputUrl)) {
      setError('Please provide a valid GitHub repository URL (e.g. https://github.com/owner/repository).');
      return;
    }

    inFlight.current = true;
    let fingerprint: string;
    try { fingerprint = await workspaceFingerprint(workspace.token); }
    catch { inFlight.current = false; setError('Unable to securely prepare this request.'); return; }
    if (!mounted.current || currentWorkspace.current.id !== workspace.id || currentWorkspace.current.token !== workspace.token) { inFlight.current = false; return; }
    const identity = JSON.stringify([workspace.id, fingerprint, inputUrl]);
    if (pending.current?.identity !== identity) pending.current = { identity, key: crypto.randomUUID() };
    if (!savePending(pending.current)) { inFlight.current = false; setError('Tab storage is required to safely retry this request.'); return; }
    const attempt = pending.current;
    const current = () => mounted.current && currentWorkspace.current.id === workspace.id && currentWorkspace.current.token === workspace.token;
    inFlight.current = true;
    setError(null);
    setStatus('validating');
    setProgressMsg('Validating repository and connecting to GitHub…');

    try {
      let snapshot = attempt.snapshot;
      const isGolden = inputUrl === 'REPO-EXP-01' || inputUrl === 'REPO-EXP-02';

      if (snapshot) {
        setProgressMsg('Resuming repository preparation…');
      } else if (isGolden) {
        setProgressMsg('Loading curated architectural snapshot…');
        snapshot = await ingestGoldenRepo(workspace, inputUrl);
      } else {
        setProgressMsg('Downloading repository snapshot and parsing files…');
        snapshot = await ingestRepoUrl(workspace, inputUrl);
      }

      attempt.snapshot = { snapshot_id: snapshot.snapshot_id, status: snapshot.status, files_indexed: snapshot.files_indexed, total_files: snapshot.total_files, failure_code: snapshot.failure_code };
      if (ownsPending(attempt)) savePending(attempt);
      if (!current()) return;
      setStatus('indexing');
      setProgressMsg('Indexing directory structure, symbols, and dependencies…');

      // Poll until READY or FAILED
      let attempts = 0;
      while (snapshot.status === 'QUEUED' || snapshot.status === 'INDEXING') {
        attempts++;
        if (attempts > 60) {
          throw new Error('Indexing took longer than expected. Please try again.');
        }
        await new Promise((r) => setTimeout(r, 1200));
        if (!current()) return;
        snapshot = await pollSnapshot(workspace, snapshot.snapshot_id);
        attempt.snapshot = { snapshot_id: snapshot.snapshot_id, status: snapshot.status, files_indexed: snapshot.files_indexed, total_files: snapshot.total_files, failure_code: snapshot.failure_code };
        if (ownsPending(attempt)) savePending(attempt);
        if (!current()) return;
        if (snapshot.status === 'INDEXING') {
          const count = snapshot.files_indexed ?? 0;
          const total = snapshot.total_files ?? 0;
          setProgressMsg(`Analyzing code: indexed ${count} of ${total || 'all'} files…`);
        }
      }

      if (snapshot.status === 'FAILED') {
        pending.current = null;
        if (ownsPending(attempt)) savePending(null);
        throw new Error(snapshot.failure_code ? `Ingestion failed: ${snapshot.failure_code}` : 'Failed to ingest repository.');
      }

      setStatus('preparing');
      setProgressMsg('Initializing your AI mentor and generating context…');

      // Extract repo name
      let repoName = 'repository';
      if (!isGolden) {
        const parts = inputUrl.replace(/\/$/, '').split('/');
        repoName = parts.slice(-2).join('/').replace(/\.git$/, '');
      } else {
        repoName = 'Architecture Reference';
      }

      const session = await createSession(workspace, {
        snapshot_id: snapshot.snapshot_id,
        repo_url: isGolden ? 'https://github.com/mentorly/reference' : inputUrl,
        repo_name: repoName,
        title: `Exploring ${repoName}`,
      }, attempt.key);

      if (!current()) return;
      pending.current = null;
      if (ownsPending(attempt)) savePending(null);
      onSessionReady(session);
    } catch (err) {
      if (!current()) return;
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to start learning session.');
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <div className="codebase-onboarding">
      <div className="codebase-onboarding-card">
        {hasExistingSessions && onViewHistory && (
          <div className="onboarding-top-nav">
            <button type="button" className="ghost-button" onClick={onViewHistory}>
              ← All sessions
            </button>
          </div>
        )}
        <header className="onboarding-header">
          <div className="onboarding-badge">
            <Icon name="code" />
            <span>Voice-First Codebase Mentor</span>
          </div>
          <h1>Learn any GitHub repository with your AI mentor.</h1>
          <p className="onboarding-subtitle">
            Paste a repository URL. Your mentor will help you understand the architecture, code, and design decisions through conversation.
          </p>
        </header>

        {error && (
          <div className="codebase-alert error" role="alert">
            <Icon name="warning" />
            <span>{error}</span>
          </div>
        )}

        {status === 'idle' || status === 'error' ? (
          <form
            className="onboarding-form"
            onSubmit={(e) => {
              e.preventDefault();
              void handleStartLearning();
            }}
          >
            <div className="input-group">
              <label htmlFor="repo-url-input">GitHub Repository URL</label>
              <div className="input-wrapper">
                <input
                  id="repo-url-input"
                  type="text"
                  placeholder="https://github.com/owner/repository"
                  value={url}
                  onChange={(e) => {
                    const next = e.target.value;
                    const storedSource = pending.current ? JSON.parse(pending.current.identity)[2] : null;
                    if (storedSource && next.trim() && next.trim() !== storedSource) {
                      if (pending.current && ownsPending(pending.current)) savePending(null);
                      pending.current = null;
                    }
                    setUrl(next);
                  }}
                  spellCheck={false}
                />
                <button
                  type="submit"
                  className="primary start-button"
                  onClick={(e) => {
                    e.preventDefault();
                    void handleStartLearning();
                  }}
                >
                  Start learning <Icon name="arrow" />
                </button>
              </div>
            </div>

            <div className="samples-group">
              <span className="samples-label">Or explore a sample repository:</span>
              <div className="samples-pills">
                {SAMPLE_REPOS.map((sample) => (
                  <button
                    key={sample.label}
                    type="button"
                    className="sample-pill"
                    onClick={() => {
                      setUrl(sample.url);
                      void handleStartLearning(sample.url);
                    }}
                  >
                    {sample.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="permission-note">
              <div className="note-icon">🎙️</div>
              <div className="note-text">
                <strong>Hands-free voice experience</strong>
                <p>
                  Your browser will ask for microphone permission when you start. Your mentor speaks, listens, and explains naturally through conversation.
                </p>
              </div>
            </div>

            {hasExistingSessions && onViewHistory && (
              <div className="history-link-wrap">
                <button type="button" className="link-button" onClick={onViewHistory}>
                  View your previous learning sessions →
                </button>
              </div>
            )}
          </form>
        ) : (
          <div className="onboarding-progress" role="status">
            <div className="spinner-large" />
            <h3>Analyzing repository</h3>
            <p className="progress-status-text">{progressMsg}</p>
            <div className="progress-steps">
              <div className={`step-item ${status === 'validating' ? 'active' : 'done'}`}>
                1. Connecting
              </div>
              <div className={`step-item ${status === 'indexing' ? 'active' : status === 'preparing' ? 'done' : ''}`}>
                2. Ingesting & Indexing
              </div>
              <div className={`step-item ${status === 'preparing' ? 'active' : ''}`}>
                3. Grounding AI Mentor
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
