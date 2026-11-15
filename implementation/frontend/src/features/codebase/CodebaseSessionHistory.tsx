import { useMemo, useState } from 'react';
import { Icon } from '../../components/HorizonVisuals';
import type { Workspace } from '../../studioApi';
import {
  deleteSession,
  renameSession,
  type CodebaseSession,
} from './codebaseApi';

export type CodebaseSessionHistoryProps = {
  workspace: Workspace;
  sessions: CodebaseSession[];
  onSelectSession: (session: CodebaseSession) => void;
  onNewSession: () => void;
  onRefresh: () => void;
};

type GroupedSessions = {
  today: CodebaseSession[];
  yesterday: CodebaseSession[];
  previous: CodebaseSession[];
};

function formatRelativeTime(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / (60 * 1000));
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    return `${diffDays}d ago`;
  } catch {
    return dateStr;
  }
}

export function CodebaseSessionHistory({
  workspace,
  sessions,
  onSelectSession,
  onNewSession,
  onRefresh,
}: CodebaseSessionHistoryProps) {
  const [search, setSearch] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const filteredSessions = useMemo(() => {
    if (!search.trim()) return sessions;
    const q = search.toLowerCase();
    return sessions.filter(
      (s) =>
        (s.title || '').toLowerCase().includes(q) ||
        (s.repo_name || '').toLowerCase().includes(q) ||
        (s.current_topic || '').toLowerCase().includes(q)
    );
  }, [sessions, search]);

  const grouped: GroupedSessions = useMemo(() => {
    const today: CodebaseSession[] = [];
    const yesterday: CodebaseSession[] = [];
    const previous: CodebaseSession[] = [];

    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const yesterdayStart = todayStart - 24 * 60 * 60 * 1000;

    for (const session of filteredSessions) {
      const time = new Date(session.updated_at || session.created_at).getTime();
      if (time >= todayStart) {
        today.push(session);
      } else if (time >= yesterdayStart) {
        yesterday.push(session);
      } else {
        previous.push(session);
      }
    }

    return { today, yesterday, previous };
  }, [filteredSessions]);

  async function handleRename(sessionId: string) {
    if (!editTitle.trim()) return;
    setIsBusy(true);
    setError(null);
    try {
      await renameSession(workspace, sessionId, editTitle.trim());
      setEditingId(null);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rename session.');
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDelete(sessionId: string) {
    setIsBusy(true);
    setError(null);
    try {
      await deleteSession(workspace, sessionId);
      setDeletingId(null);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete session.');
    } finally {
      setIsBusy(false);
    }
  }

  function renderGroup(title: string, groupSessions: CodebaseSession[]) {
    if (!groupSessions.length) return null;
    return (
      <div className="session-history-group" key={title}>
        <h3 className="group-title">{title}</h3>
        <ul className="session-list">
          {groupSessions.map((session) => (
            <li key={session.session_id} className="session-item">
              <div
                className="session-clickable"
                onClick={() => onSelectSession(session)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSelectSession(session);
                }}
              >
                <div className="session-item-header">
                  <span className="session-repo-pill">{session.repo_name}</span>
                  <span className="session-time">{formatRelativeTime(session.updated_at)}</span>
                </div>
                {editingId === session.session_id ? (
                  <form
                    className="rename-form"
                    onClick={(e) => e.stopPropagation()}
                    onSubmit={(e) => {
                      e.preventDefault();
                      void handleRename(session.session_id);
                    }}
                  >
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      autoFocus
                    />
                    <button type="submit" disabled={isBusy} className="rename-save">
                      Save
                    </button>
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => setEditingId(null)}
                      className="rename-cancel"
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <h4 className="session-title">{session.title}</h4>
                )}
                <div className="session-item-footer">
                  <span className="session-meta">
                    {session.message_count ?? 1} messages · {session.knowledge_level}
                  </span>
                </div>
              </div>

              <div className="session-item-actions">
                <button
                  type="button"
                  className="icon-action"
                  title="Rename session"
                  aria-label="Rename session"
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingId(session.session_id);
                    setEditTitle(session.title);
                  }}
                >
                  ✎
                </button>
                <button
                  type="button"
                  className="icon-action delete"
                  title="Delete session"
                  aria-label="Delete session"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeletingId(session.session_id);
                  }}
                >
                  🗑
                </button>
              </div>

              {deletingId === session.session_id && (
                <div className="delete-confirm-popover" onClick={(e) => e.stopPropagation()}>
                  <p>Delete this learning session?</p>
                  <div className="delete-confirm-buttons">
                    <button
                      type="button"
                      className="danger-btn"
                      disabled={isBusy}
                      onClick={() => void handleDelete(session.session_id)}
                    >
                      Confirm delete
                    </button>
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => setDeletingId(null)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="codebase-session-history">
      <header className="history-header">
        <div>
          <h2>Your learning sessions</h2>
          <p>Resume previous conversations or start exploring a new codebase.</p>
        </div>
        <button type="button" className="primary new-session-btn" onClick={onNewSession}>
          + New session
        </button>
      </header>

      {error && (
        <div className="codebase-alert error" role="alert">
          <Icon name="warning" />
          <span>{error}</span>
        </div>
      )}

      <div className="history-search-bar">
        <input
          type="search"
          placeholder="Search learning sessions or repositories…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="history-content">
        {!sessions.length ? (
          <div className="history-empty">
            <p>No learning sessions saved yet.</p>
            <button type="button" className="primary" onClick={onNewSession}>
              Start learning a repository
            </button>
          </div>
        ) : !filteredSessions.length ? (
          <div className="history-empty">
            <p>No sessions match "{search}".</p>
          </div>
        ) : (
          <div className="history-groups">
            {renderGroup('Today', grouped.today)}
            {renderGroup('Yesterday', grouped.yesterday)}
            {renderGroup('Previous', grouped.previous)}
          </div>
        )}
      </div>
    </div>
  );
}
