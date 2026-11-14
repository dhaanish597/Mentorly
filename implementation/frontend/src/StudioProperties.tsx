import { useEffect, useState } from 'react';
import type { Graph, StudioEdge, StudioNode } from './studioApi';
import { parseObject, readable } from './StudioViews';
import type { RequiredField } from './StudioViews';

export function nodePosition(n: StudioNode, i: number): { x: number; y: number } {
  const p = n.properties?.position as { x?: unknown; y?: unknown } | undefined;
  return { x: typeof p?.x === 'number' ? p.x : 50 + (i % 3) * 200, y: typeof p?.y === 'number' ? p.y : 50 + Math.floor(i / 3) * 130 };
}

function JsonProperties({ value, onChange }: { value: Record<string, unknown>; onChange: (value: Record<string, unknown>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState('');
  useEffect(() => { setText(JSON.stringify(value, null, 2)); }, [value]);
  return <details><summary>Advanced component properties</summary>
    <label>Properties (JSON object)<textarea rows={4} value={text} onChange={e => setText(e.target.value)} /></label>
    <button onClick={() => { try { onChange(parseObject(text)); setError(''); } catch { setError('Enter a valid JSON object.'); } }}>Apply properties</button>
    {error && <p role="alert">{error}</p>}
  </details>;
}

type NodeProps = { node: StudioNode; index: number; requiredFields: RequiredField[]; onChange: (patch: Partial<StudioNode>) => void; onRemove: () => void };
export function StudioNodeProperties({ node: n, index: i, requiredFields, onChange, onRemove }: NodeProps) {
  return <fieldset className="studio-properties"><legend>Component {i + 1} · {n.label}</legend>
    <div className="studio-property-grid">
      <label>Label<input value={n.label} onChange={e => onChange({ label: e.target.value })} /></label>
      <label>Kind<input value={n.kind} onChange={e => onChange({ kind: e.target.value })} /></label>
      <label>Replicas<input type="number" min="1" value={n.replica_count} onChange={e => onChange({ replica_count: Number(e.target.value) })} /></label>
      <label>Statefulness<input value={n.statefulness} onChange={e => onChange({ statefulness: e.target.value })} /></label>
      <label>Partition key<input value={n.partition_key} onChange={e => onChange({ partition_key: e.target.value })} /></label>
      <label>Consistency<input value={n.consistency_mode} onChange={e => onChange({ consistency_mode: e.target.value })} /></label>
      <label>Horizontal position<input type="number" value={nodePosition(n, i).x} onChange={e => onChange({ properties: { ...n.properties, position: { ...nodePosition(n, i), x: Number(e.target.value) } } })} /></label>
      <label>Vertical position<input type="number" value={nodePosition(n, i).y} onChange={e => onChange({ properties: { ...n.properties, position: { ...nodePosition(n, i), y: Number(e.target.value) } } })} /></label>
      {requiredFields.filter(field => field.type === 'property' || field.type === 'policy').map(field => <label key={field.key}>
        {readable(field.key)}{field.description ? ` — ${field.description}` : ''}
        <input list={`policy-${n.node_id}-${field.key}`} value={typeof n.properties[field.key] === 'string' ? n.properties[field.key] as string : ''} onChange={e => {
          const properties = e.target.value ? { ...n.properties, [field.key]: e.target.value } : Object.fromEntries(Object.entries(n.properties).filter(([key]) => key !== field.key));
          onChange({ properties });
        }} />
        {field.values && <datalist id={`policy-${n.node_id}-${field.key}`}>{field.values.filter(value => typeof value === 'string').map(value => <option key={String(value)} value={String(value)} />)}</datalist>}
      </label>)}
    </div>
    <label>Notes<textarea value={n.notes} onChange={e => onChange({ notes: e.target.value })} /></label>
    <JsonProperties value={n.properties} onChange={properties => onChange({ properties })} />
    <button className="danger" onClick={onRemove}>Remove component</button>
  </fieldset>;
}

type EdgeProps = { edge: StudioEdge; index: number; graph: Graph; onChange: (patch: Partial<StudioEdge>) => void; onRemove: () => void };
export function StudioEdgeProperties({ edge, index, graph, onChange, onRemove }: EdgeProps) {
  return <fieldset className="studio-properties"><legend>Connection {index + 1}</legend>
    <div className="studio-property-grid">
      <label>Source<select value={edge.source_node_id} onChange={e => onChange({ source_node_id: e.target.value })}>{graph.nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}</select></label>
      <label>Target<select value={edge.target_node_id} onChange={e => onChange({ target_node_id: e.target.value })}>{graph.nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}</select></label>
      <label>Protocol<input value={edge.protocol} onChange={e => onChange({ protocol: e.target.value })} /></label>
      <label>Directionality<input value={edge.directionality} onChange={e => onChange({ directionality: e.target.value })} /></label>
      <label>Estimated requests per second<input type="number" min="0" value={edge.rate_estimate_rps ?? ''} onChange={e => onChange({ rate_estimate_rps: e.target.value === '' ? null : Number(e.target.value) })} /></label>
    </div>
    <label>Failure behavior<textarea value={edge.failure_behavior} onChange={e => onChange({ failure_behavior: e.target.value })} /></label>
    <button className="danger" onClick={onRemove}>Remove connection</button>
  </fieldset>;
}
