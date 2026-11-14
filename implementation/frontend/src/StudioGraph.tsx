import { useRef, useState } from 'react';
import { Background, Controls, ReactFlow, applyNodeChanges } from '@xyflow/react';
import type { Connection, Edge, EdgeChange, Node, NodeChange } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { Graph, StudioEdge, StudioNode } from './studioApi';
import { StudioTabs } from './StudioTabs';
import { StudioAssumptions } from './StudioAssumptions';
import { StudioNodeProperties, StudioEdgeProperties, nodePosition } from './StudioProperties';
import { EvaluationView } from './StudioViews';
import type { RequiredField } from './StudioViews';

type Selection = { kind: 'node' | 'edge'; id: string } | null;
type Props = {
  graph: Graph; locked: boolean; assumptionsText: string; assumptionsPending: boolean; requiredFields: RequiredField[];
  onAssumptionsText: (text: string) => void; onError: (error: string) => void;
  onEdit: (graph: Graph) => void; onPosition: (graph: Graph) => void; onDragCommit: (graph: Graph) => void;
  onAddNode: () => string; onAddEdge: (source?: string, target?: string) => string | undefined;
  onUpdateNode: (index: number, patch: Partial<StudioNode>) => void; onRemoveNode: (index: number) => void;
  onUpdateEdge: (index: number, patch: Partial<StudioEdge>) => void;
  checkDisabled: boolean; onCheck: () => void; evaluation: unknown; validation: unknown;
};
const tabs = [{ id: 'canvas', label: 'Canvas' }, { id: 'table', label: 'Table' }, { id: 'assumptions', label: 'Assumptions' }] as const;

