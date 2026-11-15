import { useState } from 'react';
import type { components } from '../../types/openapi';
import { capability, readStudioTab, studioRequest, writeStudioTab } from '../../studioApi';
import { ensureWorkspaceSession, readWorkspaceSession, replaceWorkspaceSession } from '../../state/workspaceSession';
import { readTabSessions, rememberTabSession, problemUrl } from '../../state/productState';
import { registerSessionToken } from '../../services/apiClient';
import { exportDraftBackup, importDraftBackup } from '../../state/draftBackup';
import { navigate } from '../../components/ProductShell';

type Archive = components['schemas']['WorkspaceArchive'];

function randomCredential(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}

export function WorkspaceRecovery() {
  const [kit, setKit] = useState<{ id: string; credential: string } | null>(null);
  const [workspaceId, setWorkspaceId] = useState('');
  const [credential, setCredential] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restorable, setRestorable] = useState<Archive['data'] | null>(null);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(null); setNotice(null);
    try { await action(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Workspace action failed. Please retry.'); }
    finally { setBusy(false); }
  }
  async function create() {
    const workspace = await ensureWorkspaceSession();
    let unlinked = 0;
    for (const session of Object.values(readTabSessions())) {
      try {
        await studioRequest(`/studio/workspaces/${workspace.id}/dsa-sessions/${encodeURIComponent(session.id)}/link`, { method: 'POST', token: workspace.token, body: { session_token: session.token } });
      } catch { unlinked += 1; }
    }
    const secret = randomCredential();
    const info = await studioRequest<components['schemas']['RecoveryInfo']>(`/studio/workspaces/${workspace.id}/recovery`, {
      method: 'PUT', token: workspace.token, body: { recovery_token: secret },
    });
    setKit({ id: workspace.id, credential: secret });
    setNotice(`Recovery enabled until ${info.expires_at ? new Date(info.expires_at).toLocaleDateString() : 'workspace expiry'}. Previous recovery credentials were revoked.${unlinked ? ` ${unlinked} prior DSA sessions could not be linked; expired or other-workspace sessions cannot be recovered here.` : ''}`);
  }
  async function restore() {
    const token = randomCredential();
    const result = await studioRequest<components['schemas']['RestoredWorkspace']>(`/studio/workspaces/${encodeURIComponent(workspaceId.trim())}/recover`, {
      method: 'POST', body: { recovery_token: credential.trim(), workspace_token: token },
    });
    const workspace = { id: result.workspace_id, token };
    replaceWorkspaceSession(workspace);
    setCredential(''); setKit(null);
    setNotice('Workspace access restored. Loading owned session references.');
    const archive = await studioRequest<Archive>(`/studio/workspaces/${workspace.id}/archive`, { token });
    // Reissue only the selected session. Bulk rotation would exhaust normal quotas.
    setRestorable(archive.data);
    setNotice('Workspace access restored. Open Progress, Curriculum, or Design studio to resume server records. Unsaved drafts remain on their original device.');
  }
  async function resume(id: string, kind: 'studio' | 'dsa') {
    const workspace = readWorkspaceSession();
    if (!workspace || !restorable) throw new Error('Restore workspace access first.');
    const fresh = capability();
    await studioRequest(`/studio/workspaces/${workspace.id}/sessions/${id}/capability`, { method: 'POST', token: workspace.token, body: { session_token: fresh } });
    if (kind === 'studio') {
      const current = readStudioTab();
      writeStudioTab({ workspace, sessions: [{ id, token: fresh, workspace }, ...current.sessions.filter(session => session.id !== id)] });
      navigate('/studio');
    } else {
      const session = restorable.dsa_sessions.find(item => item.id === id);
      if (!session) throw new Error('Owned session reference is unavailable.');
      registerSessionToken(id, fresh);
      rememberTabSession(session.exercise_id, session.spec_version, { id, token: fresh });
      navigate(problemUrl(session.exercise_id, session.spec_version));
    }
  }
  async function revoke() {
    const workspace = readWorkspaceSession();
    if (!workspace) throw new Error('No workspace is active in this tab.');
    await studioRequest(`/studio/workspaces/${workspace.id}/recovery`, { method: 'DELETE', token: workspace.token });
    setKit(null); setNotice('Recovery revoked. This tab still has access to its workspace.');
  }
  async function backup() {
    const workspace = readWorkspaceSession();
    if (!workspace) throw new Error('No workspace is active in this tab.');
    const archive = await studioRequest<Archive>(`/studio/workspaces/${workspace.id}/archive`, { token: workspace.token });
    const url = URL.createObjectURL(new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'workspace-records.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice('Record archive downloaded without credentials. It contains server learning answers and reports; it is not a recovery credential or an unsaved-draft backup.');
  }
  async function backupDrafts() {
    const json = await exportDraftBackup();
    const url = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'device-drafts.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice('Draft backup downloaded. It contains source code and explanation drafts. Keep it private; workspace credentials are excluded.');
  }
  return <section className="settings-recovery" aria-labelledby="workspace-recovery-title">
    <h3 id="workspace-recovery-title">Recover your workspace</h3>
    <p>Choose recovery before closing this tab. Save the workspace ID and secret privately; they grant access to your records until workspace expiry (up to 30 days). The secret stays visible here until you dismiss it or leave this page.</p>
    <p>Restoring rotates the workspace capability. Other tabs must restore again. Server records remain unchanged; unsaved drafts and device preferences stay on their original device.</p>
    <button type="button" disabled={busy} onClick={() => void run(create)}>Create or rotate recovery credential</button>
    <button type="button" disabled={busy} onClick={() => void run(revoke)}>Revoke recovery</button>
    <button type="button" disabled={busy} onClick={() => void run(backup)}>Export workspace records</button>
    <button type="button" disabled={busy} onClick={() => void run(backupDrafts)}>Export local drafts</button>
    <label>Import local draft backup<input type="file" accept="application/json,.json" disabled={busy} onChange={event => {
      const file = event.target.files?.[0]; event.target.value = '';
      if (file) void run(async () => {
        if (file.size > 10_000_000) throw new Error('Draft backup exceeds 10 MB.');
        const result = await importDraftBackup(await file.text());
        setNotice(`${result.restored} drafts restored; ${result.skipped} existing equal or newer drafts kept. Server revisions remain unchanged.`);
      });
    }} /></label>
    {kit && <div role="group" aria-label="Save recovery credential"><label>Workspace ID<input readOnly value={kit.id} /></label><label>Recovery secret<input readOnly value={kit.credential} autoComplete="off" /></label><button type="button" onClick={() => setKit(null)}>I saved it privately</button></div>}
    <form onSubmit={event => { event.preventDefault(); void run(restore); }}>
      <label>Workspace ID to recover<input value={workspaceId} onChange={event => setWorkspaceId(event.target.value)} required maxLength={64} autoComplete="off" /></label>
      <label>Recovery secret<input type="password" value={credential} onChange={event => setCredential(event.target.value)} required minLength={43} maxLength={128} autoComplete="off" /></label>
      <button type="submit" disabled={busy}>Restore workspace access</button>
    </form>
    {restorable && <div aria-label="Recovered practice sessions"><h4>Resume a practice session</h4>
      <p>Capabilities are restored only when you choose a session. Its original expiry still applies.</p>
      {restorable.studio_sessions.map(session => <button type="button" key={session.id} disabled={busy} onClick={() => void run(() => resume(session.id, 'studio'))}>Resume {session.scenario_id} · {session.id.slice(0, 8)}</button>)}
      {restorable.dsa_sessions.map(session => <button type="button" key={session.id} disabled={busy} onClick={() => void run(() => resume(session.id, 'dsa'))}>Resume {session.exercise_id} · {session.id.slice(0, 8)}</button>)}
    </div>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
