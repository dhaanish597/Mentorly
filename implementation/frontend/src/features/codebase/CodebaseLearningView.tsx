import { useEffect, useRef, useState } from 'react';
import type { Workspace } from '../../studioApi';
import {
  fetchSessions,
  fetchSession,
  type CodebaseSession,
} from './codebaseApi';
import { CodebaseOnboarding } from './CodebaseOnboarding';
import { CodebaseSessionHistory } from './CodebaseSessionHistory';
import { CodebaseVoiceWorkspace } from './CodebaseVoiceWorkspace';
import './codebase-learning.css';

export type CodebaseLearningViewProps = {
  workspace?: Workspace;
  ensureWorkspace: () => Promise<Workspace>;
  active?: boolean;
};

export function CodebaseLearningView({
  workspace,
  ensureWorkspace,
  active = true,
}: CodebaseLearningViewProps) {
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(workspace || null);
  const [sessions, setSessions] = useState<CodebaseSession[]>([]);
  const [activeSession, setActiveSession] = useState<CodebaseSession | null>(null);
  const [view, setView] = useState<'loading' | 'onboarding' | 'history' | 'workspace'>('loading');
  const [error, setError] = useState<string | null>(null);

  const ensureWorkspaceRef = useRef(ensureWorkspace);
  ensureWorkspaceRef.current = ensureWorkspace;

  // Initialize workspace and sessions
  useEffect(() => {
    let alive = true;

    async function init() {
      try {
        const ws = workspace ?? (await ensureWorkspaceRef.current());
        if (!alive) return;
        setActiveWorkspace(ws);

        const list = await fetchSessions(ws);
        if (!alive) return;
        setSessions(list);

        // Only set view if currently loading; NEVER override user-initiated view switches!
        setView((prev) => {
          if (prev !== 'loading') return prev;
          return list.length > 0 ? 'history' : 'onboarding';
        });
      } catch (err) {
        if (alive) {
          setError(err instanceof Error ? err.message : 'Could not initialize workspace.');
          setView((prev) => (prev === 'loading' ? 'onboarding' : prev));
        }
      }
    }

    void init();
    return () => {
      alive = false;
    };
  }, [workspace]);

  async function handleRefreshSessions() {
    if (!activeWorkspace) return;
    try {
      const list = await fetchSessions(activeWorkspace);
      setSessions(list);
    } catch {
      // quiet refresh failure
    }
  }

  async function handleSelectSession(session: CodebaseSession) {
    if (!activeWorkspace) return;
    try {
      const fullSession = await fetchSession(activeWorkspace, session.session_id);
      setActiveSession(fullSession);
      sessionStorage.setItem('mentorly-active-codebase-session', fullSession.session_id);
      setView('workspace');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open session.');
    }
  }

  function handleSessionReady(newSession: CodebaseSession) {
    setActiveSession(newSession);
    sessionStorage.setItem('mentorly-active-codebase-session', newSession.session_id);
    setSessions((prev) => [newSession, ...prev]);
    setView('workspace');
  }

  function handleBackToHistory() {
    sessionStorage.removeItem('mentorly-active-codebase-session');
    void handleRefreshSessions();
    setView('history');
  }

  function handleNewSession() {
    setView('onboarding');
  }

  if (!active) return null;

  if (view === 'loading') {
    return (
      <div className="codebase-loading-state" role="status">
        <div className="spinner-large" />
        <p>Loading your codebase mentor…</p>
      </div>
    );
  }

  if (!activeWorkspace) {
    return (
      <div className="codebase-error-state" role="alert">
        <p>{error || 'Workspace could not be initialized. Please refresh.'}</p>
      </div>
    );
  }

  return (
    <div className="codebase-learning-container">
      {view === 'onboarding' && (
        <CodebaseOnboarding
          workspace={activeWorkspace}
          onSessionReady={handleSessionReady}
          onViewHistory={sessions.length > 0 ? () => setView('history') : undefined}
          hasExistingSessions={sessions.length > 0}
        />
      )}

      {view === 'history' && (
        <CodebaseSessionHistory
          workspace={activeWorkspace}
          sessions={sessions}
          onSelectSession={(s) => void handleSelectSession(s)}
          onNewSession={handleNewSession}
          onRefresh={() => void handleRefreshSessions()}
        />
      )}

      {view === 'workspace' && activeSession && (
        <CodebaseVoiceWorkspace
          workspace={activeWorkspace}
          session={activeSession}
          onSessionUpdated={setActiveSession}
          onBackToHistory={handleBackToHistory}
          onNewSession={handleNewSession}
        />
      )}
    </div>
  );
}
