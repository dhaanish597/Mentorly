import type { components } from './types/openapi';

export type Scenario = { id: string; title: string; mode: string; version: string };
export type Workspace = { id: string; token: string };
export type StudioSession = { id: string; token: string; workspace: Workspace };
// Dynamic properties are bounded JSON at the backend boundary, not fixed schema fields.
export type StudioNode = Omit<components['schemas']['Node'], 'properties'> & { properties: Record<string, unknown> };
export type StudioEdge = components['schemas']['Edge'];
export type TurnCorrectionRequest = Omit<components['schemas']['TurnCorrection'], 'kind'> & { kind?: string | null };
export type Graph = { nodes: StudioNode[]; edges: StudioEdge[]; assumptions: Record<string, unknown> };
export class StudioError extends Error { constructor(public status: number, message: string) { super(message); } }
export function capability(): string { return `${crypto.randomUUID()}${crypto.randomUUID()}`; }
export async function studioRequest<T>(path: string, options: { method?: string; token?: string; body?: unknown; signal?: AbortSignal; workspace?: Workspace; sessionToken?: string } = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (options.sessionToken) headers['X-Session-Token'] = options.sessionToken;
  if (options.workspace) { headers['X-Workspace-Id'] = options.workspace.id; headers['X-Workspace-Token'] = options.workspace.token; }
  if (method !== 'GET') headers['X-Idempotency-Key'] = crypto.randomUUID();
  const body = options.body instanceof FormData ? options.body : options.body === undefined ? undefined : JSON.stringify(options.body);
  if (body !== undefined && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const res = await fetch(`/api/v1${path}`, { method, headers, body, signal: options.signal });
  if (!res.ok) { const detail = await res.json().catch(() => null); throw new StudioError(res.status, typeof detail?.detail === 'string' ? detail.detail : detail?.message ?? `Request failed (${res.status})`); }
  return res.status === 204 ? undefined as T : await res.json() as T;
}
const KEY = 'viva-studio-tab-v1';
export function readStudioTab(): { workspace?: Workspace; sessions: StudioSession[] } {
  try { const data = JSON.parse(sessionStorage.getItem(KEY) ?? '{}'); return { workspace: data.workspace, sessions: Array.isArray(data.sessions) ? data.sessions : [] }; } catch { return { sessions: [] }; }
}
export function writeStudioTab(data: { workspace?: Workspace; sessions: StudioSession[] }): void { sessionStorage.setItem(KEY, JSON.stringify(data)); }
