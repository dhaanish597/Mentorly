/**
 * Typed HTTP client for Coordinator Metadata, Session, Turn, Verification & Speech APIs (`frontend/src/services/apiClient.ts`).
 *
 * Preserves 100% of Phase 0 metadata fetchers (`fetchHealth`, `fetchBranding`, `fetchExercises`, `fetchDemoPresets`)
 * while adding Phase 3–Phase 7 session lifecycle methods.
 */

import type {
  BrandingInfo,
  CancelRequest,
  CancelResponse,
  CapacityResponse,
  Challenge,
  CodeUpdateRequest,
  CodeUpdateResponse,
  ConfirmClaimRequest,
  CreateChallengeRequest,
  CreateSessionRequest,
  CreateSessionResponse,
  DeleteSessionResponse,
  DemoPresetMetadata,
  ExerciseMetadata,
  FreshCaseCheckRequest,
  HealthResponse,
  HintRequest,
  PlaybackAckRequest,
  SessionExportResponse,
  SpecAckRequest,
  SpecUpdateRequest,
  TextTurnRequest,
  VoicePlaybackAckResponse,
  ClaimInterpretation, EvidenceArtifact, HiddenEvidenceArtifactView, RevisionRef, TraceExecutionReport, VerifyRequest,
} from '../types/api';

