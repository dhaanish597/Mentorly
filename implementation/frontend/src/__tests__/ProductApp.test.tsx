import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import ProductApp from '../ProductApp';
import { apiClient } from '../services/apiClient';

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });
describe('product entry surfaces', () => {
  it('offers a real library destination from landing', () => {
    history.replaceState({}, '', '/'); render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'Don’t just solve it. Explain why it works.' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Explore problems' }).getAttribute('href')).toBe('/library');
  });
  it('shows saved local practice counts without inventing completion', async () => {
    history.replaceState({}, '', '/progress');
    localStorage.setItem('vcc-product-v1', JSON.stringify({ bookmarks: ['p1'], drafts: {} }));
    vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
    render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'Progress' })).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByText(/not proven mastery/)).toBeTruthy();
    await waitFor(() => expect(apiClient.getExercises).toHaveBeenCalled());
  });
  it('reports unavailable catalog and offers retry on dashboard', async () => {
    history.replaceState({}, '', '/dashboard');
    vi.spyOn(apiClient, 'getExercises').mockRejectedValue(new Error('offline'));
    render(<ProductApp />);
    expect((await screen.findByRole('alert')).textContent).toContain('practice library is unavailable');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });
  it('updates the rendered surface after browser history navigation', async () => {
    history.replaceState({}, '', '/dashboard');
    vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
    render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'What will you explore today?' })).toBeTruthy();
    act(() => { history.pushState({}, '', '/paths'); window.dispatchEvent(new PopStateEvent('popstate')); });
    expect(screen.getByRole('heading', { name: 'Learning paths' })).toBeTruthy();
    await waitFor(() => expect(apiClient.getExercises).toHaveBeenCalled());
  });
  it('reads the latest saved theme when system appearance changes', () => {
    history.replaceState({}, '', '/');
    let listener: (() => void) | undefined;
    const media = { matches: true, addEventListener: (_: string, fn: () => void) => { listener = fn; }, removeEventListener: () => {} };
    vi.stubGlobal('matchMedia', () => media);
    render(<ProductApp />);
    expect(document.documentElement.dataset.theme).toBe('dark');
    localStorage.setItem('vcc-product-v1', JSON.stringify({ theme: 'light' }));
    act(() => listener?.());
    expect(document.documentElement.dataset.theme).toBe('light');
    vi.unstubAllGlobals();
  });

  it('keeps landing accessible and offers explicit legacy session recovery', () => {
    history.replaceState({}, '', '/');
    sessionStorage.setItem('vcc-session', JSON.stringify({ id: 'old', token: 'token' }));
    render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'Don’t just solve it. Explain why it works.' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Resume previous session' }).getAttribute('href')).toBe('/?resume=1');
  });

  it('opens the legacy recovery workbench only when explicitly requested', () => {
    history.replaceState({}, '', '/?resume=1');
    sessionStorage.setItem('vcc-session', JSON.stringify({ id: 'old', token: 'token' }));
    vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
    render(<ProductApp />);
    expect(screen.getByText('Loading workspace metadata...')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Don’t just solve it. Explain why it works.' })).toBeNull();
  });

});
