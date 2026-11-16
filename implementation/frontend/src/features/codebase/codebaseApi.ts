import { studioRequest, type Workspace } from '../../studioApi';

export type CodebaseSnapshot = {
  snapshot_id: string;
  status: 'QUEUED' | 'INDEXING' | 'READY' | 'FAILED';
  total_files?: number;
  files_indexed?: number;
  coverage_ratio?: number;
  failure_code?: string;
  architecture?: {
    primary_language?: string;
    frameworks?: string[];
    entry_points?: string[];
    overview?: string;
    readme_excerpt?: string;
  };
};

export type Citation = {
  path: string;
  symbol: string;
  start_line: number;
  end_line: number;
  chunk_hash?: string;
  excerpt?: string;
  text?: string;
};

export type CodebaseMessage = {
  id: string;
  session_id?: string;
  sequence?: number;
  role: 'mentor' | 'learner';
  content: string;
  audio_url?: string | null;
  focus_topic?: string;
  focus_question?: string;
  citations: Citation[];
  metadata?: Record<string, unknown>;
  created_at: string;
};

export type CodebaseSession = {
  session_id: string;
  workspace_id: string;
  repo_id?: string;
  repo_snapshot_id?: string;
  snapshot_id?: string;
  repo_url: string;
  repo_name: string;
  branch?: string;
  commit_sha?: string | null;
  title: string;
  current_topic?: string;
  knowledge_level: string;
  message_count?: number;
  learning_progress?: Record<string, unknown>;
  pending_question?: string | null;
  status?: string;
  state?: string;
  created_at: string;
  updated_at: string;
  snapshot?: CodebaseSnapshot;
  messages?: CodebaseMessage[];
};

export type TurnResult = {
  session_id: string;
  learner_message: CodebaseMessage;
  mentor_message: CodebaseMessage;
  current_topic: string;
  knowledge_level: string;
};

export async function fetchSessions(workspace: Workspace, query?: string): Promise<CodebaseSession[]> {
  const url = `/codebase-learning/sessions${query ? `?q=${encodeURIComponent(query)}` : ''}`;
  const res = await studioRequest<{ sessions: CodebaseSession[] }>(url, {
    workspace,
  });
  return res.sessions ?? [];
}

export async function createSession(
  workspace: Workspace,
  params: {
    snapshot_id: string;
    repo_url: string;
    repo_name: string;
    branch?: string;
    commit_sha?: string | null;
    title?: string;
  },
  idempotencyKey?: string
): Promise<CodebaseSession> {
  return studioRequest<CodebaseSession>('/codebase-learning/sessions', {
    method: 'POST',
    workspace,
    idempotencyKey,
    body: params,
  });
}

export async function fetchSession(workspace: Workspace, sessionId: string): Promise<CodebaseSession> {
  return studioRequest<CodebaseSession>(`/codebase-learning/sessions/${encodeURIComponent(sessionId)}`, {
    workspace,
  });
}

export async function renameSession(workspace: Workspace, sessionId: string, title: string): Promise<CodebaseSession> {
  return studioRequest<CodebaseSession>(`/codebase-learning/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    workspace,
    body: { title },
  });
}

export async function deleteSession(workspace: Workspace, sessionId: string): Promise<void> {
  await studioRequest(`/codebase-learning/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    workspace,
  });
}

export async function submitTextTurn(
  workspace: Workspace,
  sessionId: string,
  text: string
): Promise<TurnResult> {
  return studioRequest<TurnResult>(`/codebase-learning/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: 'POST',
    workspace,
    body: { text },
  });
}

export async function submitVoiceTurn(
  workspace: Workspace,
  sessionId: string,
  wavBytes: Uint8Array,
  locale = 'en-IN'
): Promise<TurnResult> {
  const form = new FormData();
  const blob = new Blob([wavBytes.buffer as ArrayBuffer], { type: 'audio/wav' });
  form.append('file', blob, 'turn.wav');
  form.append('locale', locale);
  return studioRequest<TurnResult>(`/codebase-learning/sessions/${encodeURIComponent(sessionId)}/voice-turn`, {
    method: 'POST',
    workspace,
    body: form,
  });
}

export async function ingestRepoUrl(
  workspace: Workspace,
  repoUrl: string
): Promise<CodebaseSnapshot> {
  return studioRequest<CodebaseSnapshot>('/repos/ingest', {
    method: 'POST',
    workspace,
    body: {
      source_kind: 'public_git_url',
      source_locator: repoUrl.trim(),
    },
  });
}

export async function ingestGoldenRepo(
  workspace: Workspace,
  goldenId = 'REPO-EXP-01'
): Promise<CodebaseSnapshot> {
  return studioRequest<CodebaseSnapshot>('/repos/ingest', {
    method: 'POST',
    workspace,
    body: {
      source_kind: 'golden_curated',
      source_locator: goldenId,
    },
  });
}

export async function pollSnapshot(workspace: Workspace, snapshotId: string): Promise<CodebaseSnapshot> {
  return studioRequest<CodebaseSnapshot>(`/repos/${encodeURIComponent(snapshotId)}`, {
    workspace,
  });
}
