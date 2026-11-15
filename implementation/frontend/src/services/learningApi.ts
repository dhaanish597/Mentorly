import { studioRequest, type Workspace } from '../studioApi';

export interface LearningQuestion { id: string; prompt: string; options?: string[] }
export interface LearningLesson {
  id: string; title: string; prerequisites: string[]; difficulty: string; estimated_minutes: number;
  objectives: string[]; explanation: string; example: string; hints: string[];
  practice_url: string; question: LearningQuestion;
}
export interface LearningTrack { id: string; module: string; title: string; description: string; lessons: LearningLesson[] }
export interface LearningCatalog { version: string; tracks: LearningTrack[] }
export interface LearningAchievement { id: string; title: string; earned_at: string; source_event: string }
export interface LearningRecommendation { lesson_id: string; title: string; reason: string; url: string }
export interface LearningActivity { id?: string; title: string; occurred_at?: string; kind?: string; session_id?: string }
export interface LearningProgress {
  lessons_completed: number; attempts: number; topics_mastered: number; practice_sessions: number;
  interviews_completed: number; study_seconds: number; streak: number; completed_lesson_ids: string[];
  achievements: LearningAchievement[]; recommendations: LearningRecommendation[]; recent_activity: LearningActivity[];
}
export interface LearningFeedback { correct: boolean; message: string; hint?: string }
export interface LearningReport { lesson_completed: boolean; summary: string }
export interface LearningCoachMessage { id: string; role: string; kind: string; text: string }
export interface LearningSession {
  id: string; lesson_id: string; epoch: number; mode: string; state: string; question: LearningQuestion;
  coach_messages: string[]; coach_message_refs: LearningCoachMessage[]; answer_count: number; hint_count?: number; deadline: null; feedback?: LearningFeedback;
  report?: LearningReport; hint?: string;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Learning data is unavailable. Please retry.');
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Learning data is incomplete. Please retry.');
  return value;
}
function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('Learning data is incomplete. Please retry.');
  return value;
}
function texts(value: unknown): string[] { return list(value).map(text); }
function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw new Error('Learning progress is incomplete. Please retry.');
  return value;
}
/** Links from the learning API must stay within the product. */
export function learningUrl(value: unknown, fallback = '/learn'): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\s]/.test(value)) return fallback;
  try {
    const url = new URL(value, 'https://viva.invalid');
    const href = `${url.pathname}${url.search}${url.hash}`;
    if (!href.startsWith('/') || href.startsWith('//') || /[\\\s]/.test(href)) return fallback;
    return url.origin === 'https://viva.invalid' && new URL(href, 'https://viva.invalid').origin === 'https://viva.invalid' ? href : fallback;
  } catch { return fallback; }
}
function question(value: unknown): LearningQuestion {
  const raw = object(value);
  return { id: text(raw.id), prompt: text(raw.prompt), ...(raw.options == null ? {} : { options: list(raw.options).map(option => typeof option === 'string' ? option : text(object(option).label ?? object(option).text)) }) };
}
function lesson(value: unknown): LearningLesson {
  const raw = object(value);
  return { id: text(raw.id), title: text(raw.title), prerequisites: texts(raw.prerequisites), difficulty: text(raw.difficulty), estimated_minutes: count(raw.estimated_minutes), objectives: texts(raw.objectives), explanation: text(raw.explanation), example: text(raw.example), hints: texts(raw.hints), practice_url: learningUrl(raw.practice_url, '/library'), question: question(raw.question) };
}
export function parseLearningCatalog(value: unknown): LearningCatalog {
  const raw = object(value);
  return { version: text(raw.version), tracks: list(raw.tracks).map(value => { const track = object(value); return { id: text(track.id), module: text(track.module), title: text(track.title), description: text(track.description), lessons: list(track.lessons).map(lesson) }; }) };
}
const MAX_INTERVIEW_SESSION_REFERENCE_LENGTH = 200;
/** Opaque references stay bounded and must be encoded at every URL use. */
export function parseInterviewSessionReference(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '.' && value !== '..' && value.length > 0 && value.length <= MAX_INTERVIEW_SESSION_REFERENCE_LENGTH
    && !/[\s\p{Cc}\p{Cf}\p{Cs}]/u.test(value) ? value : undefined;
}
function activity(value: unknown): LearningActivity {
  const item = object(value);
  const sessionId = parseInterviewSessionReference(item.session_id);
  return {
    id: typeof item.id === 'string' ? item.id : undefined,
    title: text(item.title ?? item.description ?? item.event_type),
    occurred_at: typeof item.created_at === 'string' ? item.created_at : typeof item.occurred_at === 'string' ? item.occurred_at : undefined,
    kind: typeof item.type === 'string' ? item.type : typeof item.kind === 'string' ? item.kind : undefined,
    ...(sessionId ? { session_id: sessionId } : {}),
  };
}
export function parseLearningProgress(value: unknown): LearningProgress {
  const raw = object(value);
  return {
    lessons_completed: count(raw.lessons_completed), attempts: count(raw.attempts), topics_mastered: count(raw.topics_mastered), practice_sessions: count(raw.practice_sessions), interviews_completed: count(raw.interviews_completed), study_seconds: count(raw.study_seconds), streak: count(raw.streak), completed_lesson_ids: texts(raw.completed_lesson_ids),
    achievements: list(raw.achievements).flatMap(value => { const item = object(value); return typeof item.source_event === 'string' && item.source_event && typeof item.earned_at === 'string' && item.earned_at ? [{ id: text(item.id), title: text(item.title), earned_at: item.earned_at, source_event: item.source_event }] : []; }),
    recommendations: list(raw.recommendations).map(value => { const item = object(value); return { lesson_id: text(item.lesson_id), title: text(item.title), reason: text(item.reason), url: learningUrl(item.url) }; }),
    recent_activity: list(raw.recent_activity).map(activity),
  };
}
export function parseLearningSession(value: unknown): LearningSession {
  const raw = object(value);
  const feedback = raw.feedback == null ? undefined : object(raw.feedback);
  const report = raw.report == null ? undefined : object(raw.report);
  return {
    id: text(raw.id), lesson_id: text(raw.lesson_id), epoch: count(raw.epoch), mode: text(raw.mode), state: text(raw.state), question: question(raw.question), answer_count: count(raw.answer_count), deadline: null,
    coach_messages: list(raw.coach_messages).map(value => typeof value === 'string' ? value : text(object(value).text ?? object(value).message)),
    coach_message_refs: list(raw.coach_messages).flatMap(value => { if (typeof value === 'string') return []; const item = object(value); return typeof item.id === 'string' && typeof item.text === 'string' ? [{ id: item.id, text: item.text, role: typeof item.role === 'string' ? item.role : 'assistant', kind: typeof item.kind === 'string' ? item.kind : 'message' }] : []; }),
    ...(raw.hint_count == null ? {} : { hint_count: count(raw.hint_count) }),
    ...(feedback ? { feedback: { correct: feedback.correct === true, message: text(feedback.message), ...(typeof feedback.hint === 'string' ? { hint: feedback.hint } : {}) } } : {}),
    ...(report ? { report: { lesson_completed: report.lesson_completed === true, summary: typeof report.summary === 'string' ? report.summary : '' } } : {}),
    ...(typeof raw.hint === 'string' ? { hint: raw.hint } : {}),
  };
}