export function StudioGraph({ graph, locked, assumptionsText, assumptionsPending, requiredFields, onAssumptionsText, onError, onEdit, onPosition, onDragCommit, onAddNode, onAddEdge, onUpdateNode, onRemoveNode, onUpdateEdge, checkDisabled, onCheck, evaluation, validation }: Props) {
  const [view, setView] = useState<'canvas' | 'table' | 'assumptions'>('canvas');
  const [selection, setSelection] = useState<Selection>(null);
  const dragStart = useRef<Graph | null>(null);
  const flowNodes: Node[] = graph.nodes.map((n, i) => ({ id: n.node_id, position: nodePosition(n, i), data: { label: n.label || n.kind }, selected: selection?.kind === 'node' && selection.id === n.node_id }));
  const flowEdges: Edge[] = graph.edges.map(e => ({ id: e.edge_id, source: e.source_node_id, target: e.target_node_id, label: e.protocol, selected: selection?.kind === 'edge' && selection.id === e.edge_id }));
  const nodeIndex = selection?.kind === 'node' ? graph.nodes.findIndex(n => n.node_id === selection.id) : -1;
  const edgeIndex = selection?.kind === 'edge' ? graph.edges.findIndex(e => e.edge_id === selection.id) : -1;
  function onNodesChange(changes: NodeChange<Node>[]) {
    const selectedNode = changes.find(change => change.type === 'select' && change.selected);
    if (selectedNode?.type === 'select') setSelection({ kind: 'node', id: selectedNode.id });
    else if (changes.some(change => change.type === 'select' && !change.selected)) {
      setSelection(current => current?.kind === 'node' && changes.some(change => change.type === 'select' && change.id === current.id && !change.selected) ? null : current);
    }
    if (locked) return;
    const removed = changes.filter(c => c.type === 'remove').map(c => c.id);
    if (removed.length) {
      onEdit({ ...graph, nodes: graph.nodes.filter(n => !removed.includes(n.node_id)), edges: graph.edges.filter(e => !removed.includes(e.source_node_id) && !removed.includes(e.target_node_id)) });
      return;
    }
    if (!changes.some(c => c.type === 'position')) return;
    const positions = applyNodeChanges(changes, flowNodes);
    const updated = { ...graph, nodes: graph.nodes.map(n => { const item = positions.find(x => x.id === n.node_id); return item ? { ...n, properties: { ...n.properties, position: item.position } } : n; }) };
    if (dragStart.current) onPosition(updated); else onEdit(updated);
  }
  function onEdgesChange(changes: EdgeChange<Edge>[]) {
    const selectedEdge = changes.find(change => change.type === 'select' && change.selected);
    if (selectedEdge?.type === 'select') setSelection({ kind: 'edge', id: selectedEdge.id });
    else if (changes.some(change => change.type === 'select' && !change.selected)) {
      setSelection(current => current?.kind === 'edge' && changes.some(change => change.type === 'select' && change.id === current.id && !change.selected) ? null : current);
    }
    if (locked) return;
    const removed = changes.filter(c => c.type === 'remove').map(c => c.id);
    if (removed.length) onEdit({ ...graph, edges: graph.edges.filter(e => !removed.includes(e.edge_id)) });
  }
  function connect(connection: Connection) {
    if (locked || !connection.source || !connection.target) return;
    const id = onAddEdge(connection.source, connection.target);
    if (id) setSelection({ kind: 'edge', id });
  }
  const table = <div className="studio-graph-table">
    <p>Expand one row to edit. Canvas, table, assumptions and undo share one diagram.</p>
    <div className="studio-table-scroll"><table><caption>Architecture components</caption>
      <thead><tr><th scope="col">Component</th><th scope="col">Kind</th><th scope="col">Replicas</th><th scope="col">Properties</th></tr></thead>
      <tbody>{graph.nodes.map(n => <tr key={n.node_id}>
        <th scope="row">{n.label || 'Untitled component'}</th><td>{n.kind}</td><td>{n.replica_count}</td>
        <td><button aria-expanded={selection?.id === n.node_id} aria-controls="studio-graph-inspector" onClick={() => setSelection(selection?.id === n.node_id ? null : { kind: 'node', id: n.node_id })}>Edit {n.label || 'component'}</button></td>
      </tr>)}</tbody>
    </table></div>
    {!graph.nodes.length && <p>No components yet. Add one to start designing.</p>}
    <div className="studio-table-scroll"><table><caption>Architecture connections</caption>
      <thead><tr><th scope="col">Connection</th><th scope="col">Protocol</th><th scope="col">Properties</th></tr></thead>
      <tbody>{graph.edges.map(e => <tr key={e.edge_id}>
        <th scope="row">{graph.nodes.find(n => n.node_id === e.source_node_id)?.label} → {graph.nodes.find(n => n.node_id === e.target_node_id)?.label}</th><td>{e.protocol || 'Not declared'}</td>
        <td><button aria-expanded={selection?.id === e.edge_id} aria-controls="studio-graph-inspector" onClick={() => setSelection(selection?.id === e.edge_id ? null : { kind: 'edge', id: e.edge_id })}>Edit connection</button></td>
      </tr>)}</tbody>
    </table></div>
  </div>;
  return <section className="studio-architecture studio-card" aria-label="Architecture workspace">
    <div className="studio-workspace-title"><h2>Architecture</h2><span className="studio-muted">{graph.nodes.length} components · {graph.edges.length} connections</span></div>
    <fieldset disabled={locked}>
      <div className="studio-graph-toolbar">
        <button aria-label="Add component" onClick={() => { const id = onAddNode(); setSelection({ kind: 'node', id }); if (view === 'assumptions') setView('canvas'); }}>+ Add component</button>
        <button disabled={graph.nodes.length < 2} onClick={() => { const id = onAddEdge(); if (id) setSelection({ kind: 'edge', id }); if (view === 'assumptions') setView('canvas'); }}>Add connection</button>
        <span className="studio-muted">Select to edit · drag to arrange</span>
      </div>
    </fieldset>
    <StudioTabs label="Architecture view" tabs={tabs} value={view} onChange={setView}>
      {view === 'assumptions' ? <fieldset disabled={locked}><StudioAssumptions graph={graph} fields={requiredFields} text={assumptionsText} onText={onAssumptionsText} pending={assumptionsPending} onEdit={onEdit} onError={onError} /></fieldset> : <>
        {view === 'table' ? table : <>
          <div className="studio-flow" aria-label="Architecture diagram">
            <ReactFlow nodes={flowNodes} edges={flowEdges} nodesDraggable={!locked} nodesFocusable nodesConnectable={!locked} elementsSelectable
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={connect}
              isValidConnection={connection => connection.source !== connection.target}
              onNodeClick={(_, node) => setSelection({ kind: 'node', id: node.id })}
              onEdgeClick={(_, edge) => setSelection({ kind: 'edge', id: edge.id })} onPaneClick={() => setSelection(null)}
              onNodeDragStart={() => { dragStart.current = graph; }}
              onNodeDragStop={() => { const initial = dragStart.current; dragStart.current = null; if (initial && JSON.stringify(initial.nodes) !== JSON.stringify(graph.nodes)) onDragCommit(initial); }} fitView>
              <Background /><Controls showInteractive={false} />
            </ReactFlow>
            {!graph.nodes.length && <div className="studio-canvas-empty"><strong>Your architecture starts here</strong><span>Add your first component, then connect the pieces.</span></div>}
          </div>
          <p className="studio-canvas-hint">Drag from a component’s handle to connect it. Use Table for keyboard editing.</p>
        </>}
        <div id="studio-graph-inspector">
          {nodeIndex >= 0 && <fieldset disabled={locked}><StudioNodeProperties key={graph.nodes[nodeIndex].node_id} node={graph.nodes[nodeIndex]} index={nodeIndex} requiredFields={requiredFields} onChange={patch => onUpdateNode(nodeIndex, patch)} onRemove={() => { onRemoveNode(nodeIndex); setSelection(null); }} /></fieldset>}
          {edgeIndex >= 0 && <fieldset disabled={locked}><StudioEdgeProperties key={graph.edges[edgeIndex].edge_id} edge={graph.edges[edgeIndex]} index={edgeIndex} graph={graph} onChange={patch => onUpdateEdge(edgeIndex, patch)} onRemove={() => { onEdit({ ...graph, edges: graph.edges.filter((_, i) => i !== edgeIndex) }); setSelection(null); }} /></fieldset>}
        </div>
      </>}
    </StudioTabs>
    <div className="studio-constraint-check"><button disabled={checkDisabled} onClick={onCheck}>Check current constraints</button><span>Checks declared assumptions, not runtime behavior.</span></div>
    {evaluation !== null && <section><h3>Constraint check</h3><EvaluationView value={evaluation} /></section>}
    {validation !== null && <details><summary>Diagram validation</summary><EvaluationView value={validation} /></details>}
  </section>;
}
