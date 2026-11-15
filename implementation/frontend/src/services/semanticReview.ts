import type { components } from '../types/openapi';

export type SemanticReview = components['schemas']['SemanticReview'];
export type ExplanationReview = components['schemas']['ExplanationReview'];
const REVIEW_STATUSES = ['SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED_BY_EVIDENCE', 'INSUFFICIENT_EVIDENCE', 'NOT_EVALUATED', 'MODEL_UNAVAILABLE'];
const MODEL_STATUSES = ['MODEL_DISABLED', 'MODEL_NOT_CONFIGURED', 'MODEL_TIMEOUT', 'MODEL_RATE_LIMITED', 'MODEL_INVALID_RESPONSE', 'MODEL_UNAVAILABLE', 'MODEL_ASSISTED', 'MODEL_BUDGET_EXHAUSTED'];
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Explanation review returned invalid data.');
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Explanation review returned invalid data.');
  return value;
}
function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('Explanation review returned invalid data.');
  return value;
}
function member(value: unknown, options: string[]): void {
  if (!options.includes(text(value))) throw new Error('Explanation review returned an unknown status.');
}
export function parseSemanticReview(value: unknown): SemanticReview {
  const review = object(value);
  member(review.status, REVIEW_STATUSES);
  if (review.schema_version !== '1.0' || review.rubric_version !== 'semantic-quality-v1' || review.correctness_assessed !== false || !Number.isSafeInteger(review.reviewed_answer_revision) || Number(review.reviewed_answer_revision) < 1) throw new Error('Explanation review returned invalid provenance.');
  for (const key of ['answer_sha256', 'context_sha256']) if (!/^[0-9a-f]{64}$/.test(text(review[key]))) throw new Error('Explanation review returned invalid revision evidence.');
  for (const key of ['uncertainty', 'explanation', 'followup']) text(review[key]);
  function refs(value: unknown): void {
    list(value).forEach(value => {
      const ref = object(value); member(ref.source, ['question', 'answer', 'lesson_rationale']); text(ref.excerpt);
      if (!Number.isSafeInteger(ref.start) || !Number.isSafeInteger(ref.end) || Number(ref.start) < 0 || Number(ref.end) <= Number(ref.start)) throw new Error('Explanation review returned invalid evidence.');
    });
  }
  refs(review.evidence_refs);
  list(review.criteria).forEach(value => { const criterion = object(value); member(criterion.id, ['relevance', 'reasoning_coherence', 'assumptions', 'example_alignment']); member(criterion.status, REVIEW_STATUSES.slice(0, 4)); text(criterion.explanation); refs(criterion.evidence_refs); });
  const provenance = object(review.model_provenance); member(provenance.status, MODEL_STATUSES);
  for (const key of ['provider', 'model', 'request_id']) if (provenance[key] != null) text(provenance[key]);
  return review as unknown as SemanticReview;
}
export function parseExplanationReview(value: unknown): ExplanationReview {
  const result = object(value); member(result.status, ['SUPPORTED', 'NEEDS_CLARIFICATION', 'INCORRECT_WITH_EVIDENCE', 'UNASSESSED']);
  if (result.changes_objective_credit !== false) throw new Error('Explanation feedback must not change objective credit.');
  parseSemanticReview(result.review);
  return result as unknown as ExplanationReview;
}
