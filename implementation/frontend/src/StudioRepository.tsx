import { FALLBACK_BRANDING } from './config/branding';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { studioRequest, type Workspace, type StudioSession } from './studioApi';
import { StudioVoice, type StudioVoiceEvent } from './StudioVoice';
import { Icon, MentorPortrait } from './components/HorizonVisuals';
import { RedrivePanel } from './features/redrive/RedrivePanel';
import { DefenseFollowup } from './features/redrive/DefenseFollowup';
import { CodebaseLearningView } from './features/codebase/CodebaseLearningView';
import './repository-workspace.css';

type Snapshot = { snapshot_id: string; status: string; files_indexed?: number; total_files?: number; coverage_ratio?: number; failure_code?: string };
type Citation = { path: string; symbol: string; start_line: number; end_line: number; chunk_hash: string };
type SearchHit = Citation & { text: string };
type MapFile = { path: string; rank: number; imports: unknown; calls: unknown; symbols: unknown };
type SourceView = { path: string; content: string };
type Phase = 'map' | 'derive' | 'defend' | 'reflect';
type CitationView = { path: string; start_line: number; end_line: number; excerpt?: string };
type Evidence = { evidence_card_id?: string; topic?: string; origin?: string; observed_code?: CitationView[]; explicit_docs?: CitationView[]; inferred_rationale?: ({ hypothesis?: string } | string)[]; learner_alternative?: string | null };
type Decision = { topic: string; inferred_rationale: string; learner_alternative?: string; uncertainty?: string };
type Prompt = { phase: string; prompt: string; uncertainty?: string };
type DefenseAnswer = { phase: string; answer: string; citations: CitationView[]; changed_requirement?: string; learner_alternative?: string; unknowns?: string[] };
type DefenseState = { phase: Phase | 'complete'; mode?: string; prompt?: string; required_fields?: string[]; history: DefenseAnswer[]; synthesis?: { basis?: string }; snapshot_id?: string };
type Operation = { generation: number; signal: AbortSignal; current: () => boolean };
export type RepositoryPanelProps = {
  workspace?: Workspace;
  ensureWorkspace: () => Promise<Workspace>;
  onSnapshot: (id: string | null) => void;
  session?: StudioSession | null;
  /** The current server epoch and coach events, not a locally inferred voice turn. */
  speechEpoch?: number;
  speechEvents?: StudioVoiceEvent[];
  /** Active session binding; independent from the tab's exploration selection. */
  boundSnapshotId?: string | null;
  /** Refresh the shell's validated session snapshot / coach events after a transition. */
  onSessionChange?: () => void | Promise<void>;
  /** Hidden panels retain learning state but must release voice capture / playback. */
  active?: boolean;
  /** Whether to use the voice-first codebase learning mentor experience. */
  mentorMode?: boolean;
};
const TAB_KEY = 'viva-repo-tab-v1';
const MAX_CITATIONS = 10;
const MAX_EXCERPT = 400;
const PROMPTS: Record<Phase, string> = {
  map: 'Which files are responsible for this behavior? Walk me through the source.',
  derive: 'What constraints could explain this structure? Separate what you observe from what you infer.',
  defend: 'Which trade-offs and failure modes would you discuss? Anchor your explanation in the implementation.',
  reflect: 'Compare an alternative with the observed design. What remains unknown?',
};
const citationOf = ({ path, symbol, start_line, end_line, chunk_hash }: SearchHit): Citation => ({ path, symbol, start_line, end_line, chunk_hash });
const isDoc = (path: string) => /\.(md|rst|txt)$/i.test(path);
const sameCitation = (left: Citation, right: Citation) => left.path === right.path && left.chunk_hash === right.chunk_hash && left.start_line === right.start_line && left.end_line === right.end_line;