export const learningApi = {
  async getCatalog(signal?: AbortSignal): Promise<LearningCatalog> { return parseLearningCatalog(await studioRequest('/learning/catalog', { signal })); },
  async getProgress(workspace: Workspace, signal?: AbortSignal): Promise<LearningProgress> { return parseLearningProgress(await studioRequest('/learning/progress', { workspace, signal })); },
  async createSession(workspace: Workspace, lessonId: string, languageMode: string, signal?: AbortSignal): Promise<LearningSession> { return parseLearningSession(await studioRequest('/learning/sessions', { method: 'POST', workspace, signal, body: { lesson_id: lessonId, mode: 'practice', language_mode: languageMode } })); },
  async getSession(workspace: Workspace, id: string, signal?: AbortSignal): Promise<LearningSession> { return parseLearningSession(await studioRequest(`/learning/sessions/${encodeURIComponent(id)}`, { workspace, signal })); },
  async answer(workspace: Workspace, session: LearningSession, answer: string, signal?: AbortSignal): Promise<LearningSession> { return parseLearningSession(await studioRequest(`/learning/sessions/${encodeURIComponent(session.id)}/answers`, { method: 'POST', workspace, signal, body: { expected_epoch: session.epoch, question_id: session.question.id, answer } })); },
  async restart(workspace: Workspace, session: LearningSession, signal?: AbortSignal): Promise<LearningSession> { return parseLearningSession(await studioRequest(`/learning/sessions/${encodeURIComponent(session.id)}/restart`, { method: 'POST', workspace, signal, body: { expected_epoch: session.epoch } })); },
  async hint(workspace: Workspace, session: LearningSession, signal?: AbortSignal): Promise<LearningSession> { return parseLearningSession(await studioRequest(`/learning/sessions/${encodeURIComponent(session.id)}/hints`, { method: 'POST', workspace, signal, body: { expected_epoch: session.epoch } })); },
};
