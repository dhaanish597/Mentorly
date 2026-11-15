import '@testing-library/jest-dom/vitest';
import { StrictMode } from 'react';
import { renderToString } from 'react-dom/server';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InterviewDefaults } from '../features/settings/InterviewDefaults';
import { InterviewSetup } from '../features/interview/InterviewSetup';
import { INTERVIEW_PREFERENCE_CONFIG as config, loadInterviewPreferences, resetInterviewPreferences, saveInterviewPreferences } from '../features/interview/preferences';
import type { InterviewCatalog, InterviewConfig } from '../features/interview/types';
import { loadSpeechPreferences, saveSpeechPreferences } from '../voice/preferences';

const key = 'viva.interview-preferences.v1';
const selected = { type: 'system_design' as const, difficulty: 'advanced' as const, duration_minutes: 30 };
const catalog: InterviewCatalog = { topics: { dsa: ['binary-search'], cs: ['operating-systems'], system_design: ['capacity'], codebase_defense: ['ownership'] }, dsa_exercises: [] };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });
function editDefaults(): void {
  fireEvent.change(screen.getByLabelText('Default interview type'), { target: { value: 'system_design' } });
  fireEvent.change(screen.getByLabelText('Default interview difficulty'), { target: { value: 'advanced' } });
  fireEvent.change(screen.getByLabelText('Default interview duration'), { target: { value: '30' } });
}
function save(): void { fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' })); }

describe('interview defaults editor', () => {
  it('labels its fields, explains device-only bounds, and never requests APIs, workspace, camera or microphone', () => {
    const fetch = vi.fn(), media = vi.fn(); vi.stubGlobal('fetch', fetch);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: media } });
    const onSaved = vi.fn(); render(<InterviewDefaults onSaved={onSaved} />);
    expect(screen.getByLabelText('Default interview type')).toHaveValue('dsa');
    expect(screen.getByLabelText('Default interview difficulty')).toHaveValue('beginner');
    expect(screen.getByLabelText('Default interview duration')).toHaveValue(15);
    expect(screen.getByText(/only on this device/i)).toBeInTheDocument();
    expect(screen.getByText(/consent|camera/i)).toBeInTheDocument();
    expect(screen.getByText(/server.*validat/i)).toBeInTheDocument();
    editDefaults();
    expect(localStorage.getItem(key)).toBeNull(); expect(onSaved).not.toHaveBeenCalled();
    save(); expect(onSaved).toHaveBeenCalledWith(true);
    expect(fetch).not.toHaveBeenCalled(); expect(media).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
    expect(loadInterviewPreferences(config)).toEqual(selected);
  });
  it('loads stored preferences, saves explicitly and keeps speech preferences unchanged', () => {
    saveInterviewPreferences(selected, config);
    saveSpeechPreferences({ ...loadSpeechPreferences(), sttLanguage: 'bn-IN', spokenLanguage: 'bn-IN', codeMixing: true });
    const speech = loadSpeechPreferences(); const onSaved = vi.fn();
    render(<InterviewDefaults onSaved={onSaved} />);
    expect(screen.getByLabelText('Default interview type')).toHaveValue('system_design');
    fireEvent.change(screen.getByLabelText('Default interview type'), { target: { value: 'codebase_defense' } });
    expect(loadInterviewPreferences(config)).toEqual(selected);
    save();
    expect(loadInterviewPreferences(config)).toEqual({ ...selected, type: 'codebase_defense' });
    expect(loadSpeechPreferences()).toEqual(speech);
    expect(onSaved).toHaveBeenCalledWith(true);
  });
  it.each(['', '4', '61', '5.5'])('allows duration draft %j but rejects save with an accessible validation error', duration => {
    const onSaved = vi.fn(); render(<InterviewDefaults onSaved={onSaved} />);
    const input = screen.getByLabelText('Default interview duration');
    fireEvent.change(input, { target: { value: duration } });
    expect(input).toHaveValue(duration === '' ? null : Number(duration));
    save();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/whole number.*5.*60/i);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription(expect.stringMatching(/whole number/i));
    expect(localStorage.getItem(key)).toBeNull(); expect(onSaved).toHaveBeenCalledWith(false);
    fireEvent.change(input, { target: { value: '30' } }); save();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(onSaved).toHaveBeenLastCalledWith(true);
  });
  it.each(['5', '60'])('saves the inclusive duration boundary %s', duration => {
    render(<InterviewDefaults onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Default interview duration'), { target: { value: duration } }); save();
    expect(loadInterviewPreferences(config).duration_minutes).toBe(Number(duration));
  });
  it('reports denied writes visibly and never claims a save succeeded', () => {
    const onSaved = vi.fn(); render(<InterviewDefaults onSaved={onSaved} />); editDefaults();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
    save();
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be saved.*device/i);
    expect(onSaved).toHaveBeenCalledWith(false);
    expect(loadInterviewPreferences(config)).toEqual({ type: 'dsa', difficulty: 'beginner', duration_minutes: 15 });
    expect(screen.getByLabelText('Default interview duration')).toHaveValue(30);
  });
  it('shows a safe read-denial notice and still allows a valid draft', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
    render(<InterviewDefaults onSaved={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be read.*device/i);
    expect(screen.getByLabelText('Default interview duration')).toHaveValue(15);
    editDefaults(); expect(screen.getByLabelText('Default interview duration')).toHaveValue(30);
  });
  it('subscribes across editors and resets even an unsaved draft', () => {
    const first = render(<InterviewDefaults onSaved={vi.fn()} />);
    const second = render(<InterviewDefaults onSaved={vi.fn()} />);
    fireEvent.change(within(first.container).getByLabelText('Default interview duration'), { target: { value: '60' } });
    act(() => saveInterviewPreferences(selected, config));
    expect(within(first.container).getByLabelText('Default interview duration')).toHaveValue(30);
    expect(within(second.container).getByLabelText('Default interview type')).toHaveValue('system_design');
    fireEvent.change(within(first.container).getByLabelText('Default interview duration'), { target: { value: '' } });
    act(() => resetInterviewPreferences());
    expect(within(first.container).getByLabelText('Default interview duration')).toHaveValue(15);
    expect(within(second.container).getByLabelText('Default interview type')).toHaveValue('dsa');
    fireEvent.change(within(first.container).getByLabelText('Default interview duration'), { target: { value: '60' } });
    act(() => resetInterviewPreferences());
    expect(within(first.container).getByLabelText('Default interview duration')).toHaveValue(15);
  });
  it('updates on cross-tab changes, corrupt data and removal without persisting again', () => {
    render(<StrictMode><InterviewDefaults onSaved={vi.fn()} /></StrictMode>);
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    act(() => window.dispatchEvent(new StorageEvent('storage', { key, newValue: JSON.stringify(selected) })));
    expect(screen.getByLabelText('Default interview duration')).toHaveValue(30);
    act(() => window.dispatchEvent(new StorageEvent('storage', { key, newValue: '{' })));
    expect(screen.getByLabelText('Default interview type')).toHaveValue('dsa');
    act(() => window.dispatchEvent(new StorageEvent('storage', { key: null })));
    expect(screen.getByLabelText('Default interview duration')).toHaveValue(15);
    expect(setItem).not.toHaveBeenCalled();
  });
  it('uses a stable safe server snapshot without requiring browser storage', () => {
    vi.stubGlobal('window', undefined);
    const onSaved = vi.fn();
    const html = renderToString(<InterviewDefaults onSaved={onSaved} />);
    expect(html).toContain('Default interview duration');
    expect(html).toContain('value="15"');
    expect(onSaved).not.toHaveBeenCalled();
  });
  it('cleans up editor subscriptions on unmount', () => {
    const remove = vi.spyOn(window, 'removeEventListener');
    const view = render(<InterviewDefaults onSaved={vi.fn()} />); view.unmount();
    expect(remove).toHaveBeenCalledWith(key, expect.any(Function));
    expect(remove).toHaveBeenCalledWith('storage', expect.any(Function));
  });
});

