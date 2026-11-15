import { capability, readStudioTab, studioRequest, writeStudioTab, type Workspace } from '../studioApi';

let pendingWorkspace: Promise<Workspace> | null = null;
let workspaceGeneration = 0;

/** Reuse the studio's tab-scoped capability, never a second user identity. */
export function readWorkspaceSession(): Workspace | null {
  const workspace = readStudioTab().workspace;
  return workspace && typeof workspace.id === 'string' && !!workspace.id
    && typeof workspace.token === 'string' && !!workspace.token ? workspace : null;
}

export async function ensureWorkspaceSession(): Promise<Workspace> {
  const existing = readWorkspaceSession();
  if (existing) return existing;
  if (pendingWorkspace) return pendingWorkspace;
  pendingWorkspace = createWorkspace();
  try { return await pendingWorkspace; }
  finally { pendingWorkspace = null; }
}

async function createWorkspace(): Promise<Workspace> {
  const generation = workspaceGeneration;
  const workspace = { id: crypto.randomUUID(), token: capability() };
  await studioRequest('/studio/workspaces', {
    method: 'POST', body: { workspace_id: workspace.id, workspace_token: workspace.token },
  });
  if (generation !== workspaceGeneration) {
    const restored = readWorkspaceSession();
    if (restored) return restored;
    throw new Error('Workspace changed while creation was pending.');
  }
  // Read at publication time so concurrently remembered studio sessions survive.
  writeStudioTab({ ...readStudioTab(), workspace });
  return workspace;
}

/** Restore only with a server-validated recovery credential; keep bearers tab-scoped. */
export function replaceWorkspaceSession(workspace: Workspace): void {
  writeStudioTab({ workspace, sessions: [] });
  workspaceGeneration += 1;
  pendingWorkspace = null;
}

export async function linkDsaSessionToWorkspace(id: string, token: string): Promise<void> {
  const workspace = await ensureWorkspaceSession();
  await studioRequest(`/studio/workspaces/${encodeURIComponent(workspace.id)}/dsa-sessions/${encodeURIComponent(id)}/link`, {
    method: 'POST', token: workspace.token, body: { session_token: token },
  });
}
