import { useEffect, useMemo, useState } from 'react';
import { parseInterviewSessionReference } from '../../services/learningApi';
import { createInterviewApi } from './api';
import { InterviewReportView } from './InterviewReportView';
import type { InterviewReport, Workspace } from './types';
import './interview.css';

type ReportRouteProps = { workspace: Workspace | null; search: string };
type ReportReaderProps = { workspace: Workspace; sessionId: string };
type ReportState = { status: 'loading' } | { status: 'unavailable' } | { status: 'ready'; report: InterviewReport };

function ReportUnavailable({ onRetry }: { onRetry?: () => void }): JSX.Element {
  return <div className="interview-error" role="alert"><p>Interview report unavailable. Only completed reports from this workspace can be viewed.</p>{onRetry && <button type="button" onClick={onRetry}>Retry interview report</button>}</div>;
}

function ReportReader({ workspace, sessionId }: ReportReaderProps): JSX.Element {
  const api = useMemo(() => createInterviewApi({ id: workspace.id, token: workspace.token }), [workspace.id, workspace.token]);
  const [state, setState] = useState<ReportState>({ status: 'loading' });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    api.getReport(sessionId).then(report => {
      if (!live) return;
      if (report.session_id !== sessionId) {
        setState({ status: 'unavailable' });
        return;
      }
      setState({ status: 'ready', report });
    }).catch(() => {
      if (live) setState({ status: 'unavailable' });
    });
    // The existing interview transport has no abort signal; fence every late result.
    return () => { live = false; };
  }, [api, sessionId, retry]);
  if (state.status === 'loading') return <p role="status">Loading interview report…</p>;
  if (state.status === 'unavailable') return <ReportUnavailable onRetry={() => setRetry(value => value + 1)} />;
  return <InterviewReportView report={state.report} />;
}

function selectedReport(search: string): string | undefined {
  const selectors = new URLSearchParams(search).getAll('report');
  if (selectors.length !== 1) return undefined;
  // URLSearchParams replaces malformed UTF-8; verify the raw selector first.
  const rawSelector = search.replace(/^\?/, '').split('&').find(part => new URLSearchParams(part).has('report'));
  try { decodeURIComponent(rawSelector ?? ''); }
  catch { return undefined; }
  return parseInterviewSessionReference(selectors[0]);
}

/** Separate from the interactive page: one read, no resume storage or media lifecycle. */
export function InterviewReportRoute({ workspace, search }: ReportRouteProps): JSX.Element {
  const sessionId = selectedReport(search);
  // Remount before painting a different route/capability so old evidence cannot flash.
  const readerKey = workspace && sessionId ? JSON.stringify([workspace.id, workspace.token, search]) : '';
  return <section className="interview-page" aria-labelledby="recorded-interview-title">
    <header className="interview-page-heading"><p>Recorded workspace activity</p><h1 id="recorded-interview-title">Your recorded interview</h1><p>Read-only evidence from a completed interview, not a new assessment.</p><a href="/progress">Back to progress</a></header>
    {!workspace || !sessionId ? <ReportUnavailable /> : <ReportReader key={readerKey} workspace={workspace} sessionId={sessionId} />}
  </section>;
}
