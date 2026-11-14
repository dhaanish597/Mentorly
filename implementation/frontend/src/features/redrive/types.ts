export type SourceCitation = { path: string; symbol: string; start_line: number; end_line: number; chunk_hash: string };
export type LearningFact = { kind: 'source_path' | 'identifier'; expected: string };
export type LearningStep = {
  step_id: string; phase: 'fundamentals' | 'entrypoint' | 'components' | 'flows' | 'testing_tradeoffs';
  concept: string; title: string; explanation: string; question: string; prerequisites: string[];
  citations: SourceCitation[]; facts: LearningFact[]; mastery: 'not_established';
};
export type EvidenceEvent = {
  sequence: number; step_id: string; assessment: 'supported_observation' | 'unsupported_claim' | 'contradicted_by_source' | 'needs_support';
  feedback: string; question: string; citations: SourceCitation[]; mastery: 'not_established';
};
export type LearningPlan = {
  plan_id: string; snapshot_id: string; snapshot_hash: string; epoch: number; status: 'learning' | 'review' | 'complete';
  current_step: LearningStep | null; steps: LearningStep[]; checkpoint: { cursor: number; completed_step_ids: string[] };
  revisit_step_ids: string[]; attempts: { sequence: number; step_id: string; answer: string; created_at: string }[];
  evidence_events: EvidenceEvent[]; limitations: string[];
};
const HASH = /^[a-f0-9]{64}$/;
const PHASES = ['fundamentals', 'entrypoint', 'components', 'flows', 'testing_tradeoffs'];
const ASSESSMENTS = ['supported_observation', 'unsupported_claim', 'contradicted_by_source', 'needs_support'];
function object(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function text(value: unknown, max = 4000): value is string { return typeof value === 'string' && value.length > 0 && value.length <= max; }
function strings(value: unknown, max = 500): value is string[] { return Array.isArray(value) && value.length <= max && value.every(item => text(item)); }
function integer(value: unknown, minimum = 1): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum; }
export function isSourceCitation(value: unknown): value is SourceCitation {
  if (!object(value) || !text(value.path, 512) || value.path.startsWith('/') || /[\\\x00-\x1f]/.test(value.path)
    || value.path.split('/').some(part => part === '..' || part === '.') || /^[A-Za-z]:/.test(value.path)) return false;
  return typeof value.symbol === 'string' && value.symbol.length <= 256 && integer(value.start_line)
    && integer(value.end_line) && value.end_line >= value.start_line && typeof value.chunk_hash === 'string' && HASH.test(value.chunk_hash);
}
function citations(value: unknown): value is SourceCitation[] { return Array.isArray(value) && value.length > 0 && value.length <= 10 && value.every(isSourceCitation); }
function isStep(value: unknown): value is LearningStep {
  return object(value) && text(value.step_id, 128) && typeof value.phase === 'string' && PHASES.includes(value.phase)
    && text(value.concept, 128) && text(value.title, 256) && text(value.explanation) && text(value.question, 1000)
    && strings(value.prerequisites, 32) && citations(value.citations) && value.mastery === 'not_established'
    && Array.isArray(value.facts) && value.facts.length > 0 && value.facts.length <= 10
    && value.facts.every(fact => object(fact) && ['source_path', 'identifier'].includes(String(fact.kind)) && text(fact.expected, 512));
}
function sameCitation(left: SourceCitation, right: SourceCitation): boolean {
  return left.path === right.path && left.symbol === right.symbol && left.start_line === right.start_line
    && left.end_line === right.end_line && left.chunk_hash === right.chunk_hash;
}
export function parseLearningPlan(value: unknown, snapshotId: string): LearningPlan {
  const error = new Error('Invalid learning checkpoint or source reference. Reload the current snapshot checkpoint.');
  if (!object(value) || !text(value.plan_id, 128) || value.snapshot_id !== snapshotId || typeof value.snapshot_hash !== 'string'
    || !HASH.test(value.snapshot_hash) || !integer(value.epoch) || !['learning', 'review', 'complete'].includes(String(value.status))
    || !Array.isArray(value.steps) || !value.steps.length || value.steps.length > 32 || !value.steps.every(isStep)
    || !object(value.checkpoint) || !integer(value.checkpoint.cursor, 0) || value.checkpoint.cursor > value.steps.length
    || !strings(value.checkpoint.completed_step_ids, 32) || !strings(value.revisit_step_ids, 32) || !strings(value.limitations, 32)) throw error;
  const steps = value.steps;
  const ids = steps.map(step => step.step_id);
  if (new Set(ids).size !== ids.length || steps.some((step, index) => step.prerequisites.some(id => !ids.slice(0, index).includes(id)))
    || value.revisit_step_ids.some(id => !ids.includes(id))
    || JSON.stringify(value.checkpoint.completed_step_ids) !== JSON.stringify(ids.slice(0, value.checkpoint.cursor))) throw error;
  if (value.status === 'complete') {
    if (value.current_step !== null || value.checkpoint.cursor !== steps.length || value.revisit_step_ids.length) throw error;
  } else {
    if (!isStep(value.current_step)) throw error;
    const original = steps.find(step => step.step_id === (value.current_step as LearningStep).step_id);
    const expected = value.status === 'learning' ? steps[value.checkpoint.cursor]?.step_id : value.revisit_step_ids[0];
    if (!original || value.current_step.step_id !== expected || original.citations.length !== value.current_step.citations.length
      || !original.citations.every((item, index) => sameCitation(item, (value.current_step as LearningStep).citations[index]))) throw error;
  }
  if (!Array.isArray(value.attempts) || value.attempts.length > 500 || !value.attempts.every(item => object(item)
    && integer(item.sequence) && text(item.step_id, 128) && ids.includes(item.step_id) && text(item.answer) && text(item.created_at, 100))
    || !Array.isArray(value.evidence_events) || value.evidence_events.length > 500 || !value.evidence_events.every(item => object(item)
      && integer(item.sequence) && text(item.step_id, 128) && ids.includes(item.step_id) && ASSESSMENTS.includes(String(item.assessment))
      && text(item.feedback) && typeof item.question === 'string' && item.question.length <= 1000 && citations(item.citations)
      && item.mastery === 'not_established')) throw error;
  return value as unknown as LearningPlan;
}
