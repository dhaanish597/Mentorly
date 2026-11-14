import { useState } from 'react';
import type { ComponentProps } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge, Node, ReactFlowProps } from '@xyflow/react';
import type { Graph, StudioSession } from '../studioApi';
import { StudioAssumptions } from '../StudioAssumptions';
import { StudioNodeProperties, StudioEdgeProperties, nodePosition } from '../StudioProperties';
import { StudioGraph } from '../StudioGraph';
import { StudioMentor } from '../StudioMentor';
import { StudioSessionTools } from '../StudioSessionTools';
import { StudioSetup } from '../StudioSetup';
import { EvaluationView, FeedbackView, GraphComparison, SummaryView, parseObject, readable } from '../StudioViews';
import type { RequiredField, ScenarioView, Snapshot } from '../StudioViews';

// Component doubles expose the real ReactFlow callbacks; applyNodeChanges remains the library implementation.
const flowCapture = vi.hoisted(() => vi.fn());
vi.mock('@xyflow/react', async importOriginal => {
  const actual = await importOriginal<typeof import('@xyflow/react')>();
  return { ...actual, ReactFlow: (props: ReactFlowProps<Node, Edge>) => { flowCapture(props); return <div>{props.children}</div>; }, Background: () => null, Controls: () => null };
});
vi.mock('../StudioVoice', () => ({ StudioVoice: ({ onTranscript }: { onTranscript: (text: string) => void }) => <button onClick={() => onTranscript('Reviewed voice draft')}>Append reviewed speech</button> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const workspace = { id: 'workspace', token: 'synthetic-workspace-capability' };
const session: StudioSession = { id: 'session', token: 'synthetic-session-capability', workspace };
const graph: Graph = {
  nodes: [
    { node_id: 'gateway', kind: 'service', label: 'Gateway', replica_count: 2, statefulness: 'stateless', partition_key: 'tenant_id', consistency_mode: 'eventual', notes: 'Retries are bounded.', properties: { position: { x: 25, y: 40 }, retry_policy: 'bounded' } },
    { node_id: 'store', kind: 'database', label: 'Store', replica_count: 3, statefulness: 'stateful', partition_key: 'account_id', consistency_mode: 'strong', notes: 'Replicated storage.', properties: { position: { x: 250, y: 120 } } },
  ],
  edges: [{ edge_id: 'wire', source_node_id: 'gateway', target_node_id: 'store', protocol: 'HTTPS', directionality: 'directed', rate_estimate_rps: 100, failure_behavior: 'Retry with a limit' }],
  assumptions: { requests_per_second: 100, latency_seconds: 0.2, unit: 'requests/s' },
};
const scenario: ScenarioView = { id: 'SD-01', version: '1', title: 'Reliable service', problem_statement: 'Design a reliable service.', prerequisites: ['Queues'], learning_objectives: ['Bound retries'], linked_exercise_ids: ['exercise/queue'], constraint_index: 0, constraint: { id: 'C0', title: 'Bound retries', description: 'Declare the failure policy.' }, hint_level: 0, clarification_facts: ['Retries must be bounded.'] };
const turn = { id: 'turn', epoch: 4, diagram_revision: 3, kind: 'explain', content: 'Bound the retries.', created_at: '2026-11-14T10:00:00Z', transcript_revision: 1, superseded_by: null };
const snapshot: Snapshot = { session_id: session.id, epoch: 4, diagram_revision: 3, posture: 'teaching', state: 'active', graph, events: [], turns: [turn] };
const change = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const open = (name: string) => fireEvent.click(screen.getByText(name, { selector: 'summary' }));
const flow = () => flowCapture.mock.calls[flowCapture.mock.calls.length - 1][0] as ReactFlowProps<Node, Edge>;

function AssumptionsHarness({ callbacks, fields = [], initial = graph }: { callbacks: { edit: (value: Graph) => void; text: (value: string) => void; error: (value: string) => void }; fields?: RequiredField[]; initial?: Graph }) {
  const [value, setValue] = useState(initial);
  const [text, setText] = useState(JSON.stringify(initial.assumptions, null, 2));
  return <StudioAssumptions graph={value} fields={fields} text={text} pending={text !== JSON.stringify(value.assumptions, null, 2)} onEdit={next => { callbacks.edit(next); setValue(next); }} onText={next => { callbacks.text(next); setText(next); }} onError={callbacks.error} />;
}
const assumptionCallbacks = () => ({ edit: vi.fn<(value: Graph) => void>(), text: vi.fn<(value: string) => void>(), error: vi.fn<(value: string) => void>() });

describe('typed and advanced assumptions', () => {
  it('updates numbers, booleans, declared choices and units without changing diagram topology', () => {
    const callbacks = assumptionCallbacks();
    const fields: RequiredField[] = [{ key: 'requests_per_second', type: 'number', description: 'requests/s' }, { key: 'durable', type: 'boolean' }, { key: 'strategy', type: 'enum', values: ['bounded', 'none'] }, { key: 'unit', type: 'string' }, { key: 'retry_policy', type: 'policy' }, { key: 'store_property', type: 'property' }];
    render(<AssumptionsHarness callbacks={callbacks} fields={fields} />);
    change(/requests per second/, '250');
    change('durable', 'true');
    change('durable', 'false');
    change('strategy', 'bounded');
    change('unit', 'events/s');
    expect(callbacks.edit.mock.calls[callbacks.edit.mock.calls.length - 1]?.[0]).toEqual({ ...graph, assumptions: { ...graph.assumptions, requests_per_second: 250, durable: false, strategy: 'bounded', unit: 'events/s' } });
    expect(screen.queryByLabelText('retry policy')).toBeNull();
    expect(screen.queryByLabelText('store property')).toBeNull();
    change('durable', ''); change('strategy', ''); change('unit', ''); change(/requests per second/, '');
    expect(callbacks.edit.mock.calls[callbacks.edit.mock.calls.length - 1]?.[0].assumptions).toEqual({ latency_seconds: 0.2 });
    expect(graph.assumptions.requests_per_second).toBe(100);
  });
  it('requires explicit JSON application, supports discard and preserves unknown capacity inputs', () => {
    const callbacks = assumptionCallbacks();
    render(<AssumptionsHarness callbacks={callbacks} />);
    expect(screen.getByText(/No typed assumptions/)).toBeTruthy();
    open('Advanced assumptions JSON');
    expect(screen.getByRole('button', { name: 'Apply assumptions' }).matches(':disabled')).toBe(true);
    change('Assumptions (JSON object)', '{"read_rps":1000,"miss_fraction":0.25}');
    expect(callbacks.edit).not.toHaveBeenCalled();
    click('Apply assumptions');
    expect(callbacks.edit).toHaveBeenCalledWith({ ...graph, assumptions: { read_rps: 1000, miss_fraction: 0.25 } });
    change('Assumptions (JSON object)', '{"read_rps":5}'); click('Discard assumptions draft');
    expect((screen.getByLabelText('Assumptions (JSON object)') as HTMLTextAreaElement).value).toContain('1000');
    open('Capacity estimates');
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0);
    expect(screen.getByText('250')).toBeTruthy();
  });
  it('rejects invalid JSON and blocks typed changes until the draft is repaired', () => {
    const callbacks = assumptionCallbacks();
    render(<AssumptionsHarness callbacks={callbacks} fields={[{ key: 'requests_per_second', type: 'number' }]} />);
    open('Advanced assumptions JSON'); change('Assumptions (JSON object)', '[]');
    expect(screen.getByRole('alert').textContent).toMatch(/valid assumptions JSON object/);
    change('requests per second', '50');
    expect(callbacks.error).toHaveBeenCalledWith('Fix the assumptions JSON before editing typed fields.');
    click('Apply assumptions');
    expect(callbacks.error).toHaveBeenCalledWith('Enter a valid assumptions JSON object.');
    expect(callbacks.edit).not.toHaveBeenCalled();
    expect(screen.getByText('Enter a valid assumptions object to calculate.')).toBeTruthy();
    click('Discard assumptions draft');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('component and connection properties', () => {
  it.each([
    ['Label', 'Worker', { label: 'Worker' }], ['Kind', 'queue', { kind: 'queue' }], ['Replicas', '4', { replica_count: 4 }],
    ['Statefulness', 'stateful', { statefulness: 'stateful' }], ['Partition key', 'event_id', { partition_key: 'event_id' }],
    ['Consistency', 'strong', { consistency_mode: 'strong' }], ['Notes', 'Bound the retry window.', { notes: 'Bound the retry window.' }],
    ['Horizontal position', '300', { properties: { ...graph.nodes[0].properties, position: { x: 300, y: 40 } } }],
    ['Vertical position', '75', { properties: { ...graph.nodes[0].properties, position: { x: 25, y: 75 } } }],
  ])('forwards the typed %s edit as a focused node patch', (label, value, expected) => {
    const onChange = vi.fn();
    render(<StudioNodeProperties node={graph.nodes[0]} index={0} requiredFields={[]} onChange={onChange} onRemove={vi.fn()} />);
    change(String(label), String(value)); expect(onChange).toHaveBeenCalledWith(expected);
  });
  it('edits suggested policies, removes undeclared policies and preserves other properties', () => {
    const onChange = vi.fn(); const onRemove = vi.fn();
    render(<StudioNodeProperties node={graph.nodes[0]} index={0} requiredFields={[{ key: 'retry_policy', type: 'policy', description: 'failure strategy', values: ['bounded', 'none', 100] }, { key: 'new_property', type: 'property' }, { key: 'rate', type: 'number' }]} onChange={onChange} onRemove={onRemove} />);
    change(/retry policy/, 'none');
    expect(onChange).toHaveBeenCalledWith({ properties: { ...graph.nodes[0].properties, retry_policy: 'none' } });
    change(/retry policy/, '');
    expect(onChange).toHaveBeenCalledWith({ properties: { position: { x: 25, y: 40 } } });
    change('new property', 'documented');
    expect(onChange).toHaveBeenCalledWith({ properties: { ...graph.nodes[0].properties, new_property: 'documented' } });
    expect(screen.queryByLabelText('rate')).toBeNull();
    expect(document.querySelectorAll('datalist option')).toHaveLength(2);
    click('Remove component'); expect(onRemove).toHaveBeenCalledOnce();
  });
  it('validates advanced properties and resynchronizes after a canonical node update', () => {
    const onChange = vi.fn(); const props = { node: graph.nodes[0], index: 0, requiredFields: [], onChange, onRemove: vi.fn() };
    const view = render(<StudioNodeProperties {...props} />);
    open('Advanced component properties'); change('Properties (JSON object)', '{'); click('Apply properties');
    expect(screen.getByRole('alert').textContent).toMatch(/valid JSON object/);
    expect(onChange).not.toHaveBeenCalled();
    change('Properties (JSON object)', '{"position":{"x":10,"y":20},"retry_policy":"none"}'); click('Apply properties');
    expect(onChange).toHaveBeenCalledWith({ properties: { position: { x: 10, y: 20 }, retry_policy: 'none' } });
    expect(screen.queryByRole('alert')).toBeNull();
    view.rerender(<StudioNodeProperties {...props} node={{ ...graph.nodes[0], properties: { position: { x: 90, y: 60 }, canonical: true } }} />);
    expect((screen.getByLabelText('Properties (JSON object)') as HTMLTextAreaElement).value).toContain('"canonical": true');
    expect(nodePosition({ ...graph.nodes[0], properties: {} }, 4)).toEqual({ x: 250, y: 180 });
  });
  it.each([
    ['Source', 'store', { source_node_id: 'store' }], ['Target', 'gateway', { target_node_id: 'gateway' }],
    ['Protocol', 'gRPC', { protocol: 'gRPC' }], ['Directionality', 'bidirectional', { directionality: 'bidirectional' }],
    ['Estimated requests per second', '450', { rate_estimate_rps: 450 }], ['Estimated requests per second', '', { rate_estimate_rps: null }],
    ['Failure behavior', 'Fail fast', { failure_behavior: 'Fail fast' }],
  ])('forwards the typed %s edit as a focused connection patch', (label, value, expected) => {
    const onChange = vi.fn();
    render(<StudioEdgeProperties edge={graph.edges[0]} index={0} graph={graph} onChange={onChange} onRemove={vi.fn()} />);
    change(String(label), String(value)); expect(onChange).toHaveBeenCalledWith(expected);
  });
  it('renders an unknown connection rate and delegates removal', () => {
    const onRemove = vi.fn();
    render(<StudioEdgeProperties edge={{ ...graph.edges[0], rate_estimate_rps: null }} index={0} graph={graph} onChange={vi.fn()} onRemove={onRemove} />);
    expect((screen.getByLabelText('Estimated requests per second') as HTMLInputElement).value).toBe('');
    click('Remove connection'); expect(onRemove).toHaveBeenCalledOnce();
  });
});

function graphCallbacks() {
  return { edit: vi.fn<(value: Graph) => void>(), position: vi.fn<(value: Graph) => void>(), commit: vi.fn<(value: Graph) => void>(), node: vi.fn(), edge: vi.fn(), remove: vi.fn(), addNode: vi.fn(), addEdge: vi.fn(), text: vi.fn(), error: vi.fn(), check: vi.fn() };
}
function GraphHarness({ callbacks, initial = graph, locked = false }: { callbacks: ReturnType<typeof graphCallbacks>; initial?: Graph; locked?: boolean }) {
  const [value, setValue] = useState(initial);
  const [text, setText] = useState(JSON.stringify(initial.assumptions, null, 2));
  return <StudioGraph graph={value} locked={locked} assumptionsText={text} assumptionsPending={text !== JSON.stringify(value.assumptions, null, 2)} requiredFields={[{ key: 'requests_per_second', type: 'number' }]}
    onAssumptionsText={next => { callbacks.text(next); setText(next); }} onError={callbacks.error}
    onEdit={next => { callbacks.edit(next); setValue(next); }} onPosition={next => { callbacks.position(next); setValue(next); }} onDragCommit={callbacks.commit}
    onAddNode={() => { callbacks.addNode(); const id = `new-${value.nodes.length}`; setValue({ ...value, nodes: [...value.nodes, { ...graph.nodes[0], node_id: id, label: 'New component' }] }); return id; }}
    onAddEdge={(source = value.nodes[0]?.node_id, target = value.nodes[1]?.node_id) => { callbacks.addEdge(source, target); if (!source || !target) return undefined; const id = `edge-${value.edges.length}`; setValue({ ...value, edges: [...value.edges, { ...graph.edges[0], edge_id: id, source_node_id: source, target_node_id: target }] }); return id; }}
    onUpdateNode={(index, patch) => { callbacks.node(index, patch); setValue({ ...value, nodes: value.nodes.map((node, i) => i === index ? { ...node, ...patch } : node) }); }}
    onRemoveNode={index => { callbacks.remove(index); const id = value.nodes[index].node_id; setValue({ ...value, nodes: value.nodes.filter(node => node.node_id !== id), edges: value.edges.filter(edge => edge.source_node_id !== id && edge.target_node_id !== id) }); }}
    onUpdateEdge={(index, patch) => { callbacks.edge(index, patch); setValue({ ...value, edges: value.edges.map((edge, i) => i === index ? { ...edge, ...patch } : edge) }); }}
    checkDisabled={locked} onCheck={callbacks.check} evaluation={{ status: 'satisfied', reason: 'Declared assumptions are checked.' }} validation={{ mechanism_status: 'unknown' }} />;
}

describe('canonical architecture presentation callbacks', () => {
  it('groups a drag as one history commit and does not pollute history with selection', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} />);
    act(() => flow().onNodesChange?.([{ type: 'select', id: 'gateway', selected: true }]));
    expect(callbacks.edit).not.toHaveBeenCalled();
    const original = flow().nodes?.[0];
    act(() => flow().onNodeDragStart?.({} as Parameters<NonNullable<ReactFlowProps['onNodeDragStart']>>[0], original!, flow().nodes!));
    act(() => flow().onNodesChange?.([{ type: 'position', id: 'gateway', position: { x: 150, y: 200 }, dragging: true }]));
    expect(callbacks.position.mock.calls[0][0].nodes[0].properties.position).toEqual({ x: 150, y: 200 });
    expect(callbacks.edit).not.toHaveBeenCalled();
    act(() => flow().onNodeDragStop?.({} as Parameters<NonNullable<ReactFlowProps['onNodeDragStop']>>[0], flow().nodes![0], flow().nodes!));
    expect(callbacks.commit).toHaveBeenCalledWith(graph);
    expect(graph.nodes[0].properties.position).toEqual({ x: 25, y: 40 });
    act(() => flow().onNodesChange?.([{ type: 'position', id: 'store', position: { x: 80, y: 100 } }]));
    expect(callbacks.edit.mock.calls[0][0].nodes[1].properties.position).toEqual({ x: 80, y: 100 });
  });
  it('does not commit cancelled or stationary drags to history', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} />);
    const event = {} as Parameters<NonNullable<ReactFlowProps['onNodeDragStop']>>[0];
    act(() => flow().onNodeDragStop?.(event, flow().nodes![0], flow().nodes!));
    act(() => flow().onNodeDragStart?.(event, flow().nodes![0], flow().nodes!));
    act(() => flow().onNodeDragStop?.(event, flow().nodes![0], flow().nodes!));
    expect(callbacks.commit).not.toHaveBeenCalled(); expect(callbacks.edit).not.toHaveBeenCalled(); expect(callbacks.position).not.toHaveBeenCalled();
  });
  it('removes a canvas component together with its incident connections and removes edges independently', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} />);
    act(() => flow().onNodesChange?.([{ type: 'remove', id: 'gateway' }]));
    expect(callbacks.edit.mock.calls[0][0]).toEqual({ ...graph, nodes: [graph.nodes[1]], edges: [] });
    cleanup(); callbacks.edit.mockClear(); render(<GraphHarness callbacks={callbacks} />);
    act(() => flow().onEdgesChange?.([{ type: 'remove', id: 'wire' }]));
    expect(callbacks.edit).toHaveBeenCalledWith({ ...graph, edges: [] });
  });
  it('selects rows, edits a connection, toggles the inspector and removes it from the same graph', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Table' })); click('Edit Gateway');
    change('Notes', 'Updated note'); expect(callbacks.node).toHaveBeenCalledWith(0, { notes: 'Updated note' });
    click('Edit Gateway'); expect(screen.queryByLabelText('Label')).toBeNull();
    click('Edit connection'); change('Protocol', 'gRPC'); expect(callbacks.edge).toHaveBeenCalledWith(0, { protocol: 'gRPC' });
    click('Edit connection'); expect(screen.queryByLabelText('Protocol')).toBeNull();
    click('Edit connection'); click('Remove connection');
    expect(callbacks.edit.mock.calls[callbacks.edit.mock.calls.length - 1]?.[0].edges).toEqual([]);
    click('Edit Gateway'); click('Remove component'); expect(callbacks.remove).toHaveBeenCalledWith(0);
    expect(screen.queryByRole('button', { name: 'Edit Gateway' })).toBeNull();
  });
  it('connects valid handles and supports direct canvas inspection without history edits', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} />);
    const source = flow().nodes![0]; const edge = flow().edges![0];
    act(() => flow().onNodeClick?.({} as Parameters<NonNullable<ReactFlowProps['onNodeClick']>>[0], source));
    expect(screen.getByLabelText('Label')).toBeTruthy();
    act(() => flow().onPaneClick?.({} as Parameters<NonNullable<ReactFlowProps['onPaneClick']>>[0]));
    expect(screen.queryByLabelText('Label')).toBeNull();
    act(() => flow().onEdgeClick?.({} as Parameters<NonNullable<ReactFlowProps['onEdgeClick']>>[0], edge));
    expect(screen.getByLabelText('Protocol')).toBeTruthy();
    expect(callbacks.edit).not.toHaveBeenCalled();
    expect(flow().isValidConnection?.({ source: 'gateway', target: 'gateway', sourceHandle: null, targetHandle: null })).toBe(false);
    act(() => flow().onConnect?.({ source: 'gateway', target: 'store', sourceHandle: null, targetHandle: null }));
    expect(callbacks.addEdge).toHaveBeenCalledWith('gateway', 'store');
    expect((screen.getByLabelText('Source') as HTMLSelectElement).value).toBe('gateway');
    act(() => flow().onConnect?.({ source: '', target: 'store', sourceHandle: null, targetHandle: null }));
    act(() => flow().onConnect?.({ source: 'gateway', target: '', sourceHandle: null, targetHandle: null }));
    expect(callbacks.addEdge).toHaveBeenCalledOnce();
    click('Check current constraints'); expect(callbacks.check).toHaveBeenCalledOnce();
    open('Diagram validation'); expect(screen.getByText('Mechanism: unknown')).toBeTruthy();
  });
  it('disables mutations when locked but keeps keyboard inspection available', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} locked />);
    act(() => {
      flow().onNodesChange?.([{ type: 'remove', id: 'gateway' }]);
      flow().onEdgesChange?.([{ type: 'remove', id: 'wire' }]);
      flow().onConnect?.({ source: 'gateway', target: 'store', sourceHandle: null, targetHandle: null });
      flow().onNodesChange?.([{ type: 'select', id: 'gateway', selected: true }]);
    });
    expect(screen.getByLabelText('Label').matches(':disabled')).toBe(true);
    expect(callbacks.edit).not.toHaveBeenCalled(); expect(callbacks.addEdge).not.toHaveBeenCalled();
    click('Check current constraints'); expect(callbacks.check).not.toHaveBeenCalled();
  });
  it('shows empty-state guidance, adds from assumptions and edits its canonical typed field', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} initial={{ nodes: [], edges: [], assumptions: {} }} />);
    expect(screen.getByText('Your architecture starts here')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Table' })); expect(screen.getByText(/No components yet/)).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Assumptions' })); change('requests per second', '80');
    expect(callbacks.edit.mock.calls[callbacks.edit.mock.calls.length - 1]?.[0].assumptions).toEqual({ requests_per_second: 80 });
    click('Add component'); expect(screen.getByRole('tab', { name: 'Canvas' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByLabelText('Label')).toBeTruthy(); expect(callbacks.addNode).toHaveBeenCalledOnce();
  });
  it('returns to canvas when adding a connection from the focused assumptions panel', () => {
    const callbacks = graphCallbacks(); render(<GraphHarness callbacks={callbacks} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Assumptions' })); click('Add connection');
    expect(screen.getByRole('tab', { name: 'Canvas' }).getAttribute('aria-selected')).toBe('true');
    expect(callbacks.addEdge).toHaveBeenCalledWith('gateway', 'store');
  });
});

