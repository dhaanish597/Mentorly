import { capability, readStudioTab, studioRequest, writeStudioTab, type Workspace } from '../studioApi';

let pendingWorkspace: Promise<Workspace> | null = null;

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
  const workspace = { id: crypto.randomUUID(), token: capability() };
  await studioRequest('/studio/workspaces', {
    method: 'POST', body: { workspace_id: workspace.id, workspace_token: workspace.token },
  });
  // Read at publication time so concurrently remembered studio sessions survive.
  writeStudioTab({ ...readStudioTab(), workspace });
  return workspace;
}
