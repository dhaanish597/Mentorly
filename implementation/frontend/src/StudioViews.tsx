import type { Graph } from './studioApi';

export type RequiredField = { key: string; type: string; description?: string; values?: unknown[] };
export type ScenarioView = {
  id: string; version: string; title: string; problem_statement: string;
  prerequisites: string[]; learning_objectives: string[]; linked_exercise_ids: string[];
  constraint_index: number; transfer_active?: boolean; required_fields?: RequiredField[]; clarification_facts?: string[] | Record<string, unknown>;
  constraint: { id: string; title: string; description: string }; hint_level: number;
};
export type Snapshot = {
  session_id: string; epoch: number; diagram_revision: number; graph?: Graph; diagram?: Graph;
  events?: { sequence: number; type: string; payload?: { epoch?: number; text?: string; phase?: string; action?: string; turn_id?: string } }[];
  turns?: { id: string; epoch: number; diagram_revision: number; kind: string; content: string; created_at: string; transcript_revision?: number; superseded_by?: string | null }[];
  scenario_id?: string; posture?: string; mode?: string; state?: string; phase?: string; repo_snapshot_id?: string | null;
  deadline_at?: string | null; remaining_seconds?: number | null;
};

export function parseObject(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Enter a JSON object.');
  return value as Record<string, unknown>;
}

export function readable(value: unknown): string {
  return typeof value === 'string' ? value.replace(/_/g, ' ') : value == null ? 'Not available' : String(value);
}

export function EvaluationView({ value }: { value: unknown }) {
  const v = value as { status?: string; reason?: string; mechanism_status?: string; checks?: { constraint_id: string; status: string; reason: string }[]; calculations?: Record<string, number>; limitation?: string };
  return <div className="readable-result">
    {v.status && <p><strong>Status:</strong> {readable(v.status)}</p>}
    {v.reason && <p>{v.reason}</p>}
    {v.mechanism_status && <p>Mechanism: {readable(v.mechanism_status)}</p>}
    {v.checks && <ul>{v.checks.map((check, i) => <li key={i}><strong>{check.constraint_id}: {readable(check.status)}</strong><p>{check.reason}</p></li>)}</ul>}
    {v.calculations && Object.entries(v.calculations).map(([key, n]) => <p key={key}>{readable(key)}: {n.toLocaleString()}</p>)}
    {v.limitation && <p>{v.limitation}</p>}
  </div>;
}

export function SummaryView({ value }: { value: unknown }) {
  const v = value as { turn_count: number; assistance_events: number; dimensions: { dimension: string; status: string }[]; artifact?: { node_count: number; edge_count: number; diagram_revision: number }; missing_assumptions?: string[]; next_transfer?: string; limitation?: string };
  return <div className="readable-result">
    <p>{v.turn_count} explanations · {v.assistance_events} assisted actions</p>
    {v.artifact && <p>Diagram revision {v.artifact.diagram_revision}: {v.artifact.node_count} components, {v.artifact.edge_count} connections.</p>}
    <h3>Assessment dimensions</h3>
    <ul>{v.dimensions?.map(d => <li key={d.dimension}>{readable(d.dimension)}: {readable(d.status)}</li>)}</ul>
    {!!v.missing_assumptions?.length && <p>Missing assumptions: {v.missing_assumptions.map(readable).join(', ')}</p>}
    {v.next_transfer && <p><strong>Next transfer:</strong> {v.next_transfer}</p>}
    {v.limitation && <p>{v.limitation}</p>}
  </div>;
}

export function FeedbackView({ value }: { value: unknown }) {
  const v = value as { status?: string; question?: string; uncertainty?: string; source?: string };
  return <div className="readable-result">
    <p><strong>{readable(v.status)}</strong>{v.source && ` · ${readable(v.source)}`}</p>
    {v.question && <p>{v.question}</p>}{v.uncertainty && <p>{v.uncertainty}</p>}
  </div>;
}

function GraphDescription({ graph }: { graph: Graph }) {
  return <>
    <h4>Components</h4>
    <ul>{graph.nodes.map(n => <li key={n.node_id}>
      <strong>{n.label}</strong> ({n.kind}), {n.replica_count} replicas; {n.statefulness}; consistency: {n.consistency_mode || 'unspecified'}
      {n.partition_key && `; partition: ${n.partition_key}`}{n.notes && <p>{n.notes}</p>}
      {Object.entries(n.properties).filter(([key]) => key !== 'position').map(([key, value]) => <p key={key}>{readable(key)}: {readable(value)}</p>)}
    </li>)}</ul>
    <h4>Connections</h4>
    <ul>{graph.edges.map(e => <li key={e.edge_id}>
      {graph.nodes.find(n => n.node_id === e.source_node_id)?.label ?? e.source_node_id} → {graph.nodes.find(n => n.node_id === e.target_node_id)?.label ?? e.target_node_id}: {e.protocol || 'unspecified'}, {e.directionality}, rate {e.rate_estimate_rps ?? 'unknown'} requests/s; {e.failure_behavior || 'failure behavior unspecified'}
    </li>)}</ul>
    <h4>Assumptions</h4>
    {Object.entries(graph.assumptions).length ? <ul>{Object.entries(graph.assumptions).map(([key, value]) => <li key={key}>{readable(key)}: {readable(value)}</li>)}</ul> : <p>None declared.</p>}
  </>;
}

export function GraphComparison({ current, proposed }: { current: Graph; proposed: Graph }) {
  return <div className="graph-comparison">
    <section><h3>Current diagram</h3><GraphDescription graph={current} /></section>
    <section><h3>Proposed diagram</h3><GraphDescription graph={proposed} /></section>
  </div>;
}
