import type { Workspace } from '../../studioApi';

const KEY = 'viva-learning-sessions-v1';
interface StoredLessonSession { workspaceId: string; lessonId: string; sessionId: string }
function savedSessions(): StoredLessonSession[] {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((item): item is StoredLessonSession => !!item && typeof item === 'object' && typeof item.workspaceId === 'string' && typeof item.lessonId === 'string' && typeof item.sessionId === 'string') : [];
  } catch { return []; }
}
export function readLessonSession(workspace: Workspace, lessonId: string): string | null {
  return savedSessions().find(item => item.workspaceId === workspace.id && item.lessonId === lessonId)?.sessionId ?? null;
}
export function rememberLessonSession(workspace: Workspace, lessonId: string, sessionId: string): boolean {
  try {
    const others = savedSessions().filter(item => item.workspaceId !== workspace.id || item.lessonId !== lessonId);
    sessionStorage.setItem(KEY, JSON.stringify([...others, { workspaceId: workspace.id, lessonId, sessionId }]));
    return true;
  } catch { return false; }
}
export function forgetLessonSession(workspace: Workspace, lessonId: string): void {
  sessionStorage.setItem(KEY, JSON.stringify(savedSessions().filter(item => item.workspaceId !== workspace.id || item.lessonId !== lessonId)));
}