const evaluation = { status: 'satisfied_under_declared_assumptions', reason: 'Bounded retries declared.', mechanism_status: 'unknown', checks: [{ constraint_id: 'C0', status: 'satisfied', reason: 'Declared capacity is sufficient.' }], calculations: { read_rps: 1000 }, limitation: 'Runtime behavior is not certified.' };
const assessment = { turn_count: 2, assistance_events: 1, dimensions: [{ dimension: 'trade_offs', status: 'unassessed' }], artifact: { node_count: 2, edge_count: 1, diagram_revision: 3 }, missing_assumptions: ['bytes_per_request'], next_transfer: 'Try another region.', limitation: 'This is not a runtime test.' };
function sessionToolsProps(): ComponentProps<typeof StudioSessionTools> {
  return { graph, snapshot: { ...snapshot, turns: [{ ...turn, id: 'previous', superseded_by: 'turn' }, turn], events: [{ sequence: 1, type: 'coach.action', payload: { epoch: 4, text: 'Saved mentor prompt' } }, { sequence: 2, type: 'turn.recorded' }] }, scenario, busy: false, mutationDisabled: false,
    proposalText: JSON.stringify(graph), onProposalText: vi.fn(), proposal: { proposal_id: 'proposal', graph, validation: evaluation }, onPreview: vi.fn(), onDecide: vi.fn(),
    revisions: [{ revision: 2, parent_revision: 1, created_at: turn.created_at }, { revision: 3, parent_revision: 2, created_at: turn.created_at }], onRevisions: vi.fn(), onRestore: vi.fn(), summary: assessment, onSummary: vi.fn(), onExport: vi.fn(), lastTurnId: turn.id,
    externalFeedback: false, onExternalFeedback: vi.fn(), feedback: { status: 'abstained', source: 'deterministic_coordinator', question: 'Why bound retries?', uncertainty: 'No runtime evidence.' }, onFeedback: vi.fn(),
    reviewPrompt: 'Describe the failure policy.', onReviewPrompt: vi.fn(), reviews: [{ card_id: 'card', prompt: 'What is the retry bound?', due_at: turn.created_at }], onCreateReview: vi.fn(), onLoadReviews: vi.fn(), onRateReview: vi.fn(), onReload: vi.fn(), onLeave: vi.fn(), onDelete: vi.fn(), onEditTurn: vi.fn(), editDisabled: false };
}

