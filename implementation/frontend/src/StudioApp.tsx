import { FALLBACK_BRANDING } from './config/branding';
import { useEffect, useRef, useState } from 'react';
import { capability, readStudioTab, studioRequest, writeStudioTab, StudioError, type Graph, type Scenario, type StudioEdge, type StudioNode, type StudioSession, type Workspace } from './studioApi';
import { RepositoryPanel } from './StudioRepository';
import { StudioGraph } from './StudioGraph';
import { StudioMentor } from './StudioMentor';
import { StudioSetup } from './StudioSetup';
import { StudioSessionTools } from './StudioSessionTools';
import { StudioTabs } from './StudioTabs';
import { parseObject, readable, type ScenarioView, type Snapshot } from './StudioViews';
import './studio.css';

const emptyGraph = (): Graph => ({ nodes: [], edges: [], assumptions: {} });
const areaTabs = [{ id: 'design', label: 'System design' }, { id: 'repository', label: 'Codebase learning' }] as const;
function StudioNav() { return <header className="studio-header"><a href="/dashboard" className="studio-brand">{FALLBACK_BRANDING.productName}</a><nav aria-label="Main navigation"><a href="/dashboard">Home</a><a href="/library">Practice</a><a href="/paths">Learning paths</a><a href="/studio" aria-current="page">Design studio</a><a href="/progress">Progress</a></nav></header>; }
export function StudioApp() {
  const [tab, setTab] = useState(readStudioTab);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState('');
  const [mock, setMock] = useState(false);
  const [duration, setDuration] = useState(2700);
  const [clock, setClock] = useState(Date.now());
  const [posture, setPosture] = useState('teaching');
  const [selected, setSelected] = useState<StudioSession | null>(null);
  const [scenarioView, setScenarioView] = useState<ScenarioView | null>(null);
  const [coachReply, setCoachReply] = useState('');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [graph, setGraph] = useState<Graph>(emptyGraph);
  const [history, setHistory] = useState<Graph[]>([]);
  const [future, setFuture] = useState<Graph[]>([]);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [turnInFlight, setTurnInFlight] = useState(false);
  const [evaluation, setEvaluation] = useState<unknown>(null);
  const [validation, setValidation] = useState<unknown>(null);
  const [repoSnapshot, setRepoSnapshot] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<{revision:number; parent_revision:number | null; created_at:string}[]>([]);
  const [proposalText, setProposalText] = useState('');
  const [proposal, setProposal] = useState<{proposal_id:string;graph:Graph;validation:unknown} | null>(null);
  const [summary, setSummary] = useState<unknown>(null);
  const [panel, setPanel] = useState<'design' | 'repository'>(() => new URLSearchParams(window.location.search).get('area') === 'repository' ? 'repository' : 'design');
  const [repositoryVisited, setRepositoryVisited] = useState(() => panel === 'repository');
  function changeArea(value: 'design' | 'repository') { if (value === 'repository') setRepositoryVisited(true); setPanel(value); }
  const [turn, setTurn] = useState('');
  const [editingTurn, setEditingTurn] = useState<{ id: string; revision: number } | null>(null);
  const [lastTurnId, setLastTurnId] = useState('');
  const [externalFeedback, setExternalFeedback] = useState(false);
  const [feedback, setFeedback] = useState<unknown>(null);
  const [reviewPrompt, setReviewPrompt] = useState('');
  const [reviews, setReviews] = useState<{card_id:string;prompt:string;due_at:string}[]>([]);
  const [turnKind, setTurnKind] = useState('explain');
  const [assumptionsText, setAssumptionsText] = useState('{}');
  const generation = useRef(0);
  const turnAbort = useRef<AbortController | null>(null);
  const activeActions = useRef(0);
  const graphLocked = busy || snapshot?.state === 'completed';
  const assumptionsPending = assumptionsText !== JSON.stringify(graph.assumptions, null, 2);
  useEffect(() => () => { generation.current++; turnAbort.current?.abort(); }, []);
  const savedTab = (next: typeof tab) => { writeStudioTab(next); setTab(next); };
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty || assumptionsPending) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [dirty, assumptionsPending]);
  useEffect(() => { const id = window.setInterval(() => setClock(Date.now()), 1000); return () => window.clearInterval(id); }, []);
  useEffect(() => {
    let alive = true;
    studioRequest<{ scenarios: Scenario[] }>('/studio/scenarios').then(r => {
      if (alive) {
        const sorted = [...r.scenarios].sort((a, b) => {
          const aIsSD = a.mode === 'dsa_to_system_bridge' || a.mode === 'guided_system_design';
          const bIsSD = b.mode === 'dsa_to_system_bridge' || b.mode === 'guided_system_design';
          if (aIsSD && !bIsSD) return -1;
          if (!aIsSD && bIsSD) return 1;
          return 0;
        });
        setScenarios(sorted);
        setScenario(current => current || sorted.find(s => s.mode === 'dsa_to_system_bridge' || s.mode === 'guided_system_design')?.id || sorted[0]?.id || '');
      }
    }).catch(e => {
      if (alive) setError(`Scenario catalog unavailable: ${String(e.message ?? e)}`);
    });
    return () => { alive = false; };
  }, []);
  async function action(fn: () => Promise<void>) {
    setError(null); activeActions.current++; setBusy(true);
    try { await fn(); }
    catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(e instanceof StudioError && e.status === 409 && /revision|epoch/i.test(e.message)
        ? 'This session changed elsewhere. Reload the saved version before saving again.'
        : e instanceof Error ? e.message : String(e));
    } finally { activeActions.current--; setBusy(activeActions.current > 0); }
  }
  async function ensureWorkspace(): Promise<Workspace> { if (tab.workspace) return tab.workspace; const workspace = { id: crypto.randomUUID(), token: capability() }; await studioRequest('/studio/workspaces', { method: 'POST', body: { workspace_id: workspace.id, workspace_token: workspace.token } }); savedTab({ ...tab, workspace }); return workspace; }
  async function openSession(session: StudioSession) {
    const load = ++generation.current;
    const path = `/studio/sessions/${encodeURIComponent(session.id)}`;
    const data = await studioRequest<Snapshot>(path, { token: session.token });
    const detail = await studioRequest<ScenarioView>(`${path}/scenario`, { token: session.token });
    if (load !== generation.current) return;
    const initial = data.graph ?? data.diagram ?? emptyGraph();
    const lastCoach = [...(data.events ?? [])].reverse().find(event => event.type === 'coach.action' && event.payload?.epoch === data.epoch);
    const latestTurn = [...(data.turns ?? [])].reverse().find(item => !item.superseded_by);
    setScenarioView(detail); setCoachReply(lastCoach?.payload?.text ?? '');
    setFeedback(null); setProposal(null); setRevisions([]); setSummary(null);
    setSelected(session); setSnapshot(data); setGraph(initial);
    setAssumptionsText(JSON.stringify(initial.assumptions ?? {}, null, 2));
    setHistory([]); setFuture([]); setDirty(false); setValidation(null); setEvaluation(null);
    setLastTurnId(latestTurn?.id ?? '');
    if (selected?.id !== session.id) { setEditingTurn(null); setTurn(''); }
  }
  async function startSession() {
    const item = scenarios.find(s => s.id === scenario);
    if (!item) throw new Error('Choose an available scenario.');
    const repositoryCase = ['repo_exploration', 'project_defense'].includes(item.mode);
    if (repositoryCase && !repoSnapshot) {
      throw new Error('This challenge needs a repository snapshot. Switch to the Codebase learning tab above to import one first.');
    }
    const timed = mock && item.mode === 'guided_system_design';
    const workspace = await ensureWorkspace();
    const session: StudioSession = { id: crypto.randomUUID(), token: capability(), workspace };
    await studioRequest('/studio/sessions', {
      method: 'POST', token: workspace.token,
      body: {
        workspace_id: workspace.id, session_id: session.id, session_token: session.token,
        mode: timed ? 'architecture_mock_interview' : item.mode, posture,
        ...(timed ? { duration_seconds: duration } : {}), scenario_id: item.id, scenario_version: item.version,
        ...(repositoryCase && repoSnapshot ? { repo_snapshot_id: repoSnapshot } : {}),
      },
    });
    savedTab({ workspace, sessions: [...tab.sessions, session] });
    await openSession(session);
  }
  function edit(next: Graph) { setHistory(h => [...h.slice(-49), graph]); setFuture([]); setGraph(next); setDirty(true); }
  function undo() { const prev = history[history.length - 1]; if (!prev) return; setHistory(h => h.slice(0, -1)); setFuture(f => [graph, ...f]); setGraph(prev); setAssumptionsText(JSON.stringify(prev.assumptions, null, 2)); setDirty(true); }
  function redo() { const next = future[0]; if (!next) return; setFuture(f => f.slice(1)); setHistory(h => [...h, graph]); setGraph(next); setAssumptionsText(JSON.stringify(next.assumptions, null, 2)); setDirty(true); }
  async function save() {
    if (!selected || !snapshot) return;
    const assumptions = parseObject(assumptionsText);
    const result = await studioRequest<{ revision: number; epoch: number; validation: unknown }>(`/studio/sessions/${encodeURIComponent(selected.id)}/diagram`, {
      method: 'PUT', token: selected.token,
      body: { base_revision: snapshot.diagram_revision, nodes: graph.nodes, edges: graph.edges, assumptions },
    });
    setGraph({ ...graph, assumptions });
    setSnapshot({ ...snapshot, diagram_revision: result.revision, epoch: result.epoch });
    setValidation(result.validation); setDirty(false);
  }
  async function submitTurn() {
    if (!selected || !snapshot || !turn.trim()) return;
    const current = ++generation.current;
    const controller = new AbortController();
    turnAbort.current = controller;
    setTurnInFlight(true);
    const path = `/studio/sessions/${encodeURIComponent(selected.id)}/turns${editingTurn ? `/${encodeURIComponent(editingTurn.id)}/correction` : ''}`;
    try {
      const recorded = await studioRequest<{ turn_id: string; epoch?: number }>(path, {
        method: 'POST', token: selected.token,
        body: { epoch: snapshot.epoch, ...(editingTurn ? { base_revision: editingTurn.revision } : {}), text: turn.trim(), kind: turnKind },
        signal: controller.signal,
      });
      if (generation.current !== current) return;
      setLastTurnId(recorded.turn_id);
      const epoch = recorded.epoch;
      if (epoch !== undefined) setSnapshot(previous => previous ? { ...previous, epoch } : previous);
      setTurn(''); setEditingTurn(null);
      await openSession(selected);
    } finally { setTurnInFlight(false); }
  }
  function editLatestTurn(item: NonNullable<Snapshot['turns']>[number]) {
    if (graphLocked || item.superseded_by) return;
    if (turn.trim() && !window.confirm('Replace your current explanation draft with this saved explanation?')) return;
    setEditingTurn({ id: item.id, revision: item.transcript_revision ?? 1 });
    setTurn(item.content); setTurnKind(item.kind);
    document.getElementById('studio-explanation')?.focus();
  }
  async function interrupt() { if (!selected || !snapshot) return; const current = ++generation.current; turnAbort.current?.abort(); const result = await studioRequest<{ epoch: number }>(`/studio/sessions/${encodeURIComponent(selected.id)}/interrupt`, { method: 'POST', token: selected.token, body: { expected_epoch: snapshot.epoch } }); if (current === generation.current) setSnapshot(prev => prev?.session_id === selected.id ? { ...prev, epoch: result.epoch } : prev); }
  async function previewProposal() { if (!selected || !snapshot) return; const candidate = parseObject(proposalText); const r = await studioRequest<{proposal_id:string;graph:Graph;validation:unknown}>(`/studio/sessions/${selected.id}/proposals`, {method:'POST',token:selected.token,body:{base_revision:snapshot.diagram_revision,graph:candidate}}); setProposal(r); }
  async function decideProposal(decision:'accept'|'discard') { if (!selected || !proposal || dirty || assumptionsPending) return; await studioRequest(`/studio/sessions/${selected.id}/proposals/${proposal.proposal_id}/${decision}`, {method:'POST',token:selected.token}); setProposal(null); await openSession(selected); }
  async function loadRevisions() { if (!selected) return; const r = await studioRequest<{revisions: typeof revisions}>(`/studio/sessions/${selected.id}/diagrams`, { token: selected.token }); setRevisions(r.revisions); }
  async function restoreRevision(target_revision: number) {
    if (!selected || !snapshot) return;
    const r = await studioRequest<{ revision: number; epoch: number; graph: Graph }>(`/studio/sessions/${selected.id}/diagrams/restore`, {
      method: 'POST', token: selected.token, body: { base_revision: snapshot.diagram_revision, target_revision },
    });
    setGraph(r.graph); setAssumptionsText(JSON.stringify(r.graph.assumptions, null, 2));
    setSnapshot({ ...snapshot, diagram_revision: r.revision, epoch: r.epoch });
    setHistory([]); setFuture([]); setDirty(false);
    await loadRevisions();
  }
  async function getSummary() { if (!selected) return; setSummary(await studioRequest(`/studio/sessions/${selected.id}/summary`, {token:selected.token})); }
  async function exportSession() { if (!selected) return; const data = await studioRequest(`/studio/sessions/${selected.id}/export`, {token:selected.token}); const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})); const link=document.createElement('a'); link.href=url; link.download='viva-studio-session.json'; link.click(); URL.revokeObjectURL(url); }
  async function evaluateDiagram() { if (!selected) return; setEvaluation(await studioRequest(`/studio/sessions/${selected.id}/evaluation`, {token:selected.token})); }
  async function refreshSession(expectedEpoch?: number, requestGeneration = ++generation.current) {
    if (!selected) return;
    const data = await studioRequest<Snapshot>(`/studio/sessions/${selected.id}`, { token: selected.token });
    if (generation.current !== requestGeneration || (expectedEpoch !== undefined && data.epoch !== expectedEpoch)) return;
    if (snapshot && data.diagram_revision !== snapshot.diagram_revision) throw new StudioError(409, 'Diagram revision changed; reload the saved version.');
    setSnapshot(data);
    setLastTurnId([...(data.turns ?? [])].reverse().find(turn => !turn.superseded_by)?.id ?? '');
  }
  async function requestFeedback() {
    if (!selected || !snapshot || !lastTurnId) return;
    const local = ++generation.current;
    const r = await studioRequest<{ epoch: number }>(`/studio/sessions/${selected.id}/feedback`, {
      method: 'POST', token: selected.token,
      body: { epoch: snapshot.epoch, turn_id: lastTurnId, allow_external: externalFeedback },
    });
    if (generation.current !== local || r.epoch !== snapshot.epoch) return;
    setFeedback(r);
    await refreshSession(r.epoch, local);
  }
  async function createReview() { if (!selected || !lastTurnId || !reviewPrompt.trim()) return; await studioRequest(`/studio/sessions/${selected.id}/review-cards`, {method:'POST',token:selected.token,body:{turn_id:lastTurnId,prompt:reviewPrompt.trim()}}); setReviewPrompt(''); await loadReviews(); }
  async function loadReviews() { if (!selected) return; const r=await studioRequest<{cards:typeof reviews}>(`/studio/workspaces/${selected.workspace.id}/reviews`, {token:selected.workspace.token}); setReviews(r.cards); }
  async function rateReview(id:string,rating:number) { if (!selected) return; await studioRequest(`/studio/workspaces/${selected.workspace.id}/reviews/${id}/rating`, {method:'POST',token:selected.workspace.token,body:{rating}}); await loadReviews(); }
  async function timer(actionName:'pause'|'resume') { if (!selected) return; await studioRequest(`/studio/sessions/${selected.id}/timer/${actionName}`, {method:'POST',token:selected.token}); await openSession(selected); }
  async function removeWorkspace() { if (!tab.workspace) return; generation.current++; turnAbort.current?.abort(); await studioRequest(`/studio/workspaces/${tab.workspace.id}`, {method:'DELETE',token:tab.workspace.token}); sessionStorage.removeItem('viva-repo-tab-v1'); savedTab({sessions:[]}); setRepoSnapshot(null); setSelected(null); setSnapshot(null); }
  async function switchToTeaching() { if (!selected) return; await studioRequest(`/studio/sessions/${selected.id}/posture`,{method:'POST',token:selected.token,body:{posture:'teaching'}}); await openSession(selected); }
  async function coach(actionName:string) { if (!selected) return; const r=await studioRequest<{text:string;epoch:number}>(`/studio/sessions/${selected.id}/coach`, {method:'POST',token:selected.token,body:{action:actionName}}); setCoachReply(r.text); await openSession(selected); }
  async function removeSession() { if (!selected) return; generation.current++; turnAbort.current?.abort(); await studioRequest(`/studio/sessions/${encodeURIComponent(selected.id)}`, { method: 'DELETE', token: selected.token }); savedTab({ ...tab, sessions: tab.sessions.filter(s => s.id !== selected.id) }); setSelected(null); setSnapshot(null); setGraph(emptyGraph()); }
  function addNode(): string {
    const id = crypto.randomUUID();
    edit({ ...graph, nodes: [...graph.nodes, { node_id: id, kind: 'service', label: 'New component', replica_count: 1, statefulness: 'unknown', partition_key: '', consistency_mode: 'unknown', notes: '', properties: { position: { x: 60, y: 60 } } }] });
    return id;
  }
  function updateNode(i: number, patch: Partial<StudioNode>) { edit({ ...graph, nodes: graph.nodes.map((n, j) => i === j ? { ...n, ...patch } : n) }); }
  function removeNode(i: number) { const id = graph.nodes[i].node_id; edit({ ...graph, nodes: graph.nodes.filter((_, j) => i !== j), edges: graph.edges.filter(e => e.source_node_id !== id && e.target_node_id !== id) }); }
  function addEdge(source = graph.nodes[0]?.node_id, target = graph.nodes[1]?.node_id): string | undefined {
    if (!source || !target || source === target || !graph.nodes.some(n => n.node_id === source) || !graph.nodes.some(n => n.node_id === target)) return;
    const id = crypto.randomUUID();
    edit({ ...graph, edges: [...graph.edges, { edge_id: id, source_node_id: source, target_node_id: target, protocol: '', directionality: 'directed', rate_estimate_rps: null, failure_behavior: '' }] });
    return id;
  }
  function updateEdge(i: number, patch: Partial<StudioEdge>) { edit({ ...graph, edges: graph.edges.map((e, j) => i === j ? { ...e, ...patch } : e) }); }
  const mutationDisabled = busy || dirty || assumptionsPending;
  function confirmDiscard(): boolean { return !(dirty || assumptionsPending) || window.confirm('Discard unsaved diagram changes?'); }
  function leaveSession() {
    if (!confirmDiscard()) return;
    generation.current++; turnAbort.current?.abort(); setSelected(null); setSnapshot(null); setDirty(false);
    setGraph(emptyGraph()); setAssumptionsText('{}'); setTurn(''); setEditingTurn(null);
  }
  const timerText = snapshot?.state === 'paused' ? `Paused: ${snapshot.remaining_seconds ?? 0} seconds remaining`
    : snapshot?.deadline_at ? `Time remaining: ${Math.max(0, Math.ceil((Date.parse(snapshot.deadline_at) - clock) / 1000))} seconds` : 'Timer unavailable';
  return <div className="studio-shell horizon">
    <a className="skip-link" href="#studio-main">Skip to main content</a><StudioNav />
    <main className={`studio-main ${selected ? 'studio-active' : ''}`} id="studio-main">
      <header className="studio-title">
        <div><p className="studio-eyebrow">Learn by designing and defending</p><h1>{selected ? scenarioView?.title ?? 'Design studio' : 'Design studio'}</h1></div>
        {selected && <span className="studio-stage">{readable(snapshot?.phase ?? 'clarify')}{scenarioView ? ` · Constraint ${scenarioView.constraint_index + 1}` : ''}</span>}
        <a href="/library">← Coding practice</a>
      </header>
      {error && <p className="studio-error" role="alert">{error}</p>}
      <StudioTabs label="Studio area" tabs={areaTabs} value={panel} onChange={changeArea}>
        {repositoryVisited && <div hidden={panel !== 'repository'}><RepositoryPanel workspace={tab.workspace} ensureWorkspace={ensureWorkspace} onSnapshot={setRepoSnapshot}
          session={selected} speechEpoch={snapshot?.epoch ?? 1} speechEvents={snapshot?.events ?? []} active={panel === 'repository'}
          boundSnapshotId={snapshot?.repo_snapshot_id} onSessionChange={() => action(() => refreshSession())} /></div>}
        <div hidden={panel !== 'design'}>{!selected ?
          <StudioSetup scenarios={scenarios} scenario={scenario} onScenario={setScenario} mock={mock} onMock={setMock}
            duration={duration} onDuration={setDuration} posture={posture} onPosture={setPosture} busy={busy}
            sessions={tab.sessions} workspace={tab.workspace} onStart={() => void action(startSession)}
            onResume={session => void action(() => openSession(session))} onDeleteWorkspace={() => { if (window.confirm('Permanently delete this workspace and all associated data?')) void action(removeWorkspace); }} /> : <>
          <div className="studio-session-bar">
            <div><span className="studio-revision" role="status">Revision {snapshot?.diagram_revision ?? 0}{dirty || assumptionsPending ? ' · Unsaved changes' : ' · Saved'}</span>
              {snapshot?.mode === 'architecture_mock_interview' && <div className="studio-timer"><span role="status">{timerText}</span><button disabled={mutationDisabled} onClick={() => void action(() => timer(snapshot.state === 'paused' ? 'resume' : 'pause'))}>{snapshot.state === 'paused' ? 'Resume timer' : 'Pause timer'}</button></div>}
            </div>
            <div className="studio-actions"><button disabled={!history.length || graphLocked || assumptionsPending} onClick={undo}>Undo</button><button disabled={!future.length || graphLocked || assumptionsPending} onClick={redo}>Redo</button><button disabled={!dirty || graphLocked || assumptionsPending} onClick={() => void action(save)}>Save diagram</button></div>
          </div>
          <div className="studio-workspace">
            <StudioMentor key={selected.id} session={selected} snapshot={snapshot} scenario={scenarioView} reply={coachReply}
              draft={turn} onDraft={setTurn} kind={turnKind} onKind={setTurnKind} locked={graphLocked || panel !== 'design'} actionDisabled={mutationDisabled}
              correcting={editingTurn !== null} onCancelCorrection={() => { setEditingTurn(null); setTurn(''); }}
              dirty={dirty} assumptionsPending={assumptionsPending} busy={busy} turnInFlight={turnInFlight}
              onSend={() => void action(submitTurn)} onCoach={name => void action(() => coach(name))}
              onInterrupt={() => void action(interrupt)} onTeaching={() => { if (window.confirm('Switch to teaching and interrupt this assessment?')) void action(switchToTeaching); }} />
            <div className="studio-workspace-content">
              {scenarioView && <section className="studio-constraint-strip" aria-label="Current constraint"><span className="studio-eyebrow">Current constraint</span><h2>{scenarioView.constraint.title}</h2><p>{scenarioView.constraint.description}</p>{scenarioView.transfer_active && <p role="status">Fresh transfer is active. Work on the new case and explain your reasoning.</p>}</section>}
              {snapshot?.state === 'completed' && <p className="studio-completed" role="status">Practice is complete. Reopen in teaching mode to edit the diagram or add turns.</p>}
              <StudioGraph key={selected.id} graph={graph} locked={graphLocked} assumptionsText={assumptionsText} assumptionsPending={assumptionsPending}
                requiredFields={scenarioView?.required_fields ?? []} onAssumptionsText={setAssumptionsText} onError={setError}
                onEdit={edit} onPosition={next => { setGraph(next); setDirty(true); }} onDragCommit={initial => { setHistory(h => [...h.slice(-49), initial]); setFuture([]); }}
                onAddNode={addNode} onAddEdge={addEdge} onUpdateNode={updateNode} onRemoveNode={removeNode} onUpdateEdge={updateEdge}
                checkDisabled={mutationDisabled} onCheck={() => void action(evaluateDiagram)} evaluation={evaluation} validation={validation} />
              <StudioSessionTools graph={graph} snapshot={snapshot} scenario={scenarioView} busy={busy} mutationDisabled={mutationDisabled}
                onEditTurn={editLatestTurn} editDisabled={graphLocked || assumptionsPending}
                proposalText={proposalText} onProposalText={setProposalText} proposal={proposal} onPreview={() => void action(previewProposal)} onDecide={decision => void action(() => decideProposal(decision))}
                revisions={revisions} onRevisions={() => void action(loadRevisions)} onRestore={revision => void action(() => restoreRevision(revision))}
                summary={summary} onSummary={() => void action(getSummary)} onExport={() => void action(exportSession)} lastTurnId={lastTurnId}
                externalFeedback={externalFeedback} onExternalFeedback={setExternalFeedback} feedback={feedback} onFeedback={() => void action(requestFeedback)}
                reviewPrompt={reviewPrompt} onReviewPrompt={setReviewPrompt} reviews={reviews} onCreateReview={() => void action(createReview)} onLoadReviews={() => void action(loadReviews)} onRateReview={(id, rating) => void action(() => rateReview(id, rating))}
                onReload={() => { if (confirmDiscard()) void action(() => openSession(selected)); }} onLeave={leaveSession} onDelete={() => { if (window.confirm('Delete this studio session?')) void action(removeSession); }} />
            </div>
          </div>
        </>}</div>
      </StudioTabs>
    </main>
  </div>;
}
