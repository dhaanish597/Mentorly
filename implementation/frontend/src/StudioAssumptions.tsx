import type { Graph } from './studioApi';
import { calculateCapacity } from './studioCapacity';
import { parseObject, readable } from './StudioViews';
import type { RequiredField } from './StudioViews';

type Props = {
  graph: Graph; fields: RequiredField[]; text: string; onText: (text: string) => void;
  pending: boolean; onEdit: (graph: Graph) => void; onError: (error: string) => void;
};

export function StudioAssumptions({ graph, fields, text, onText, pending, onEdit, onError }: Props) {
  let assumptions: Record<string, unknown> | null = null;
  try { assumptions = parseObject(text); } catch { /* The invalid draft stays editable and is reported below. */ }
  const inputs = fields.filter(field => field.type !== 'property' && field.type !== 'policy');
  function update(key: string, value: unknown) {
    if (!assumptions) { onError('Fix the assumptions JSON before editing typed fields.'); return; }
    const next = value === undefined ? Object.fromEntries(Object.entries(assumptions).filter(([name]) => name !== key)) : { ...assumptions, [key]: value };
    onEdit({ ...graph, assumptions: next });
    onText(JSON.stringify(next, null, 2));
  }
  return <div className="studio-assumptions">
    <h3>Declare your assumptions</h3>
    <p>Keep units explicit. These values belong to the same diagram as the canvas and table.</p>
    <div className="studio-property-grid">
      {inputs.map(field => <label key={field.key}>
        {readable(field.key)}{field.description ? ` — ${field.description}` : ''}
        {field.type === 'boolean' ? <select value={typeof assumptions?.[field.key] === 'boolean' ? String(assumptions[field.key]) : ''} onChange={e => update(field.key, e.target.value === '' ? undefined : e.target.value === 'true')}>
          <option value="">Not declared</option><option value="true">Yes</option><option value="false">No</option>
        </select> : field.values?.length ? <select value={String(assumptions?.[field.key] ?? '')} onChange={e => update(field.key, e.target.value || undefined)}>
          <option value="">Not declared</option>{field.values.map(value => <option key={String(value)} value={String(value)}>{readable(value)}</option>)}
        </select> : <input type={field.type === 'number' ? 'number' : 'text'} min={field.type === 'number' ? '0' : undefined}
          value={typeof assumptions?.[field.key] === 'number' || typeof assumptions?.[field.key] === 'string' ? String(assumptions[field.key]) : ''}
          onChange={e => update(field.key, e.target.value === '' ? undefined : field.type === 'number' ? Number(e.target.value) : e.target.value)} />}
      </label>)}
    </div>
    {!inputs.length && <p className="studio-muted">No typed assumptions are requested at this stage. Add any extra assumptions in the advanced editor.</p>}
    <details><summary>Advanced assumptions JSON</summary>
      <label>Assumptions (JSON object)<textarea rows={5} value={text} onChange={e => onText(e.target.value)} /></label>
      {!assumptions && <p role="alert">Enter a valid assumptions JSON object.</p>}
      <div className="studio-actions">
        <button disabled={!pending} onClick={() => {
          try { const next = parseObject(text); onEdit({ ...graph, assumptions: next }); onText(JSON.stringify(next, null, 2)); }
          catch { onError('Enter a valid assumptions JSON object.'); }
        }}>Apply assumptions</button>
        <button disabled={!pending} onClick={() => onText(JSON.stringify(graph.assumptions, null, 2))}>Discard assumptions draft</button>
      </div>
    </details>
    <Capacity assumptions={assumptions} />
  </div>;
}

function Capacity({ assumptions }: { assumptions: Record<string, unknown> | null }) {
  const values = assumptions ? calculateCapacity(assumptions) : null;
  return <details><summary>Capacity estimates</summary>
    <p>Estimates use numeric assumptions. Missing inputs remain unknown; check units and assumptions.</p>
    <p>Keys: event_rate_per_second, recipients_per_event, read_rps, miss_fraction, events_per_second, retry_window_seconds, bytes_per_event, replicas, requests_per_second, bytes_per_request, latency_seconds.</p>
    {values ? <dl>{Object.entries(values).map(([label, value]) => <div key={label}><dt>{readable(label)}</dt><dd>{value === null ? 'Unknown' : value.toLocaleString()}</dd></div>)}</dl> : <p>Enter a valid assumptions object to calculate.</p>}
  </details>;
}