describe('session evidence controls', () => {
  it('keeps proposal, revision, assessment, feedback and export callbacks reachable through disclosures', () => {
    const props = sessionToolsProps(); render(<StudioSessionTools {...props} />);
    open('Review a proposed graph'); change('Proposed graph', '{"nodes":[],"edges":[],"assumptions":{}}');
    expect(props.onProposalText).toHaveBeenCalled(); click('Preview proposal'); expect(props.onPreview).toHaveBeenCalledOnce();
    click('Accept proposal'); click('Discard proposal'); expect(props.onDecide).toHaveBeenNthCalledWith(1, 'accept'); expect(props.onDecide).toHaveBeenNthCalledWith(2, 'discard');
    open('Saved revisions and review'); click('Load revisions'); expect(props.onRevisions).toHaveBeenCalledOnce();
    const restores = screen.getAllByRole('button', { name: 'Restore as new revision' });
    expect(restores[1].matches(':disabled')).toBe(true); fireEvent.click(restores[0]); expect(props.onRestore).toHaveBeenCalledWith(2);
    click('Load assessment summary'); click('Export session'); expect(props.onSummary).toHaveBeenCalledOnce(); expect(props.onExport).toHaveBeenCalledOnce();
    open('Feedback on the last explanation'); fireEvent.click(screen.getByRole('checkbox')); expect(props.onExternalFeedback).toHaveBeenCalledWith(true);
    click('Request feedback'); expect(props.onFeedback).toHaveBeenCalledOnce(); expect(screen.getByText('Why bound retries?')).toBeTruthy();
  });
  it('creates reviews, rates recall, edits only the current turn and delegates session controls', () => {
    const props = sessionToolsProps(); render(<StudioSessionTools {...props} />);
    open('Review queue'); change('Review prompt linked to your last submitted turn', 'Recall the bound.'); expect(props.onReviewPrompt).toHaveBeenCalledWith('Recall the bound.');
    click('Create review card'); click('Load due cards'); expect(props.onCreateReview).toHaveBeenCalledOnce(); expect(props.onLoadReviews).toHaveBeenCalledOnce();
    ['Again', 'Hard', 'Good', 'Easy'].forEach((name, i) => { click(name); expect(props.onRateReview).toHaveBeenNthCalledWith(i + 1, 'card', i + 1); });
    open('Your decision timeline'); expect(screen.getAllByRole('button', { name: 'Edit latest explanation' })).toHaveLength(1);
    click('Edit latest explanation'); expect(props.onEditTurn).toHaveBeenCalledWith(turn);
    expect(screen.getByText('Superseded by a corrected explanation.')).toBeTruthy();
    open('Session controls'); click('Reload saved'); click('Leave session'); click('Delete session');
    expect(props.onReload).toHaveBeenCalledOnce(); expect(props.onLeave).toHaveBeenCalledOnce(); expect(props.onDelete).toHaveBeenCalledOnce();
  });
  it('honors busy and missing-evidence gates, and shows empty session activity', () => {
    const props = sessionToolsProps(); const view = render(<StudioSessionTools {...props} busy mutationDisabled editDisabled />);
    ['Preview proposal', 'Accept proposal', 'Discard proposal', 'Load revisions', 'Request feedback', 'Create review card', 'Again', 'Edit latest explanation', 'Delete session'].forEach(name => { expect(screen.getByRole('button', { name }).matches(':disabled')).toBe(true); click(name); });
    expect(props.onDecide).not.toHaveBeenCalled(); expect(props.onFeedback).not.toHaveBeenCalled();
    view.rerender(<StudioSessionTools {...props} lastTurnId="" proposalText=" " reviewPrompt=" " proposal={null} revisions={[]} summary={null} feedback={null} reviews={[]} scenario={null} snapshot={null} />);
    expect(screen.getByRole('button', { name: 'Preview proposal' }).matches(':disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Create review card' }).matches(':disabled')).toBe(true);
    expect(screen.getByText('No explanations submitted yet.')).toBeTruthy(); expect(screen.getByText('No activity yet.')).toBeTruthy();
  });
  it('renders authored case facts, prerequisites and encoded exercise links', () => {
    const props = sessionToolsProps(); const view = render(<StudioSessionTools {...props} />);
    open('The case and learning objectives'); expect(screen.getByText('Retries must be bounded.')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Open related coding problem/ }).getAttribute('href')).toBe('/practice/exercise%2Fqueue');
    open('Session activity'); expect(screen.getByText('Saved mentor prompt')).toBeTruthy();
    view.rerender(<StudioSessionTools {...props} scenario={{ ...scenario, id: 'REPO-01', clarification_facts: { retention: 'one day' } }} />);
    expect(screen.getByText('retention: one day')).toBeTruthy(); expect(screen.getByText(/Explore the repository and support/)).toBeTruthy();
  });
});