describe('new interview setup defaults integration', () => {
  it('uses saved defaults on a new mount, leaves topics empty and uses shared speech language', () => {
    localStorage.setItem(key, JSON.stringify({ ...selected, topics: ['capacity'], language_mode: 'en-IN', consent: true, camera: true }));
    saveSpeechPreferences({ ...loadSpeechPreferences(), sttLanguage: 'hi-IN', spokenLanguage: 'hi-IN', codeMixing: true });
    const onStart = vi.fn(); render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={onStart} />);
    expect(screen.getByLabelText('Interview type')).toHaveValue('system_design');
    expect(screen.getByLabelText('Difficulty')).toHaveValue('advanced');
    expect(screen.getByLabelText('Duration in minutes')).toHaveValue(30);
    expect(screen.getByLabelText('Language preference')).toHaveValue('hi-IN,en-IN');
    expect(screen.getByLabelText('capacity')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    expect(onStart).toHaveBeenCalledWith({ ...selected, topics: [], language_mode: 'hi-IN,en-IN' });
  });
  it('loads preferences once, never overwrites in-progress setup from settings and reloads on remount', () => {
    const onStart = vi.fn(); const view = render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={onStart} />);
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    fireEvent.click(screen.getByLabelText('binary search'));
    fireEvent.change(screen.getByLabelText('Duration in minutes'), { target: { value: '20' } });
    act(() => saveInterviewPreferences(selected, config));
    view.rerender(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={onStart} />);
    expect(screen.getByLabelText('Interview type')).toHaveValue('dsa');
    expect(screen.getByLabelText('Duration in minutes')).toHaveValue(20);
    expect(screen.getByLabelText('binary search')).toBeChecked();
    expect(getItem.mock.calls.filter(([name]) => name === key)).toHaveLength(0);
    view.unmount();
    render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={onStart} />);
    expect(screen.getByLabelText('Interview type')).toHaveValue('system_design');
    expect(screen.getByLabelText('capacity')).not.toBeChecked();
    expect(getItem.mock.calls.filter(([name]) => name === key)).toHaveLength(1);
  });
  it('saves in the editor, remounts setup and does not implicitly save setup edits', () => {
    const editor = render(<InterviewDefaults onSaved={vi.fn()} />); editDefaults(); save(); editor.unmount();
    const view = render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('capacity'));
    fireEvent.change(screen.getByLabelText('Interview type'), { target: { value: 'codebase_defense' } });
    fireEvent.change(screen.getByLabelText('Difficulty'), { target: { value: 'intermediate' } });
    fireEvent.change(screen.getByLabelText('Duration in minutes'), { target: { value: '45' } });
    expect(screen.getByLabelText('ownership')).not.toBeChecked();
    expect(loadInterviewPreferences(config)).toEqual(selected);
    view.unmount(); render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={vi.fn()} />);
    expect(screen.getByLabelText('Interview type')).toHaveValue('system_design');
    expect(screen.getByLabelText('Difficulty')).toHaveValue('advanced');
    expect(screen.getByLabelText('Duration in minutes')).toHaveValue(30);
    expect(screen.getByLabelText('capacity')).not.toBeChecked();
  });
  it('validates against server-supported choices rather than shipped defaults', () => {
    saveInterviewPreferences(selected, config);
    const restricted: InterviewConfig = { ...config, types: ['cs'], difficulties: ['intermediate'], duration_minutes: { minimum: 5, maximum: 20, default: 15 } };
    const onStart = vi.fn(); render(<InterviewSetup config={restricted} catalog={catalog} busy={false} onStart={onStart} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    expect(onStart).toHaveBeenCalledWith({ type: 'cs', difficulty: 'intermediate', duration_minutes: 15, topics: [], language_mode: 'en-IN' });
    expect(loadInterviewPreferences(config)).toEqual(selected);
  });
  it('limits topics to eight, permits deselection and never persists topic drafts', () => {
    const topicCatalog = { ...catalog, topics: { ...catalog.topics, dsa: Array.from({ length: 9 }, (_, index) => `topic${index}`) } };
    const onStart = vi.fn(); render(<InterviewSetup config={config} catalog={topicCatalog} busy={false} onStart={onStart} />);
    for (let index = 0; index < 8; index += 1) fireEvent.click(screen.getByLabelText(`topic${index}`));
    expect(screen.getByLabelText('topic8')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('topic0'));
    expect(screen.getByLabelText('topic8')).toBeEnabled();
    fireEvent.click(screen.getByLabelText('topic8'));
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ topics: Array.from({ length: 8 }, (_, index) => `topic${index + 1}`) }));
    expect(localStorage.getItem(key)).toBeNull();
  });
  it('shows shared-speech save failures without modifying interview defaults', () => {
    saveInterviewPreferences(selected, config);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
    render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Language preference'), { target: { value: 'ta-IN' } });
    expect(screen.getByRole('status')).toHaveTextContent(/Speech preferences could not be saved/);
    expect(loadInterviewPreferences(config)).toEqual(selected);
  });
  it('shows defaults without saving or requesting media when preference reads are denied', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
    const setItem = vi.spyOn(Storage.prototype, 'setItem'), media = vi.fn();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: media } });
    const onStart = vi.fn(); render(<InterviewSetup config={config} catalog={catalog} busy={false} onStart={onStart} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start interview' }));
    expect(onStart).toHaveBeenCalledWith({ type: 'dsa', difficulty: 'beginner', duration_minutes: 15, topics: [], language_mode: 'en-IN' });
    expect(setItem).not.toHaveBeenCalled(); expect(media).not.toHaveBeenCalled();
  });
});
