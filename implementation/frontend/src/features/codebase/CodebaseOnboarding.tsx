import { useState } from 'react';
import { Icon } from '../../components/HorizonVisuals';
import type { Workspace } from '../../studioApi';
import { ingestRepoUrl, ingestGoldenRepo, pollSnapshot, createSession, type CodebaseSession } from './codebaseApi';

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

export function CodebaseOnboarding({
  workspace,
  onSessionReady,
  onViewHistory,
  hasExistingSessions = false,
}: CodebaseOnboardingProps) {
  const [url, setUrl] = useState('');
  const [status, setStatus] = useState<'idle' | 'validating' | 'indexing' | 'preparing' | 'error'>('idle');
  const [progressMsg, setProgressMsg] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function handleStartLearning(targetUrl?: string) {
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

    setError(null);
    setStatus('validating');
    setProgressMsg('Validating repository and connecting to GitHub…');

    try {
      let snapshot;
      const isGolden = inputUrl === 'REPO-EXP-01' || inputUrl === 'REPO-EXP-02';

      if (isGolden) {
        setProgressMsg('Loading curated architectural snapshot…');
        snapshot = await ingestGoldenRepo(workspace, inputUrl);
      } else {
        setProgressMsg('Downloading repository snapshot and parsing files…');
        snapshot = await ingestRepoUrl(workspace, inputUrl);
      }

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
        snapshot = await pollSnapshot(workspace, snapshot.snapshot_id);
        if (snapshot.status === 'INDEXING') {
          const count = snapshot.files_indexed ?? 0;
          const total = snapshot.total_files ?? 0;
          setProgressMsg(`Analyzing code: indexed ${count} of ${total || 'all'} files…`);
        }
      }

      if (snapshot.status === 'FAILED') {
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
      });

      onSessionReady(session);
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to start learning session.');
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
                  onChange={(e) => setUrl(e.target.value)}
                  autoFocus
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
