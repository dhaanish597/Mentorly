import '@testing-library/jest-dom/vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeWorkspace } from '../components/WorkbenchComponents';
import { ProductShell } from '../components/ProductShell';
import { createInitialWorkbenchState } from '../state/useSessionStore';
vi.mock('../components/PythonEditor', () => ({ PythonEditor: () => <div>Editor</div> }));
afterEach(cleanup);
describe('voice-first question workspace', () => {
  it('collapses the sidebar to named icons when a question is open', () => {
    history.replaceState(null, '', '/practice/ex1_shortest_subarray');
    const { container } = render(<ProductShell current="/library" workspace><div>Question</div></ProductShell>);
    expect(container.querySelector('.product-shell')).toHaveClass('question-workspace');
    expect(screen.getByRole('link', { name: 'Practice' })).toBeInTheDocument();
  });
  it('offers a separate code submit action without an explanation confirmation', () => {
    const state = { ...createInitialWorkbenchState(), sessionId: 'session', specAcknowledged: true };
    render(<CodeWorkspace state={state} highlightedLine={null} onChangeCode={vi.fn()} onSaveCode={vi.fn()} onSubmitCode={vi.fn()} isBusy={false} />);
    expect(screen.getByRole('button', { name: 'Submit code' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument();
  });
});
