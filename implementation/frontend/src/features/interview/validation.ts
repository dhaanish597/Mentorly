/** Runtime boundary validation without introducing a new package dependency. */
import type { InterviewCatalog, InterviewConfig, InterviewMessage, InterviewReport, InterviewSession } from './types';
import { CODE_MIXING_LANGUAGES, SPEECH_LANGUAGES, resolveLanguageMode } from '../../voice/languages';
const TYPES = ['dsa', 'cs', 'system_design', 'codebase_defense'];
const LANGUAGE_MODES = [...SPEECH_LANGUAGES.map(item => item.code), ...CODE_MIXING_LANGUAGES.map(code => resolveLanguageMode(code, true))];
function invalid(): never { throw new Error('The interview server returned an invalid response.'); }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) invalid(); return value as Record<string, unknown>; }
function text(value: unknown): string { if (typeof value !== 'string') invalid(); return value; }
function integer(value: unknown): number { if (!Number.isSafeInteger(value)) invalid(); return value as number; }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) invalid(); return value; }
function strings(value: unknown): string[] { return array(value).map(text); }
function member(value: unknown, options: string[]): string { const v = text(value); if (!options.includes(v)) invalid(); return v; }
function message(value: unknown): InterviewMessage {
  const v = object(value); text(v.text);
  array(v.source_refs).forEach(ref => { const r = object(ref); text(r.source); for (const key of ['exercise_id', 'spec_version', 'policy_id']) if (r[key] != null) text(r[key]); });
  return v as unknown as InterviewMessage;
}
export function parseConfig(value: unknown): InterviewConfig {
  const v = object(value); strings(v.types).forEach(t => member(t, TYPES)); strings(v.difficulties).forEach(t => member(t, ['beginner', 'intermediate', 'advanced']));
  strings(v.language_modes).forEach(t => member(t, LANGUAGE_MODES));
  const d = object(v.duration_minutes); integer(d.minimum); integer(d.maximum); integer(d.default);
  if (d.minimum !== 5 || d.maximum !== 60 || d.default !== 15 || v.camera_default !== false) invalid();
  return v as unknown as InterviewConfig;
}
export function parseCatalog(value: unknown): InterviewCatalog {
  const v = object(value); const topics = object(v.topics); TYPES.forEach(t => strings(topics[t]));
  array(v.dsa_exercises).forEach(p => { const e = object(p); ['exercise_id', 'title', 'description', 'difficulty', 'spec_version'].forEach(k => text(e[k])); strings(e.topics); if (e.constraints_summary != null) strings(e.constraints_summary); });
  return v as unknown as InterviewCatalog;
}
export function parseReport(value: unknown): InterviewReport {
  const v = object(value); text(v.session_id); text(v.completed_at); member(v.completion_reason, ['finished', 'timeout', 'questions_exhausted']); integer(v.answered_count);
  for (const key of ['semantic_validity', 'technical_correctness', 'psychology']) { const a = object(v[key]); text(a.status); text(a.reason); }
  if (object(v.semantic_validity).status !== 'unassessed' || object(v.technical_correctness).status !== 'unassessed_no_execution_evidence' || object(v.psychology).status !== 'not_assessed') invalid();
  strings(v.limitations);
  array(v.answers).forEach(item => {
    const a = object(item); ['question_id', 'question', 'answer'].forEach(k => text(a[k])); if (a.code != null) text(a.code);
    array(a.indicators).forEach(item => {
      const i = object(item); ['id', 'label', 'status', 'semantic_validity'].forEach(k => text(i[k]));
      if (![0, 1].includes(integer(i.value)) || integer(i.maximum) !== 1 || i.semantic_validity !== 'unassessed') invalid();
      array(i.excerpts).forEach(item => { const e = object(item); const start = integer(e.start), end = integer(e.end); const points = Array.from(text(a.answer)); if (start < 0 || end <= start || end > points.length || points.slice(start, end).join('') !== text(e.text)) invalid(); });
    });
  });
  if (v.practice_topics != null) array(v.practice_topics).forEach(item => { const t = object(item); member(t.type, TYPES); text(t.topic); text(t.reason); strings(t.missing_indicators); });
  array(v.recommendations).forEach(item => { const r = object(item); ['exercise_id', 'spec_version', 'reason'].forEach(k => text(r[k])); if (r.lesson_id != null) text(r.lesson_id); strings(r.missing_indicators); });
  return v as unknown as InterviewReport;
}
export function parseSession(value: unknown): InterviewSession {
  const v = object(value); text(v.id); member(v.type, TYPES); member(v.difficulty, ['beginner', 'intermediate', 'advanced']); member(v.language_mode, LANGUAGE_MODES); strings(v.topics);
  const epoch = integer(v.epoch), duration = integer(v.duration_minutes); if (epoch < 1 || duration < 5 || duration > 60) invalid();
  member(v.state, ['active', 'completed']); ['started_at', 'deadline_at'].forEach(k => { if (!Number.isFinite(Date.parse(text(v[k])))) invalid(); });
  message(v.introduction); if (v.acknowledgement != null) message(v.acknowledgement);
  if (v.question != null) { const q = object(v.question); message(q); text(q.id); member(q.kind, ['primary', 'followup']); if (q.parent_id != null) text(q.parent_id); }
  if (v.report != null) parseReport(v.report);
  if ((v.state === 'active' && !v.question) || (v.state === 'completed' && (!v.report || v.question))) invalid();
  return v as unknown as InterviewSession;
}