const API_BASE = '/api/v1';

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'GET',
    headers: { Accept: 'application/json', ...sessionHeaders(path) },
    signal,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} fetching ${path}`);
  }
  return (await response.json()) as T;
}

async function sendJson<T>(
  method: 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...sessionHeaders(path),
      'X-Idempotency-Key': crypto.randomUUID(),
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.message ?? detail?.error?.message ?? detail?.detail ?? `HTTP ${response.status} on ${method} ${path}`);
  }
  return (await response.json()) as T;
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return getJson<HealthResponse>('/meta/health', signal);
}

export function fetchBranding(signal?: AbortSignal): Promise<BrandingInfo> {
  return getJson<BrandingInfo>('/meta/branding', signal);
}

export function fetchExercises(signal?: AbortSignal): Promise<ExerciseMetadata[]> {
  return getJson<ExerciseMetadata[]>('/meta/exercises', signal);
}

export function fetchDemoPresets(signal?: AbortSignal): Promise<DemoPresetMetadata[]> {
  return getJson<DemoPresetMetadata[]>('/meta/demo-presets', signal);
}

export function createSession(req: CreateSessionRequest): Promise<CreateSessionResponse> {
  return sendJson<CreateSessionResponse>('POST', '/sessions', req);
}

export function updateSessionCode(
  sessionId: string,
  req: CodeUpdateRequest,
): Promise<CodeUpdateResponse> {
  return sendJson<CodeUpdateResponse>('PUT', `/sessions/${sessionId}/code`, req);
}

export function updateSessionSpec(
  sessionId: string,
  req: SpecUpdateRequest,
): Promise<Record<string, unknown>> {
  return sendJson<Record<string, unknown>>('POST', `/sessions/${sessionId}/spec`, req);
}

export function acknowledgeSessionSpec(
  sessionId: string,
  req: SpecAckRequest,
): Promise<Record<string, unknown>> {
  return sendJson<Record<string, unknown>>('POST', `/sessions/${sessionId}/spec-ack`, req);
}

export function createChallenge(
  sessionId: string,
  req: CreateChallengeRequest,
): Promise<Challenge> {
  return sendJson<Challenge>('POST', `/sessions/${sessionId}/challenges`, req);
}

export function submitTextTurn(
  sessionId: string,
  req: TextTurnRequest,
): Promise<Record<string, unknown>> {
  return sendJson<Record<string, unknown>>('POST', `/sessions/${sessionId}/turns/text`, req);
}

export function confirmTurnClaim(
  sessionId: string,
  turnId: string,
  req: Omit<ConfirmClaimRequest, 'challenge_id'> & { challenge_id?: string; capture_attempt_id?: number },
): Promise<Record<string, unknown>> {
  return sendJson<Record<string, unknown>>(
    'POST',
    `/sessions/${sessionId}/turns/${turnId}/confirm-claim`,
    req,
  );
}

export function submitFreshCaseCheck(
  sessionId: string,
  req: FreshCaseCheckRequest,
): Promise<Record<string, unknown>> {
  return sendJson<Record<string, unknown>>(
    'POST',
    `/sessions/${sessionId}/fresh-case-check`,
    req,
  );
}

export function requestCoachingHint(
  sessionId: string,
  req: HintRequest,
): Promise<Record<string, unknown>> {
  return sendJson<Record<string, unknown>>('POST', `/sessions/${sessionId}/hints`, req);
}

export function sendPlaybackAck(
  sessionId: string,
  req: PlaybackAckRequest,
): Promise<VoicePlaybackAckResponse> {
  return sendJson<VoicePlaybackAckResponse>(
    'POST',
    `/sessions/${sessionId}/playback-ack`,
    req,
  );
}

export function cancelSessionWork(
  sessionId: string,
  req: CancelRequest,
): Promise<CancelResponse> {
  return sendJson<CancelResponse>('POST', `/sessions/${sessionId}/cancel`, req);
}

export function exportSessionBundle(sessionId: string): Promise<SessionExportResponse> {
  return getJson<SessionExportResponse>(`/sessions/${sessionId}/export`);
}

export function deleteSession(sessionId: string): Promise<DeleteSessionResponse> {
  return sendJson<DeleteSessionResponse>('DELETE', `/sessions/${sessionId}`);
}

export function fetchCapacity(signal?: AbortSignal): Promise<CapacityResponse> {
  return getJson<CapacityResponse>('/capacity', signal);
}

// Tokens stay in the browser session; they are never placed in URLs or exports.
const sessionTokens = new Map<string, string>();
export function registerSessionToken(sessionId: string, token: string): void {
  sessionTokens.set(sessionId, token);
}
function sessionHeaders(path: string): Record<string, string> {
  const sessionId = /^\/sessions\/([^/]+)/.exec(path)?.[1];
  const token = sessionId ? sessionTokens.get(sessionId) : undefined;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface SessionSnapshot {
  session_id: string;
  state: import('../types/api').SessionState;
  learning_state: import('../types/api').LearningState;
  spec_acknowledged: boolean;
  language_mode: import('../types/api').LanguageMode;
  interaction_mode: import('../types/api').InteractionMode;
  source_code: string;
  revision: import('../types/api').RevisionRef;
  latest_client_edit_sequence?: number;
  prior_artifact_id?: string | null;
  challenges: Challenge[];
  evidence_artifacts: Array<EvidenceArtifact | HiddenEvidenceArtifactView>;
  active_turn?: { state?: import('../types/api').TurnState; turn_id: string; proposed_claim: ClaimInterpretation | null; capture_attempt_id: number; turn_generation: number; transcript?: string } | null;
  verification_report?: import('../types/api').VerificationReport | null;
  trace_report?: TraceExecutionReport | null;
  coaching?: CoachingResponse | null;
}
export interface TurnResponse { turn_id: string; revision: RevisionRef; proposed_claim: ClaimInterpretation; capture_attempt_id: number; turn_generation?: number; transcript?: string; normalized_transcript?: string }
export interface CoachingResponse {
  display_text?: string; text?: string; hint_level?: number; pointed_line?: number | null; pointed_event_id?: number | null; source_mode?: string;
}
export interface ResultResponse {
  session_state: import('../types/api').SessionState;
  learning_state: import('../types/api').LearningState;
  revision: RevisionRef;
  artifact?: EvidenceArtifact | HiddenEvidenceArtifactView | null;
  verification_report?: import('../types/api').VerificationReport | null;
  challenge?: Challenge | null;
  diagnostic_challenge?: Challenge | null;
  trace_report?: TraceExecutionReport | null;
  coaching?: CoachingResponse | null;
  executed?: boolean;
}
export function verifyRepair(sessionId: string, req: VerifyRequest & { run_curated_suite: boolean; generated_cases_target: number }): Promise<ResultResponse> {
  return sendJson<ResultResponse>('POST', `/sessions/${sessionId}/verify`, req);
}
export function retryExecution(sessionId: string, turnId: string, req: { revision: RevisionRef }): Promise<ResultResponse> {
  return sendJson<ResultResponse>('POST', `/sessions/${sessionId}/turns/${turnId}/retry-execution`, req);
}
export function restoreSession(sessionId: string): Promise<SessionSnapshot> {
  return getJson<SessionSnapshot>(`/sessions/${sessionId}`);
}

export interface OrientationAudio {
  audio: ArrayBuffer;
  playbackId: string | null;
}

/** Only fixed server-authored messages: never accepts a hidden answer or caller text. */
export async function requestVoiceOrientation(
  sessionId: string,
  revision: RevisionRef,
  purpose: 'introduction' | 'test-voice',
  signal?: AbortSignal,
): Promise<OrientationAudio> {
  const path = `/sessions/${sessionId}/speech/${purpose}`;
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST', signal,
    headers: {
      Accept: 'audio/wav', 'Content-Type': 'application/json',
      ...sessionHeaders(path), 'X-Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ revision }),
  });
  if (!response.ok) {
    const detail: unknown = await response.json().catch(() => null);
    const message = detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string'
      ? detail.message : 'Voice is unavailable. Continue with text.';
    throw new Error(message);
  }
  if (!response.headers.get('Content-Type')?.startsWith('audio/wav')) {
    throw new Error('The voice service returned an unsupported audio format. Continue with text.');
  }
  return { audio: await response.arrayBuffer(), playbackId: response.headers.get('X-Playback-ID') };
}

// Kept for metadata clients from the base implementation.
export const apiClient = {
  getHealth: fetchHealth,
  getBranding: fetchBranding,
  getExercises: fetchExercises,
  getDemoPresets: fetchDemoPresets,
};
