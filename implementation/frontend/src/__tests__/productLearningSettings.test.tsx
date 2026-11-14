import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { loadAudioPreferences, saveAudioPreferences } from '../voice/preferences';
import { loadProductState } from '../state/productState';

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); history.replaceState({}, '', '/settings'); vi.spyOn(window, 'scrollTo').mockImplementation(() => {}); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('functional product settings', () => {
  it('exposes categories and persists real audio preferences', () => {
    render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'Voice & Audio' })).toBeInTheDocument();
    for (const name of ['Voice & Audio', 'Language', 'Learning', 'Appearance', 'Privacy', 'Advanced']) expect(screen.getByRole('link', { name })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Text-only mode' }));
    fireEvent.change(screen.getByRole('slider', { name: 'Playback volume' }), { target: { value: '0.4' } });
    expect(loadAudioPreferences().textOnly).toBe(true);
    expect(loadAudioPreferences().volume).toBe(0.4);
    expect(screen.getByRole('status')).toHaveTextContent('Saved on this device');
  });
  it('updates and persists existing appearance without overwriting saved drafts', () => {
    localStorage.setItem('vcc-product-v1', JSON.stringify({ bookmarks: ['real-problem'], theme: 'system' }));
    history.replaceState({}, '', '/settings?category=appearance'); render(<ProductApp />);
    fireEvent.click(screen.getByRole('radio', { name: 'Dark' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(loadProductState().theme).toBe('dark');
    expect(loadProductState().bookmarks).toEqual(['real-problem']);
  });
  it('explains learning limitations rather than rendering pretend controls', () => {
    history.replaceState({}, '', '/settings?category=learning'); render(<ProductApp />);
    expect(screen.getByText(/study goals and reminders are not available/i)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open curriculum' })).toHaveAttribute('href', '/learn');
  });
  it('resets preferences only after confirmation and preserves workspace credentials', () => {
    saveAudioPreferences({ ...loadAudioPreferences(), textOnly: true });
    sessionStorage.setItem('viva-studio-tab-v1', 'workspace-stays');
    history.replaceState({}, '', '/settings?category=advanced'); render(<ProductApp />);
    fireEvent.click(screen.getByRole('button', { name: 'Reset preferences' }));
    expect(screen.getByRole('button', { name: 'Confirm reset' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reset' }));
    expect(loadAudioPreferences().textOnly).toBe(false);
    expect(sessionStorage.getItem('viva-studio-tab-v1')).toBe('workspace-stays');
    expect(screen.getByRole('status')).toHaveTextContent('Preferences reset');
  });
  it('reports persistence denial rather than claiming a successful save', () => {
    render(<ProductApp />);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Text-only mode' }));
    expect(screen.getByRole('alert')).toHaveTextContent('could not be saved');
  });
});
