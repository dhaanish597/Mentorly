import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CoachingHintFeed, FreshCaseTransferCard } from '../components/WorkbenchComponents';
import { createInitialWorkbenchState } from '../state/useSessionStore';
import type { EvidenceArtifact } from '../types/api';
afterEach(cleanup);
describe('contextual coding mentor controls',()=>{
  it('does not show a wall of disabled hint actions before evidence exists',()=>{
    render(<CoachingHintFeed state={createInitialWorkbenchState()} onRequestHintLevel={vi.fn()}/>);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
  it('offers only the next available grounded hint',()=>{
    const state={...createInitialWorkbenchState(),activeArtifact:{} as EvidenceArtifact};
    render(<CoachingHintFeed state={state} onRequestHintLevel={vi.fn()}/>);
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button',{name:'Level 1 Hint'})).toBeTruthy();
  });
  it('keeps fresh transfer out of the initial workspace and reveals it when ready',()=>{
    const state=createInitialWorkbenchState();
    const view=render(<FreshCaseTransferCard state={state} onIssueTransferChallenge={vi.fn()}/>);
    expect(screen.queryByRole('button',{name:'Load Held-Out Transfer Case'})).toBeNull();
    view.rerender(<FreshCaseTransferCard state={{...state,learningState:'FRESH_CASE_CHECK'}} onIssueTransferChallenge={vi.fn()}/>);
    expect(screen.getByRole('button',{name:'Load Held-Out Transfer Case'})).toBeTruthy();
  });
});