export function RepositoryPanel({ workspace, ensureWorkspace, onSnapshot, session, speechEpoch = 1, speechEvents = [], boundSnapshotId, onSessionChange, active: panelActive = true, mentorMode = false }: RepositoryPanelProps) {
  if (mentorMode) {
    return <CodebaseLearningView workspace={workspace} ensureWorkspace={ensureWorkspace} active={panelActive} />;
  }
  const activeBoundSnapshotId = session ? boundSnapshotId ?? null : null;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [explorationImport, setExplorationImport] = useState<Snapshot | null>(null);
  const [kind, setKind] = useState<'golden_curated' | 'public_git_url' | 'zip'>('public_git_url');
  const [source, setSource] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [map, setMap] = useState<MapFile[]>([]);
  const [view, setView] = useState<SourceView | null>(null);
  const [viewCitation, setViewCitation] = useState<Citation | null>(null);
  const [beginnerOpen, setBeginnerOpen] = useState(false);
  const [chosen, setChosen] = useState<SearchHit[]>([]);
  const [topic, setTopic] = useState('');
  const [rationale, setRationale] = useState('');
  const [alternative, setAlternative] = useState('');
  const [phase, setPhase] = useState<Phase>('derive');
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [answer, setAnswer] = useState('');
  const [defenseState, setDefenseState] = useState<DefenseState | null>(null);
  const [sessionRefresh, setSessionRefresh] = useState<Operation | null>(null);
  const [cards, setCards] = useState<Evidence[]>([]);
  const [selectedCards, setSelectedCards] = useState<string[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [changedRequirement, setChangedRequirement] = useState('');
  const [reflectAlternative, setReflectAlternative] = useState('');
  const [unknowns, setUnknowns] = useState('');
  const generation = useRef(0);
  const mounted = useRef(false);
  const pending = useRef<Set<AbortController>>(new Set());
  const active = useRef<number | null>(null);
  const lifecycle = useRef<number | null>(null);
  const completedRefresh = useRef<Operation | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);
  const ownerRef = useRef(workspace);
  const sessionRef = useRef(session);
  const bindingRef = useRef(activeBoundSnapshotId);
  const creatingWorkspace = useRef<{ generation: number; owner?: Workspace } | null>(null);
  const ready = snapshot?.status === 'READY';
  const projectReflect = defenseState?.phase === 'reflect' && defenseState.mode === 'project_defense';
  const unknownItems = unknowns.split('\n').map(item => item.trim()).filter(Boolean);
  const invalidUnknowns = unknownItems.length > MAX_CITATIONS || unknownItems.some(item => item.length > MAX_EXCERPT);
  const oversizedAnswer = answer.trim().length > 4000;
  const currentPhase = defenseState?.phase ?? phase;
  const question = defenseState?.prompt || prompt?.prompt || (currentPhase === 'complete' ? 'You have completed this defense. Revisit your cited statements and the unknowns you recorded.' : PROMPTS[currentPhase]);

  function invalidate() {
    generation.current += 1;
    creatingWorkspace.current = null;
    pending.current.forEach(controller => controller.abort());
    pending.current.clear();
    active.current = null; lifecycle.current = null;
    setBusy(false);
  }
  function operation(): Operation {
    const controller = new AbortController();
    const request = generation.current;
    pending.current.add(controller);
    return { generation: request, signal: controller.signal, current: () => mounted.current && generation.current === request && !controller.signal.aborted };
  }
  function resetDefense() {
    setDefenseState(null); setSessionRefresh(null); setAnswer(''); setChangedRequirement(''); setReflectAlternative(''); setUnknowns('');
  }
  function clearLearning() {
    resetDefense(); setMap([]); setHits([]); setView(null); setViewCitation(null); setBeginnerOpen(false); setChosen([]); setEvidence(null); setPrompt(null);
    setCards([]); setSelectedCards([]); setDecisions([]); setTopic(''); setRationale(''); setAlternative(''); setQuery('');
  }
  function showSnapshot(value: Snapshot | null) {
    snapshotRef.current = value;
    setSnapshot(value);
  }
  function release(op: Operation) {
    pending.current.forEach(controller => { if (controller.signal === op.signal) pending.current.delete(controller); });
  }
  function report(reason: unknown, op: Operation) {
    if (op.current()) setError(reason instanceof Error ? reason.message : 'The repository request failed. Please try again.');
  }
  async function run(task: (op: Operation) => Promise<void>, replace = false) {
    if (lifecycle.current !== null || (active.current !== null && !replace)) return;
    if (replace) invalidate();
    const op = operation(); active.current = op.generation; lifecycle.current = replace ? op.generation : null; setBusy(true); setError('');
    try { await task(op); }
    catch (reason) { report(reason, op); }
    finally {
      release(op);
      if (op.current() && active.current === op.generation) { active.current = null; lifecycle.current = null; setBusy(false); }
    }
  }
  function owner() {
    if (!workspace) throw new Error('The workspace is no longer available in this tab.');
    return workspace;
  }
  function repoPath(suffix = '') {
    if (!snapshot || snapshot.status !== 'READY') throw new Error('Wait for repository indexing to finish.');
    return `/repos/${encodeURIComponent(snapshot.snapshot_id)}${suffix}`;
  }

  useLayoutEffect(() => {
    const requests = pending.current;
    mounted.current = true;
    return () => { mounted.current = false; requests.forEach(controller => controller.abort()); requests.clear(); generation.current += 1; };
  }, []);
  useLayoutEffect(() => {
    const changedOwner = ownerRef.current?.id !== workspace?.id || ownerRef.current?.token !== workspace?.token;
    const changedSession = sessionRef.current?.id !== session?.id || sessionRef.current?.token !== session?.token;
    const changedBinding = bindingRef.current !== activeBoundSnapshotId;
    bindingRef.current = activeBoundSnapshotId;
    const creation = creatingWorkspace.current;
    const publishedCreation = !ownerRef.current && workspace && !changedSession && creation?.generation === generation.current
      && (!creation.owner || (creation.owner.id === workspace.id && creation.owner.token === workspace.token));
    ownerRef.current = workspace; sessionRef.current = session;
    if (publishedCreation) return;
    invalidate(); setError(''); resetDefense(); setChosen([]);
    if (changedOwner || changedBinding) { clearLearning(); showSnapshot(null); setExplorationImport(null); }
    if (changedOwner) onSnapshot(null);
    // Capability / binding changes fence work without replacing exploration metadata.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id, workspace?.token, session?.id, session?.token, activeBoundSnapshotId]);

  useEffect(() => {
    if (!workspace || snapshotRef.current) return;
    const op = operation();
    const requests = pending.current;
    let requestedId = activeBoundSnapshotId;
    if (!requestedId) {
      let stored: { workspace_id?: unknown; snapshot_id?: unknown } | null;
      try { stored = JSON.parse(sessionStorage.getItem(TAB_KEY) ?? 'null'); }
      catch { setError('Invalid repository tab metadata was ignored. Import a repository to continue.'); release(op); return; }
      if (stored?.workspace_id !== workspace.id || typeof stored.snapshot_id !== 'string' || !stored.snapshot_id) { release(op); return; }
      requestedId = stored.snapshot_id;
    }
    studioRequest<Snapshot>(`/repos/${encodeURIComponent(requestedId)}`, { workspace, signal: op.signal })
      .then(result => { if (op.current()) { showSnapshot(result); if (!activeBoundSnapshotId && result.status === 'READY') onSnapshot(result.snapshot_id); } })
      .catch(reason => report(reason, op)).finally(() => release(op));
    return () => { requests.forEach(controller => { if (controller.signal === op.signal) controller.abort(); }); release(op); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id, workspace?.token, session?.id, session?.token, activeBoundSnapshotId]);

  useEffect(() => {
    const indexedSnapshot = activeBoundSnapshotId ? explorationImport : snapshot;
    if (!workspace || !indexedSnapshot || !['QUEUED', 'INDEXING'].includes(indexedSnapshot.status)) return;
    const op = operation();
    const requests = pending.current;
    const timer = window.setTimeout(() => {
      studioRequest<Snapshot>(`/repos/${encodeURIComponent(indexedSnapshot.snapshot_id)}`, { workspace, signal: op.signal })
        .then(result => { if (op.current()) { if (activeBoundSnapshotId) setExplorationImport(result); else showSnapshot(result); if (result.status === 'READY') onSnapshot(result.snapshot_id); } })
        .catch(reason => report(reason, op)).finally(() => release(op));
    }, 1000);
    return () => { window.clearTimeout(timer); requests.forEach(controller => { if (controller.signal === op.signal) controller.abort(); }); release(op); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id, workspace?.token, snapshot, explorationImport, session?.id, session?.token, activeBoundSnapshotId]);

  useEffect(() => {
    if (!workspace || !ready || !snapshot) return;
    const op = operation();
    const requests = pending.current;
    const base = `/repos/${encodeURIComponent(snapshot.snapshot_id)}`;
    const load = async <T,>(suffix: string, apply: (result: T) => void) => {
      try { const result = await studioRequest<T>(base + suffix, { workspace, signal: op.signal }); if (op.current()) apply(result); }
      catch (reason) { report(reason, op); }
    };
    void Promise.all([
      load<{ files: MapFile[] }>('/map', result => setMap(Array.isArray(result.files) ? result.files : [])),
      load<{ cards: Evidence[] }>('/evidence', result => setCards(Array.isArray(result.cards) ? result.cards : [])),
    ]).finally(() => release(op));
    return () => { requests.forEach(controller => { if (controller.signal === op.signal) controller.abort(); }); release(op); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id, workspace?.token, snapshot?.snapshot_id, ready, session?.id, session?.token]);

  useEffect(() => {
    const op = sessionRefresh;
    if (!op?.current() || busy || completedRefresh.current === op) return;
    completedRefresh.current = op;
    // Commit voice availability before the shell supplies new coach.action events.
    // A callback identity change alone must not replay a completed transition.
    void (async () => { try { await onSessionChange?.(); } catch (reason) { report(reason, op); } })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionRefresh, busy]);

  async function ingest(op: Operation) {
    const importedKind = kind;
    const importedSource = source.trim();
    if (importedKind === 'zip' && !file) throw new Error('Choose a ZIP archive.');
    if (importedKind !== 'zip' && !importedSource) throw new Error('Choose a repository source.');
    if (!workspace) creatingWorkspace.current = { generation: op.generation };
    const workspaceOwner = workspace ?? await ensureWorkspace();
    if (!op.current()) return;
    if (!workspace) creatingWorkspace.current = { generation: op.generation, owner: workspaceOwner };
    if (ownerRef.current && (ownerRef.current.id !== workspaceOwner.id || ownerRef.current.token !== workspaceOwner.token)) throw new Error('The workspace changed during import. Try again in the current workspace.');
    let body: unknown = { source_kind: importedKind, source_locator: importedSource };
    if (importedKind === 'zip' && file) { const form = new FormData(); form.append('file', file); body = form; }
    const result = await studioRequest<Snapshot>('/repos/ingest', { method: 'POST', workspace: workspaceOwner, body, signal: op.signal });
    if (!op.current()) return;
    if (activeBoundSnapshotId) setExplorationImport(result);
    else { clearLearning(); showSnapshot(result); }
    onSnapshot(result.status === 'READY' ? result.snapshot_id : null);
    sessionStorage.setItem(TAB_KEY, JSON.stringify({ workspace_id: workspaceOwner.id, snapshot_id: result.snapshot_id }));
  }
  async function search(op: Operation) {
    if (!query.trim()) return;
    const result = await studioRequest<{ results: SearchHit[] }>(repoPath(`/search?q=${encodeURIComponent(query.trim())}`), { workspace: owner(), signal: op.signal });
    if (op.current()) setHits(result.results);
  }
  async function open(path: string, op: Operation) {
    const result = await studioRequest<SourceView>(repoPath(`/files?path=${encodeURIComponent(path)}`), { workspace: owner(), signal: op.signal });
    if (op.current()) { setView(result); setViewCitation(null); }
  }
  const openSource = (path: string) => { void run(op => open(path, op)); };
  const openCitation = (citation: Citation) => { void run(async op => {
    await open(citation.path, op);
    if (op.current()) setViewCitation(citation);
  }); };
  async function loadCards(op: Operation) {
    const result = await studioRequest<{ cards: Evidence[] }>(repoPath('/evidence'), { workspace: owner(), signal: op.signal });
    if (op.current()) setCards(result.cards);
  }
  async function loadDecisions(op: Operation) {
    const result = await studioRequest<{ decisions: Decision[] }>(repoPath('/decisions'), { workspace: owner(), signal: op.signal });
    if (op.current()) setDecisions(result.decisions);
  }
  async function refreshRepository(op: Operation) {
    const result = await studioRequest<{ files: MapFile[] }>(repoPath('/map'), { workspace: owner(), signal: op.signal });
    if (!op.current()) return;
    setMap(result.files);
    await Promise.all([loadCards(op), loadDecisions(op)]);
  }
  async function makeEvidence(op: Operation) {
    if (!topic.trim()) return;
    const result = await studioRequest<Evidence>(repoPath('/evidence'), { method: 'POST', workspace: owner(), signal: op.signal, body: {
      topic: topic.trim(), observed_code: chosen.filter(hit => !isDoc(hit.path)).map(citationOf),
      explicit_docs: chosen.filter(hit => isDoc(hit.path)).map(hit => ({ ...citationOf(hit), excerpt: hit.text.slice(0, MAX_EXCERPT) })),
      inferred_rationale: rationale.trim() ? [rationale.trim()] : [], learner_alternative: alternative.trim() || null,
    } });
    if (!op.current()) return;
    setEvidence(result); await loadCards(op);
  }
  async function saveDecision(op: Operation) {
    if (!topic.trim() || !rationale.trim() || !selectedCards.length) return;
    await studioRequest(repoPath('/decisions'), { method: 'POST', workspace: owner(), signal: op.signal, body: {
      topic: topic.trim(), evidence_card_ids: selectedCards, inferred_rationale: rationale.trim(), learner_alternative: alternative.trim() || null,
    } });
    if (op.current()) await loadDecisions(op);
  }
  async function getPrompt(op: Operation, manual = false) {
    const focus = (manual ? topic : answer).trim();
    if (!focus) return;
    const result = await studioRequest<Prompt>(repoPath('/defense'), { method: 'POST', workspace: owner(), signal: op.signal, body: {
      phase, topic: focus.slice(0, 200), citations: chosen.map(citationOf), learner_alternative: manual ? alternative.trim() || null : null,
    } });
    if (op.current()) setPrompt(result);
  }
  async function startDefense(op: Operation) {
    if (!session) return;
    const result = await studioRequest<DefenseState>(repoPath('/defense/start'), { method: 'POST', workspace: owner(), sessionToken: session.token, signal: op.signal, body: { studio_session_id: session.id } });
    if (op.current()) { setDefenseState(result); setPrompt(null); setSessionRefresh(op); }
  }
  async function answerDefense(op: Operation) {
    if (!session || !defenseState || defenseState.phase === 'complete' || !answer.trim() || !chosen.length || oversizedAnswer) return;
    if (projectReflect && (!changedRequirement.trim() || !reflectAlternative.trim() || invalidUnknowns)) return;
    const result = await studioRequest<DefenseState>(repoPath('/defense/answer'), { method: 'POST', workspace: owner(), sessionToken: session.token, signal: op.signal, body: {
      studio_session_id: session.id, expected_phase: defenseState.phase, answer: answer.trim(), citations: chosen.map(citationOf),
      evidence_links: chosen.map(hit => ({ kind: isDoc(hit.path) ? 'explicit_docs' : 'observed_code', claim: answer.trim(), citation: citationOf(hit), excerpt: hit.text.slice(0, MAX_EXCERPT) })),
      ...(projectReflect ? { changed_requirement: changedRequirement.trim(), learner_alternative: reflectAlternative.trim(), unknowns: unknownItems } : {}),
    } });
    if (op.current()) { setDefenseState(result); setAnswer(''); setChangedRequirement(''); setReflectAlternative(''); setUnknowns(''); setSessionRefresh(op); }
  }
  async function remove(op: Operation) {
    if (!snapshot) return;
    await studioRequest(`/repos/${encodeURIComponent(snapshot.snapshot_id)}`, { method: 'DELETE', workspace: owner(), signal: op.signal });
    if (!op.current()) return;
    clearLearning(); showSnapshot(null);
    if (!activeBoundSnapshotId) { sessionStorage.removeItem(TAB_KEY); onSnapshot(null); }
  }
  async function exportRecord(op: Operation) {
    const base = repoPath();
    const [savedCards, savedDecisions] = await Promise.all([
      studioRequest<{ cards: Evidence[] }>(base + '/evidence', { workspace: owner(), signal: op.signal }),
      studioRequest<{ decisions: Decision[] }>(base + '/decisions', { workspace: owner(), signal: op.signal }),
    ]);
    if (!op.current()) return;
    const record = { snapshot, map, evidence: savedCards.cards, decisions: savedDecisions.decisions, defense: defenseState, basis: 'Learner statements and cited source spans; author intent remains unknown. No truth grading.' };
    const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }));
    try { const link = document.createElement('a'); link.href = url; link.download = 'repository-learning.json'; link.click(); }
    finally { URL.revokeObjectURL(url); }
  }
  function choose(hit: SearchHit, checked: boolean) {
    if (checked && chosen.length >= MAX_CITATIONS) { setError('Choose at most ten source citations for one answer.'); return; }
    setChosen(checked ? [...chosen, hit] : chosen.filter(item => !sameCitation(item, hit)));
  }
  const importForm = <ImportSetup kind={kind} source={source} file={file} busy={busy} onKind={next => { setKind(next); setSource(next === 'golden_curated' ? 'REPO-EXP-01' : ''); setFile(null); }} onSource={setSource} onFile={setFile} onImport={() => void run(ingest, true)} />;
  const blockedAnswer = busy || !ready || !answer.trim() || !chosen.length || oversizedAnswer || (projectReflect && (!changedRequirement.trim() || !reflectAlternative.trim() || invalidUnknowns));

  return <section className="repository-workspace" aria-label="Repository workspace" aria-busy={busy}>
    <header className="repo-heading"><div><h2>Learn the code. Defend the why.</h2><p>Talk it through with your mentor, with source evidence beside you.</p></div><Icon name="book" /></header>
    {error && <p role="alert" className="studio-error">{error}</p>}
    {!snapshot ? <section className="repo-import"><h3>Bring a codebase</h3>{importForm}<p className="repo-note">Public repositories and ZIP archives are treated as data. Indexing never executes repository code.</p></section> : <section className="repo-snapshot-bar" aria-label="Repository snapshot">
      <div><strong>Index status: {snapshot.status}</strong>{ready ? <p>Indexed {snapshot.files_indexed ?? 0} of {snapshot.total_files ?? 0} files. Coverage: {Math.round((snapshot.coverage_ratio ?? 0) * 100)}%.</p> : <p role="status">{snapshot.status === 'FAILED' ? `Import failed: ${snapshot.failure_code ?? 'unknown error'}` : 'Indexing in progress…'}</p>}</div>
      <Disclosure title="Replace repository">{importForm}</Disclosure>
    </section>}
    {activeBoundSnapshotId && <p className="repo-note">This session stays bound to its original codebase. Imports are saved separately for exploration.</p>}
    {activeBoundSnapshotId && explorationImport && <p className="repo-note" role="status">Exploration import: {explorationImport.status}{explorationImport.status === 'FAILED' ? ` — ${explorationImport.failure_code ?? 'import failed'}` : ''}. Your current defense stays on its bound source.</p>}
    <div className="repo-learning-grid">
      <section className="repo-mentor" aria-label="Repository mentor">
        <header className="repo-mentor-identity"><MentorPortrait state={busy ? 'thinking' : 'idle'} eager /><div><h3>Your mentor</h3><p>Evidence first. Your reasoning matters.</p></div></header>
        {ready && workspace && <div className="repo-conversation"><button type="button" disabled={busy} aria-expanded={beginnerOpen} onClick={() => setBeginnerOpen(value => !value)}>{beginnerOpen ? 'Return to repository defense' : 'Teach me from the beginning'}</button></div>}
        {beginnerOpen && ready && workspace && snapshot && <RedrivePanel key={`${workspace.id}:${snapshot.snapshot_id}`} workspace={workspace} snapshotId={snapshot.snapshot_id} onOpenSource={openCitation} session={session} speechEpoch={speechEpoch} active={panelActive && !busy} />}
        <div hidden={beginnerOpen}>
        <div className="repo-conversation">
          <div className="repo-phase-switch" role="group" aria-label="Learning focus">
            <button type="button" aria-pressed={currentPhase === 'derive' || currentPhase === 'map'} disabled={busy || !!defenseState} onClick={() => { setPhase('derive'); setPrompt(null); }}>Derive</button>
            <button type="button" aria-pressed={currentPhase === 'defend' || currentPhase === 'reflect' || currentPhase === 'complete'} disabled={busy || !!defenseState} onClick={() => { setPhase('defend'); setPrompt(null); }}>Defense</button>
          </div>
          {defenseState && <p className="repo-phase">Current stage: {defenseState.phase}</p>}
          <p className="repo-mentor-question">{ready ? question : 'Bring a repository, then we’ll explore its structure together.'}</p>
          {defenseState?.history.length ? <><p className="repo-last-answer"><strong>You</strong>{defenseState.history[defenseState.history.length - 1].answer}</p><DefenseFollowup phase={defenseState.history[defenseState.history.length - 1].phase} answer={defenseState.history[defenseState.history.length - 1].answer} citations={defenseState.history[defenseState.history.length - 1].citations} onOpenSource={openCitation} /></> : null}
          <p className="repo-note">Observed code, documented claims, and your hypotheses are distinct. Static source does not establish runtime behavior or author intent.</p>
          {!session && ready && <p className="repo-note">Explore with a prompt now. Open a repository-backed studio session for voice and a saved defense.</p>}
          {session && ready && !defenseState && <button type="button" className="primary repo-start" disabled={busy} onClick={() => void run(startDefense)}>Start or resume defense</button>}
          {defenseState?.phase === 'complete' && <p role="status">Defense completed. Review the cited history below.</p>}
        </div>
        <div className="repo-composer">
          {session && <StudioVoice key={`${session.id}:${snapshot?.snapshot_id ?? 'setup'}`} session={session} epoch={speechEpoch} events={speechEvents} disabled={beginnerOpen || !panelActive || busy || !ready || defenseState?.phase === 'complete'} onTranscript={text => setAnswer(current => current ? `${current}\n${text}` : text)} />}
          {ready && defenseState?.phase !== 'complete' && <>
            <label>Your explanation<textarea value={answer} maxLength={4000} disabled={busy} placeholder="Talk first, or type your reasoning here…" onChange={event => setAnswer(event.target.value)} /></label>
            {projectReflect && <Disclosure title="Reflection details"><p className="repo-note">Name the changed requirement and your alternative explicitly. Spoken explanations are not parsed into these fields.</p><label>Changed requirement<input value={changedRequirement} maxLength={2000} onChange={event => setChangedRequirement(event.target.value)} disabled={busy} /></label><label>Your alternative<input value={reflectAlternative} maxLength={2000} onChange={event => setReflectAlternative(event.target.value)} disabled={busy} /></label><label>Unknowns (optional)<textarea value={unknowns} onChange={event => setUnknowns(event.target.value)} placeholder="One unknown per line (up to 10)." disabled={busy} /></label></Disclosure>}
            <p className="repo-note">{chosen.length ? `${chosen.length} source citation${chosen.length === 1 ? '' : 's'} selected.` : 'Choose a source citation in Search source to support your answer.'} Review the draft before sending. Voice never submits for you.</p>
            {defenseState ? <button type="button" className="primary repo-submit" disabled={blockedAnswer} onClick={() => void run(answerDefense)}>Submit defense answer<Icon name="arrow" /></button> : !session ? <button type="button" className="primary repo-submit" disabled={busy || !answer.trim()} onClick={() => void run(op => getPrompt(op))}>Get mentor prompt<Icon name="arrow" /></button> : null}
            {oversizedAnswer && <p role="alert" className="repo-note">Your transcript is preserved. Shorten it to 4,000 characters before submitting.</p>}
            {projectReflect && invalidUnknowns && <p role="alert" className="repo-note">Keep unknowns to ten lines, up to 400 characters each.</p>}
            {projectReflect && (!changedRequirement.trim() || !reflectAlternative.trim()) && <p className="repo-note">Add the changed requirement and your alternative in Reflection details to continue.</p>}
          </>}
          {defenseState && <Disclosure title="Defense history">{defenseState.history.length ? defenseState.history.map((item, index) => <DefenseHistory key={index} value={item} onOpen={openSource} />) : <p>No answers recorded yet.</p>}{defenseState.synthesis?.basis && <p className="repo-note">{defenseState.synthesis.basis}</p>}</Disclosure>}
        </div>
        </div>
      </section>
      <section className="repo-evidence" aria-label="Evidence browser">
        <header><h3><Icon name="code" />Source evidence</h3><p className="repo-note">Read the source. Cite the exact span. Keep inference separate.</p></header>
        {!ready ? <p className="repo-empty">Your indexed repository will appear here.</p> : <>
          <Disclosure title="Search source"><form onSubmit={event => { event.preventDefault(); void run(search); }} className="repo-search"><label>Search code<input value={query} maxLength={200} disabled={busy} placeholder="Find a symbol, file, or phrase" onChange={event => setQuery(event.target.value)} /></label><button type="submit" disabled={busy || !query.trim()}>Search</button></form>
            {hits.length ? <ul className="repo-hits">{hits.map(hit => <li key={`${hit.path}:${hit.start_line}:${hit.chunk_hash}`}><button type="button" disabled={busy} className="repo-source-link" onClick={() => openSource(hit.path)}>{hit.path}:{hit.start_line}–{hit.end_line} {hit.symbol}</button><pre>{hit.text}</pre><label className="studio-check"><input type="checkbox" disabled={busy || (chosen.length >= MAX_CITATIONS && !chosen.some(item => sameCitation(item, hit)))} checked={chosen.some(item => sameCitation(item, hit))} onChange={event => choose(hit, event.target.checked)} />Use this citation</label></li>)}</ul> : <p className="repo-note">Search the indexed source to select exact citations.</p>}
          </Disclosure>
          {chosen.length > 0 && <div className="repo-selected"><strong>Selected source spans</strong><ul>{chosen.map(hit => <li key={`${hit.path}:${hit.start_line}:${hit.chunk_hash}`}><span>{hit.path}:{hit.start_line}–{hit.end_line}</span><button type="button" disabled={busy} aria-label={`Remove citation ${hit.path}:${hit.start_line}`} onClick={() => choose(hit, false)}>×</button></li>)}</ul></div>}
          <div className="repo-map"><h4>Repository map</h4>{map.length ? <ul>{map.map(item => <li key={item.path}><button type="button" disabled={busy} onClick={() => openSource(item.path)}><Icon name="code" />{item.path}</button></li>)}</ul> : <p className="repo-note">No source files listed yet.</p>}</div>
          {view && <section className="repo-source-view" aria-label="Open source file"><h4>{view.path}</h4>{viewCitation && <p className="repo-note">Selected lines {viewCitation.start_line}–{viewCitation.end_line} · sha256:{viewCitation.chunk_hash}</p>}<pre>{view.content.split('\n').map((line, index) => <span key={index}>{viewCitation && index + 1 >= viewCitation.start_line && index + 1 <= viewCitation.end_line ? <mark>{`${String(index + 1).padStart(4, ' ')}  ${line}`}</mark> : `${String(index + 1).padStart(4, ' ')}  ${line}`}{'\n'}</span>)}</pre></section>}
          <Disclosure title="Saved evidence and decisions" onExpand={() => void run(loadDecisions)}>{cards.length ? cards.map((item, index) => <EvidenceCard key={item.evidence_card_id ?? index} value={item} onOpen={openSource} />) : <p>No saved evidence cards yet.</p>}{decisions.length ? decisions.map((item, index) => <DecisionCard key={index} value={item} />) : <p className="repo-note">No saved decisions yet.</p>}</Disclosure>
          <Disclosure title="Advanced evidence tools"><p className="repo-note">Optional manual tools. They are not required to talk through a defense.</p><fieldset disabled={busy} className="repo-manual"><legend className="sr-only">Manual evidence and decisions</legend><label>Topic<input value={topic} maxLength={200} onChange={event => setTopic(event.target.value)} /></label><label>Inferred rationale<textarea value={rationale} maxLength={400} onChange={event => setRationale(event.target.value)} /></label><label>Your alternative<textarea value={alternative} maxLength={2000} onChange={event => setAlternative(event.target.value)} /></label><button type="button" disabled={!topic.trim()} onClick={() => void run(makeEvidence)}>Create evidence card</button>{evidence && <EvidenceCard value={evidence} onOpen={openSource} />}
            {cards.map(item => item.evidence_card_id && <label key={item.evidence_card_id} className="studio-check"><input type="checkbox" checked={selectedCards.includes(item.evidence_card_id)} disabled={selectedCards.length >= MAX_CITATIONS && !selectedCards.includes(item.evidence_card_id)} onChange={event => { const id = item.evidence_card_id!; setSelectedCards(event.target.checked ? [...selectedCards, id] : selectedCards.filter(value => value !== id)); }} />{item.topic ?? 'Saved evidence card'} — use in a decision</label>)}
            <button type="button" disabled={!topic.trim() || !rationale.trim() || !selectedCards.length} onClick={() => void run(saveDecision)}>Save decision from selected evidence</button><label>Defense stage<select value={phase} onChange={event => setPhase(event.target.value as Phase)}><option value="map">Map</option><option value="derive">Derive</option><option value="defend">Defend</option><option value="reflect">Reflect</option></select></label><button type="button" disabled={!topic.trim()} onClick={() => void run(op => getPrompt(op, true))}>Get defense prompt</button>{prompt && <p>{prompt.prompt}</p>}</fieldset></Disclosure>
          <Disclosure title="Snapshot tools"><p className="repo-note">Source is sanitized, but secret scanners are heuristic. A snapshot cannot be deleted while an active session references it. Exports contain source evidence and your learning record, not capability tokens.</p><div className="studio-actions"><button type="button" disabled={busy} onClick={() => void run(refreshRepository)}>Refresh repository data</button><button type="button" disabled={busy} onClick={() => void run(exportRecord)}>Export learning record</button><button type="button" className="danger" onClick={() => { if (window.confirm('Delete this repository snapshot?')) void run(remove, true); }}>Delete snapshot</button></div></Disclosure>
        </>}
        {snapshot && !ready && <Disclosure title="Snapshot tools"><p className="repo-note">A snapshot cannot be deleted while an active session references it.</p><button type="button" className="danger" onClick={() => { if (window.confirm('Delete this repository snapshot?')) void run(remove, true); }}>Delete snapshot</button></Disclosure>}
      </section>
    </div>
  </section>;
}

function Disclosure({ title, children, onExpand }: { title: string; children: ReactNode; onExpand?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return <details className="repo-disclosure" open={expanded} aria-label={title}><summary onClick={event => { event.preventDefault(); if (!expanded) onExpand?.(); setExpanded(value => !value); }}>{title}</summary>{expanded && <div>{children}</div>}</details>;
}
function ImportSetup({ kind, source, file, busy, onKind, onSource, onFile, onImport }: {
  kind: 'golden_curated' | 'public_git_url' | 'zip'; source: string; file: File | null; busy: boolean;
  onKind: (kind: 'golden_curated' | 'public_git_url' | 'zip') => void; onSource: (value: string) => void; onFile: (value: File | null) => void; onImport: () => void;
}) {
  const id = useId();
  const sources = [{ kind: 'public_git_url', label: 'Public URL' }, { kind: 'zip', label: 'ZIP archive' }, { kind: 'golden_curated', label: 'Curated example' }] as const;
  function select(index: number) { onKind(sources[index].kind); document.getElementById(`${id}-${sources[index].kind}`)?.focus(); }
  return <form className="repo-import-form" onSubmit={event => { event.preventDefault(); onImport(); }}>
    <div className="repo-source-tabs" role="tablist" aria-label="Repository source">{sources.map((item, index) => <button type="button" role="tab" key={item.kind} id={`${id}-${item.kind}`} aria-selected={kind === item.kind} aria-controls={`${id}-source`} tabIndex={kind === item.kind ? 0 : -1} disabled={busy} onClick={() => onKind(item.kind)} onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); select((index + (event.key === 'ArrowRight' ? 1 : sources.length - 1)) % sources.length); } else if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); select(event.key === 'Home' ? 0 : sources.length - 1); } }}>{item.label}</button>)}</div>
    <div role="tabpanel" id={`${id}-source`} aria-labelledby={`${id}-${kind}`} className="repo-import-row">{kind === 'golden_curated' ? <label>Example<select disabled={busy} value={source} onChange={event => onSource(event.target.value)}><option value="REPO-EXP-01">{FALLBACK_BRANDING.productName} architecture</option><option value="REPO-EXP-02">Event-driven service</option></select></label> : kind === 'public_git_url' ? <label>Public HTTPS URL<input key="public-url" type="url" required disabled={busy} value={source} placeholder="https://github.com/owner/repository" onChange={event => onSource(event.target.value)} /></label> : <label>ZIP archive<input key="zip-file" type="file" disabled={busy} accept=".zip,application/zip" onChange={event => onFile(event.target.files?.[0] ?? null)} /></label>}<button type="submit" className="primary" disabled={busy || (kind === 'zip' ? !file : !source.trim())}>Import and index<Icon name="arrow" /></button></div>
  </form>;
}
function Citations({ items, onOpen }: { items: CitationView[]; onOpen: (path: string) => void }) {
  return items.length ? <ul className="repo-citations">{items.map((item, index) => <li key={index}><button type="button" onClick={() => onOpen(item.path)}>{item.path}, lines {item.start_line}–{item.end_line}</button>{item.excerpt && <blockquote>{item.excerpt}</blockquote>}</li>)}</ul> : <p className="repo-note">None recorded.</p>;
}
function EvidenceCard({ value, onOpen }: { value: Evidence; onOpen: (path: string) => void }) {
  return <article className="repo-result"><h4>{value.topic ?? 'Evidence'}</h4><strong>Observed code</strong><Citations items={value.observed_code ?? []} onOpen={onOpen} /><strong>Explicit documentation</strong><Citations items={value.explicit_docs ?? []} onOpen={onOpen} /><strong>Inferred rationale</strong><p>{value.inferred_rationale?.map(item => typeof item === 'string' ? item : item.hypothesis).join('; ') || 'None recorded.'}</p><p className="repo-note">Inference does not establish author intent.</p>{value.learner_alternative && <p><strong>Your alternative:</strong> {value.learner_alternative}</p>}</article>;
}
function DecisionCard({ value }: { value: Decision }) {
  return <article className="repo-result"><h4>{value.topic}</h4><p><strong>Inferred rationale:</strong> {value.inferred_rationale}</p>{value.learner_alternative && <p><strong>Your alternative:</strong> {value.learner_alternative}</p>}<p className="repo-note">{value.uncertainty ?? 'Inference; author intent is not established.'}</p></article>;
}
function DefenseHistory({ value, onOpen }: { value: DefenseAnswer; onOpen: (path: string) => void }) {
  return <article className="repo-result"><h4>{value.phase}</h4><p>{value.answer}</p><Citations items={value.citations ?? []} onOpen={onOpen} />{value.changed_requirement && <p><strong>Changed requirement:</strong> {value.changed_requirement}</p>}{value.learner_alternative && <p><strong>Your alternative:</strong> {value.learner_alternative}</p>}{value.unknowns?.length ? <p><strong>Unknowns:</strong> {value.unknowns.join('; ')}</p> : null}</article>;
}
