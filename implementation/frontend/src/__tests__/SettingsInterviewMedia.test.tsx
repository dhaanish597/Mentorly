import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { InterviewDefaults } from '../features/settings/InterviewDefaults';
import { resetInterviewPreferences } from '../features/interview/preferences';

const INTERVIEW_KEY = 'viva.interview-preferences.v1';
const MICROPHONE_KEY = 'viva.microphone-input.v1';
const fetchSpy = vi.fn();
const captureSpy = vi.fn();
const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');

function openSettings(category: string): void {
  history.replaceState({}, '', `/settings?category=${category}`);
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  fetchSpy.mockReset();
  captureSpy.mockReset();
  vi.stubGlobal('fetch', fetchSpy);
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: vi.fn().mockResolvedValue([
        { kind: 'audioinput', deviceId: 'test-microphone', label: 'Test microphone' },
      ]),
      getUserMedia: captureSpy,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalMediaDevices) Object.defineProperty(navigator, 'mediaDevices', originalMediaDevices);
  else Reflect.deleteProperty(navigator, 'mediaDevices');
});

describe('settings continuation integration', () => {
  it('clears a read-denial alert after storage recovers and defaults save successfully', () => {
    const getItem = Storage.prototype.getItem;
    let denied = true;
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key: string) {
      if (key === INTERVIEW_KEY && denied) throw new Error('read denied');
      return getItem.call(this, key);
    });
    render(<InterviewDefaults onSaved={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveTextContent('could not be read');
    denied = false;
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Default interview duration' }), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' }));
    expect(JSON.parse(localStorage.getItem(INTERVIEW_KEY)!)).toMatchObject({ duration_minutes: 30 });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reset clears stale duration validation and does not revive it after editing', () => {
    render(<InterviewDefaults onSaved={vi.fn()} />);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Default interview duration' }), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Use a whole number');
    act(() => { expect(resetInterviewPreferences()).toBe(true); });
    expect(screen.getByRole('spinbutton', { name: 'Default interview duration' })).toHaveValue(15);
    expect(screen.getByRole('spinbutton', { name: 'Default interview duration' })).not.toHaveAttribute('aria-invalid', 'true');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Default interview duration' }), { target: { value: '20' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('includes interview defaults in keyboard category navigation', () => {
    openSettings('learning');
    render(<ProductApp />);
    const learning = screen.getByRole('link', { name: 'Learning' });
    learning.focus();
    fireEvent.keyDown(learning, { key: 'ArrowDown' });
    expect(screen.getByRole('link', { name: 'Interview defaults' })).toHaveFocus();
    expect(screen.getByRole('heading', { name: 'Interview defaults' })).toBeInTheDocument();
  });

  it('reports a partial reset failure without claiming all preferences reset', () => {
    localStorage.setItem(INTERVIEW_KEY, JSON.stringify({ type: 'cs', difficulty: 'advanced', duration_minutes: 25 }));
    openSettings('advanced');
    render(<ProductApp />);
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('removal denied'); });
    fireEvent.click(screen.getByRole('button', { name: 'Reset preferences' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reset' }));
    expect(screen.getByRole('alert')).toHaveTextContent('could not be saved');
    expect(screen.queryByText(/Preferences reset\./)).not.toBeInTheDocument();
  });

  it('exposes interview defaults without creating a workspace or requesting media', () => {
    openSettings('interview');
    render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'Interview defaults' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Default interview type' })).toHaveValue('dsa');
    expect(screen.getByRole('combobox', { name: 'Default interview difficulty' })).toHaveValue('beginner');
    expect(screen.getByRole('spinbutton', { name: 'Default interview duration' })).toHaveValue(15);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(captureSpy).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
  });

  it('persists only the interview defaults and restores them after remount', () => {
    openSettings('interview');
    const view = render(<ProductApp />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Default interview type' }), { target: { value: 'cs' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Default interview difficulty' }), { target: { value: 'advanced' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Default interview duration' }), { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' }));
    expect(JSON.parse(localStorage.getItem(INTERVIEW_KEY)!)).toEqual({ type: 'cs', difficulty: 'advanced', duration_minutes: 25 });
    expect(screen.getByText('Saved on this device')).toBeInTheDocument();
    view.unmount();
    render(<ProductApp />);
    expect(screen.getByRole('combobox', { name: 'Default interview type' })).toHaveValue('cs');
    expect(screen.getByRole('spinbutton', { name: 'Default interview duration' })).toHaveValue(25);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('does not persist an empty or fractional duration', () => {
    openSettings('interview');
    render(<ProductApp />);
    const duration = screen.getByRole('spinbutton', { name: 'Default interview duration' });
    fireEvent.change(duration, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' }));
    expect(localStorage.getItem(INTERVIEW_KEY)).toBeNull();
    fireEvent.change(duration, { target: { value: '5.5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' }));
    expect(localStorage.getItem(INTERVIEW_KEY)).toBeNull();
    expect(screen.queryByText('Saved on this device')).not.toBeInTheDocument();
  });

  it('reports denied interview persistence instead of a successful save', () => {
    openSettings('interview');
    render(<ProductApp />);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied'); });
    fireEvent.click(screen.getByRole('button', { name: 'Save interview defaults' }));
    expect(screen.getByRole('alert')).toHaveTextContent('could not be saved');
    expect(screen.queryByText('Saved on this device')).not.toBeInTheDocument();
  });

  it('reset removes new preferences while preserving existing workspace and draft storage', () => {
    localStorage.setItem(INTERVIEW_KEY, JSON.stringify({ type: 'cs', difficulty: 'advanced', duration_minutes: 25 }));
    localStorage.setItem(MICROPHONE_KEY, JSON.stringify('test-microphone'));
    localStorage.setItem('unrelated-draft', 'retain-this-draft');
    sessionStorage.setItem('viva-studio-tab-v1', 'retain-this-workspace');
    openSettings('advanced');
    render(<ProductApp />);
    fireEvent.click(screen.getByRole('button', { name: 'Reset preferences' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reset' }));
    expect(localStorage.getItem(INTERVIEW_KEY)).toBeNull();
    expect(localStorage.getItem(MICROPHONE_KEY)).toBeNull();
    expect(localStorage.getItem('unrelated-draft')).toBe('retain-this-draft');
    expect(sessionStorage.getItem('viva-studio-tab-v1')).toBe('retain-this-workspace');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(captureSpy).not.toHaveBeenCalled();
  });

  it('enumerates and saves a microphone selection without starting capture', async () => {
    openSettings('voice');
    render(<ProductApp />);
    await screen.findByRole('option', { name: 'Test microphone' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Microphone input' }), { target: { value: 'test-microphone' } });
    await waitFor(() => expect(localStorage.getItem(MICROPHONE_KEY)).toBe(JSON.stringify('test-microphone')));
    expect(captureSpy).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Check microphone' })).toBeInTheDocument();
  });
});
