import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { loadAudioPreferences, loadSpeechPreferences, saveAudioPreferences } from '../voice/preferences';
import { loadProductState } from '../state/productState';

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); history.replaceState({}, '', '/settings'); vi.spyOn(window, 'scrollTo').mockImplementation(() => {}); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('functional product settings', () => {
  it('saves every displayed audio control and the chosen provider voice', () => {
    render(<ProductApp />);
    for (const name of ['Voice output', 'Automatically read responses', 'Play introductions', 'Mute audio']) fireEvent.click(screen.getByRole('checkbox', { name }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Playback speed' }), { target: { value: '1.5' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Spoken voice' }), { target: { value: 'Shivani' } });
    expect(loadAudioPreferences()).toMatchObject({ voiceOutput: false, autoSpeak: true, introductions: true, muted: true, speed: 1.5 });
    expect(loadSpeechPreferences().voice).toBe('Shivani');
  });
  it('saves recognition and spoken languages while limiting code mixing to supported locales', () => {
    history.replaceState({}, '', '/settings?category=language'); render(<ProductApp />);
    expect(screen.getByRole('checkbox', { name: 'Mix with English' })).toBeDisabled();
    expect(screen.getAllByRole('option', { name: 'Tamil · தமிழ்' })).toHaveLength(2);
    expect(screen.getAllByRole('option', { name: 'Bengali · বাংলা' })).toHaveLength(2);
    fireEvent.change(screen.getByRole('combobox', { name: 'Recognition language' }), { target: { value: 'ta-IN' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Spoken response language' }), { target: { value: 'hi-IN' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mix with English' }));
    expect(loadSpeechPreferences()).toMatchObject({ sttLanguage: 'ta-IN', spokenLanguage: 'hi-IN', codeMixing: true });
    expect(screen.getByText(/Full interface translation is not available/i)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Recognition language' }), { target: { value: 'en-IN' } });
    expect(loadSpeechPreferences().codeMixing).toBe(false);
  });
  it('uses keyboard category navigation and wraps focus logically', () => {
    render(<ProductApp />);
    const first = screen.getByRole('link', { name: 'Voice & Audio' }); first.focus();
    fireEvent.keyDown(first, { key: 'ArrowDown' });
    expect(screen.getByRole('link', { name: 'Language' })).toHaveFocus();
    expect(screen.getByRole('heading', { name: 'Language' })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('link', { name: 'Language' }), { key: 'End' });
    expect(screen.getByRole('link', { name: 'Advanced' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('link', { name: 'Advanced' }), { key: 'Home' });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: 'ArrowUp' });
    expect(screen.getByRole('link', { name: 'Advanced' })).toHaveFocus();
  });
  it('describes actual privacy behavior without a pretend delete button', () => {
    history.replaceState({}, '', '/settings?category=privacy'); render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'In this tab’s workspace' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open workspace controls' })).toHaveAttribute('href', '/studio');
    expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument();
  });
  it('supports light and system appearance and cancels destructive confirmation', () => {
    history.replaceState({}, '', '/settings?category=appearance'); render(<ProductApp />);
    fireEvent.click(screen.getByRole('radio', { name: 'Light' })); expect(loadProductState().theme).toBe('light');
    fireEvent.click(screen.getByRole('radio', { name: 'System' })); expect(loadProductState().theme).toBe('system');
    fireEvent.click(screen.getByRole('link', { name: 'Advanced' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reset preferences' }));
    expect(screen.getByRole('button', { name: 'Confirm reset' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('button', { name: 'Confirm reset' })).not.toBeInTheDocument();
  });
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
    expect(screen.getByText('Your preferences could not be saved on this device. Keep this tab open and try again.')).toHaveAttribute('role', 'alert');
  });
});