function setupProps(): ComponentProps<typeof StudioSetup> {
  return { scenarios: [{ id: 'SD-01', title: 'Reliable service', mode: 'guided_system_design', version: '1' }, { id: 'BRIDGE-01', title: 'Queue bridge', mode: 'dsa_to_system_bridge', version: '1' }, { id: 'REPO-01', title: 'Explore sources', mode: 'repo_exploration', version: '1' }, { id: 'DEFENSE-01', title: 'Defend a project', mode: 'project_defense', version: '1' }, { id: 'UNKNOWN-01', title: 'New practice mode', mode: 'future_mode', version: '1' }], scenario: 'SD-01', onScenario: vi.fn(), mock: true, onMock: vi.fn(), duration: 2700, onDuration: vi.fn(), posture: 'teaching', onPosture: vi.fn(), busy: false, sessions: [session, { ...session, id: 'session-two' }], workspace, onStart: vi.fn(), onResume: vi.fn(), onDeleteWorkspace: vi.fn() };
}
describe('scenario setup and resume', () => {
  it('selects readable scenarios and forwards interview settings with explicit minutes-to-seconds conversion', () => {
    const props = setupProps(); render(<StudioSetup {...props} />);
    fireEvent.click(screen.getByRole('radio', { name: /Queue bridge/ })); expect(props.onScenario).toHaveBeenCalledWith('BRIDGE-01');
    expect(screen.getByText('Design practice')).toBeTruthy(); open('Interview settings');
    change('Posture', 'assessment'); expect(props.onPosture).toHaveBeenCalledWith('assessment');
    fireEvent.click(screen.getByRole('checkbox')); expect(props.onMock).toHaveBeenCalledWith(false);
    change('Duration in minutes', '60'); expect(props.onDuration).toHaveBeenCalledWith(3600);
    click('Start session'); expect(props.onStart).toHaveBeenCalledOnce();
  });
  it('resumes the first session by default or the explicitly selected session and delegates workspace deletion', () => {
    const props = setupProps(); render(<StudioSetup {...props} />);
    open('Resume in this tab'); click('Open session'); expect(props.onResume).toHaveBeenCalledWith(session);
    change('Saved session', 'session-two'); click('Open session'); expect(props.onResume).toHaveBeenLastCalledWith(props.sessions[1]);
    open('Workspace data'); click('Delete workspace'); expect(props.onDeleteWorkspace).toHaveBeenCalledOnce();
  });
  it.each([0, 14460, 60.5])('blocks invalid timed duration %s seconds', duration => {
    const props = setupProps(); render(<StudioSetup {...props} duration={duration} />);
    click('Start session'); expect(props.onStart).not.toHaveBeenCalled();
  });
  it('handles loading, empty resume state, untimed modes and busy setup', () => {
    const props = setupProps(); const view = render(<StudioSetup {...props} scenarios={[]} scenario="" sessions={[]} workspace={undefined} mock={false} />);
    expect(screen.getByRole('status').textContent).toMatch(/loading or unavailable/); expect(screen.getByText('No studio sessions in this tab yet.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Start session' }).matches(':disabled')).toBe(true);
    view.rerender(<StudioSetup {...props} scenario="REPO-01" duration={0} />);
    expect(screen.queryByLabelText('Duration in minutes')).toBeNull(); expect(screen.getByRole('button', { name: 'Start session' }).matches(':disabled')).toBe(false);
    view.rerender(<StudioSetup {...props} busy />); click('Start session'); click('Open session');
    expect(props.onStart).not.toHaveBeenCalled(); expect(props.onResume).not.toHaveBeenCalled();
  });
});

