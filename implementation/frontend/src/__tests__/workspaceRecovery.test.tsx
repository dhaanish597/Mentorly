import '@testing-library/jest-dom/vitest';
import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WorkspaceRecovery } from '../features/settings/WorkspaceRecovery';
import { studioRequest } from '../studioApi';

vi.mock('../studioApi', async importOriginal => ({ ...await importOriginal<typeof import('../studioApi')>(), studioRequest: vi.fn() }));
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); vi.mocked(studioRequest).mockReset(); });

it('restores workspace access without bulk capability rotation for many sessions', async () => {
  vi.mocked(studioRequest).mockImplementation(async path => {
    if (path.endsWith('/recover')) return { workspace_id: 'owned-workspace', expires_at: '2099-01-01' };
    if (path.endsWith('/archive')) return { data: {
      studio_sessions: Array.from({ length: 200 }, (_, n) => ({ id: `studio-${n}`, scenario_id: 'cache-design', mode: 'guided_system_design', state: 'active' })),
      dsa_sessions: [], learning_sessions: [], learning_answers: [], interviews: [], interview_reports: [],
    } };
    throw new Error('Bulk rotation must not occur');
  });
  render(<WorkspaceRecovery />);
  fireEvent.change(screen.getByLabelText('Workspace ID to recover'), { target: { value: 'owned-workspace' } });
  fireEvent.change(screen.getByLabelText('Recovery secret'), { target: { value: 'r'.repeat(43) } });
  fireEvent.click(screen.getByRole('button', { name: 'Restore workspace access' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Workspace access restored'));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Resume a practice session' })).toBeInTheDocument());
  expect(studioRequest).toHaveBeenCalledTimes(2);
  expect(vi.mocked(studioRequest).mock.calls.some(([path]) => path.endsWith('/capability'))).toBe(false);
  expect(localStorage.getItem('viva-studio-tab-v1')).toBeNull();
  expect(sessionStorage.getItem('viva-studio-tab-v1')).toContain('owned-workspace');
});

it('shows failed recovery without replacing an existing tab capability', async () => {
  sessionStorage.setItem('viva-studio-tab-v1', JSON.stringify({ workspace: { id: 'existing', token: 'current' }, sessions: [] }));
  vi.mocked(studioRequest).mockRejectedValue(new Error('Recovery credential is invalid or expired'));
  render(<WorkspaceRecovery />);
  fireEvent.change(screen.getByLabelText('Workspace ID to recover'), { target: { value: 'unknown' } });
  fireEvent.change(screen.getByLabelText('Recovery secret'), { target: { value: 'r'.repeat(43) } });
  fireEvent.click(screen.getByRole('button', { name: 'Restore workspace access' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('invalid or expired'));
  expect(sessionStorage.getItem('viva-studio-tab-v1')).toContain('existing');
});
