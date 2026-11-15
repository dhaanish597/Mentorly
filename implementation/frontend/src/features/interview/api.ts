import { studioRequest } from '../../studioApi';
import type { InterviewApi, InterviewReport, Workspace } from './types';
import { parseCatalog, parseConfig, parseReport, parseSession } from './validation';

export interface InterviewReportApi { getReport(id: string): Promise<InterviewReport> }

/** Existing studio transport owns workspace headers; interviews accept no user IDs. */
export function createInterviewApi(workspace: Workspace): InterviewApi & InterviewReportApi {
  const request = (path: string, method = 'GET', body?: unknown): Promise<unknown> => studioRequest(`/interviews${path}`, { method, body, workspace });
  const sessionPath = (id: string): string => `/sessions/${encodeURIComponent(id)}`;
  return {
    getConfig: async () => parseConfig(await request('/config')),
    getCatalog: async () => parseCatalog(await request('/catalog')),
    createSession: async config => parseSession(await request('/sessions', 'POST', config)),
    getSession: async id => parseSession(await request(sessionPath(id))),
    getReport: async id => parseReport(await request(`/reports/${encodeURIComponent(id)}`)),
    answer: async (id, answer) => parseSession(await request(`${sessionPath(id)}/answers`, 'POST', answer)),
    finish: async (id, epoch) => parseReport(await request(`${sessionPath(id)}/finish`, 'POST', { expected_epoch: epoch })),
  };
}
