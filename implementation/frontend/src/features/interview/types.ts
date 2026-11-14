export type InterviewType = 'dsa' | 'cs' | 'system_design' | 'codebase_defense';
export type Difficulty = 'beginner' | 'intermediate' | 'advanced';
export type LanguageMode = 'en-IN' | 'ta-IN,en-IN';
export interface Workspace { id: string; token: string }
export interface SourceRef { source: string; exercise_id?: string | null; spec_version?: string | null; policy_id?: string | null }
export interface InterviewMessage { text: string; source_refs: SourceRef[] }
export interface Question extends InterviewMessage { id: string; kind: 'primary' | 'followup'; parent_id: string | null }
export interface InterviewConfiguration { type: InterviewType; difficulty: Difficulty; topics: string[]; duration_minutes: number; language_mode: LanguageMode }
export interface InterviewConfig { types: InterviewType[]; difficulties: Difficulty[]; duration_minutes: { minimum: number; maximum: number; default: number }; language_modes: LanguageMode[]; camera_default: boolean; camera_policy?: string; assessment_policy?: string; language_policy?: string }
export interface CatalogExercise { exercise_id: string; title: string; description: string; difficulty: string; spec_version: string; topics: string[] }
export interface InterviewCatalog { topics: Record<InterviewType, string[]>; dsa_exercises: CatalogExercise[] }
export interface Excerpt { start: number; end: number; text: string }
export interface Indicator { id: string; label: string; value: number; maximum: number; status: string; excerpts: Excerpt[]; semantic_validity: string }
export interface Recommendation { exercise_id: string; spec_version: string; lesson_id: string | null; reason: string; missing_indicators: string[] }
export interface InterviewReport {
  session_id: string; completion_reason: 'finished' | 'timeout' | 'questions_exhausted'; completed_at: string; answered_count: number;
  semantic_validity: { status: string; reason: string }; technical_correctness: { status: string; reason: string }; psychology: { status: string; reason: string };
  answers: { question_id: string; question: string; answer: string; code: string | null; indicators: Indicator[] }[];
  recommendations: Recommendation[]; limitations: string[];
}
export interface InterviewSession extends InterviewConfiguration {
  id: string; epoch: number; state: 'active' | 'completed'; deadline_at: string; started_at: string;
  question: Question | null; introduction: InterviewMessage; acknowledgement: InterviewMessage | null; report: InterviewReport | null;
}
export interface AnswerInput { expected_epoch: number; answer: string; code?: string }
export interface InterviewApi {
  getConfig(): Promise<InterviewConfig>;
  getCatalog(): Promise<InterviewCatalog>;
  createSession(config: InterviewConfiguration): Promise<InterviewSession>;
  getSession(id: string): Promise<InterviewSession>;
  answer(id: string, answer: AnswerInput): Promise<InterviewSession>;
  finish(id: string, epoch: number): Promise<InterviewReport>;
}
export interface VoiceMessage extends InterviewMessage { id: string; session_id: string; epoch: number; kind: 'introduction' | 'question' | 'acknowledgement' | 'end' }