describe('readable evidence views', () => {
  it('renders declared checks, calculations and limitations without claiming runtime certification', () => {
    const view = render(<EvaluationView value={evaluation} />);
    expect(screen.getByText(/satisfied under declared assumptions/)).toBeTruthy(); expect(screen.getByText('Bounded retries declared.')).toBeTruthy();
    expect(screen.getByText('Declared capacity is sufficient.')).toBeTruthy(); expect(screen.getByText(`read rps: ${(1000).toLocaleString()}`)).toBeTruthy();
    expect(screen.getByText('Runtime behavior is not certified.')).toBeTruthy();
    view.rerender(<EvaluationView value={{}} />); expect(screen.queryByText('Status:')).toBeNull();
  });
  it('shows assessment dimensions, missing assumptions, artifact revision and the next transfer', () => {
    const view = render(<SummaryView value={assessment} />);
    expect(screen.getByText('2 explanations · 1 assisted actions')).toBeTruthy(); expect(screen.getByText(/Diagram revision 3: 2 components, 1 connections/)).toBeTruthy();
    expect(screen.getByText('trade offs: unassessed')).toBeTruthy(); expect(screen.getByText('Missing assumptions: bytes per request')).toBeTruthy();
    expect(screen.getByText('Try another region.')).toBeTruthy(); expect(screen.getByText('This is not a runtime test.')).toBeTruthy();
    view.rerender(<SummaryView value={{ turn_count: 0, assistance_events: 0, dimensions: [] }} />); expect(screen.queryByText(/Missing assumptions/)).toBeNull();
  });
  it('shows explicit feedback abstention, source, question and uncertainty', () => {
    const view = render(<FeedbackView value={{ status: 'abstained', source: 'local_coordinator', question: 'Why this trade-off?', uncertainty: 'Evidence is insufficient.' }} />);
    expect(screen.getByText(/local coordinator/)).toBeTruthy(); expect(screen.getByText('Why this trade-off?')).toBeTruthy(); expect(screen.getByText('Evidence is insufficient.')).toBeTruthy();
    view.rerender(<FeedbackView value={{}} />); expect(screen.getByText('Not available')).toBeTruthy();
  });
  it('compares concrete components, connection policies and assumptions against an empty proposal', () => {
    render(<GraphComparison current={graph} proposed={{ nodes: [], edges: [], assumptions: {} }} />);
    const current = screen.getByRole('heading', { name: 'Current diagram' }).closest('section')!;
    expect(within(current).getByText('Gateway')).toBeTruthy(); expect(within(current).getByText('Retries are bounded.')).toBeTruthy();
    expect(within(current).getByText('retry policy: bounded')).toBeTruthy(); expect(within(current).getByText(/Gateway → Store: HTTPS/)).toBeTruthy();
    expect(within(current).getByText('unit: requests/s')).toBeTruthy(); expect(screen.getByText('None declared.')).toBeTruthy();
  });
  it('makes undeclared component and connection policies explicit in a proposal comparison', () => {
    const proposed: Graph = { ...graph, nodes: graph.nodes.map(node => ({ ...node, partition_key: '', consistency_mode: '', notes: '', properties: {} })), edges: graph.edges.map(edge => ({ ...edge, protocol: '', rate_estimate_rps: null, failure_behavior: '' })) };
    render(<GraphComparison current={graph} proposed={proposed} />);
    const proposal = screen.getByRole('heading', { name: 'Proposed diagram' }).closest('section')!;
    expect(proposal.textContent).toContain('consistency: unspecified');
    expect(within(proposal).getByText(/Gateway → Store: unspecified, directed, rate unknown requests\/s; failure behavior unspecified/)).toBeTruthy();
  });
  it.each(['[]', 'null', '123', '"text"', '{'])('rejects a non-object JSON draft %s', text => { expect(() => parseObject(text)).toThrow(); });
  it('accepts object JSON and formats null and numeric facts honestly', () => {
    expect(parseObject('{"durable":true}')).toEqual({ durable: true }); expect(readable(null)).toBe('Not available'); expect(readable(5)).toBe('5'); expect(readable('retry_policy')).toBe('retry policy');
  });
});

function mentorProps(): ComponentProps<typeof StudioMentor> {
  return { session, snapshot, scenario, reply: 'Consider failure behavior.', draft: 'My explanation', onDraft: vi.fn(), kind: 'explain', onKind: vi.fn(), locked: false, actionDisabled: false, dirty: false, assumptionsPending: false, busy: false, turnInFlight: false, onSend: vi.fn(), onCoach: vi.fn(), onInterrupt: vi.fn(), onTeaching: vi.fn(), correcting: false, onCancelCorrection: vi.fn() };
}
describe('state-specific mentor controls', () => {
  it('sends by button or Enter, retains multiline input and delegates help actions', () => {
    const props = mentorProps(); render(<StudioMentor {...props} />);
    change('Your explanation', 'Another explanation'); expect(props.onDraft).toHaveBeenCalledWith('Another explanation');
    click('Send explanation'); fireEvent.keyDown(screen.getByLabelText('Your explanation'), { key: 'Enter' }); expect(props.onSend).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(screen.getByLabelText('Your explanation'), { key: 'Enter', shiftKey: true }); expect(props.onSend).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(screen.getByLabelText('Your explanation'), { key: 'Enter', isComposing: true }); expect(props.onSend).toHaveBeenCalledTimes(2);
    open('Help'); ['Clarify', 'Hint', 'Options', 'Sketch', 'Explain', 'Teach back', 'Transfer', 'Rewind', 'Skip', 'Advance', 'Finish'].forEach(name => click(name));
    expect(props.onCoach).toHaveBeenCalledWith('teachback'); expect(props.onCoach).toHaveBeenCalledWith('clarify');
    change('Turn type', 'transfer'); expect(props.onKind).toHaveBeenCalledWith('transfer'); click('Interrupt current turn'); expect(props.onInterrupt).toHaveBeenCalledOnce();
    click('Next constraint →'); expect(props.onCoach).toHaveBeenCalledWith('advance');
  });
  it('offers assessment completion and explicit posture change, rather than unrestricted teaching', () => {
    const props = mentorProps(); render(<StudioMentor {...props} snapshot={{ ...snapshot, posture: 'assessment' }} scenario={{ ...scenario, constraint_index: 3 }} />);
    click('Finish assessment'); expect(props.onCoach).toHaveBeenCalledWith('finish'); open('Help'); click('Switch to teaching'); expect(props.onTeaching).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: 'Sketch' })).toBeNull();
  });
  it('offers reopening completed practice and supports explicit correction cancellation', () => {
    const props = mentorProps(); const view = render(<StudioMentor {...props} snapshot={{ ...snapshot, state: 'completed' }} />);
    expect(screen.queryByRole('button', { name: 'Send explanation' })).toBeNull(); click('Reopen practice'); expect(props.onCoach).toHaveBeenCalledWith('reopen'); open('Help'); click('Reopen'); expect(props.onCoach).toHaveBeenCalledTimes(2);
    view.rerender(<StudioMentor {...props} correcting />); click('Send correction'); click('Cancel correction'); expect(props.onSend).toHaveBeenCalledOnce(); expect(props.onCancelCorrection).toHaveBeenCalledOnce();
  });
  it('asks for teach-back and then a fresh case only after the matching recorded answer', () => {
    const props = mentorProps(); const view = render(<StudioMentor {...props} scenario={{ ...scenario, constraint_index: 3 }} />);
    click('Begin teach-back'); expect(props.onCoach).toHaveBeenCalledWith('teachback');
    const events: NonNullable<Snapshot['events']> = [{ sequence: 1, type: 'coach.action', payload: { action: 'teachback' } }];
    view.rerender(<StudioMentor {...props} scenario={{ ...scenario, constraint_index: 3 }} snapshot={{ ...snapshot, events }} />);
    expect(screen.getByText('Answer this question before moving on.')).toBeTruthy();
    view.rerender(<StudioMentor {...props} scenario={{ ...scenario, constraint_index: 3 }} snapshot={{ ...snapshot, events: [...events, { sequence: 2, type: 'turn.recorded', payload: { turn_id: turn.id } }] }} />);
    click('Try a fresh case →'); expect(props.onCoach).toHaveBeenCalledWith('transfer');
  });
  it('blocks empty or unsaved submissions while preserving an interrupt for an in-flight turn', () => {
    const props = mentorProps(); const view = render(<StudioMentor {...props} draft="" />);
    click('Send explanation'); expect(props.onSend).not.toHaveBeenCalled();
    view.rerender(<StudioMentor {...props} dirty actionDisabled busy turnInFlight />);
    expect(screen.getByText(/Save the diagram and apply any assumptions draft/)).toBeTruthy(); click('Send explanation'); expect(props.onSend).not.toHaveBeenCalled();
    click('Interrupt current turn'); expect(props.onInterrupt).toHaveBeenCalledOnce();
  });
});
