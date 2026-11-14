import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductApp from '../ProductApp';
import { ProblemLibrary } from '../components/ProblemLibrary';
import { AccessibleTabs, ResizeHandle, SettingsDialog, WorkspaceHeader } from '../components/WorkspaceChrome';
import { apiClient } from '../services/apiClient';
import { DEFAULT_PRODUCT_STATE, draftKey, problemUrl, readRoute } from '../state/productState';
import type { ExerciseMetadata } from '../types/api';

const spec = { spec_version: 'v1', label: 'Positive values', constraints_summary: ['Positive values only'], min_length: 0, max_length: 20, min_value: 0, max_value: 100, sorted_required: false };
const problems: ExerciseMetadata[] = [
  { exercise_id: 'ex1_shortest_subarray', title: 'Shortest window', function_name: 'solve', comparator: 'strict_structural', catalog_status: 'READY', description: 'Find the shortest window.', difficulty: 'intermediate', collection: 'Arrays & windows', core_concepts: ['Sliding window'], starter_code: 'def solve(): pass', default_spec_version: 'v1', spec_versions: [spec, { ...spec, spec_version: 'v2', label: 'Negatives allowed' }] },
  { exercise_id: 'ex19_first_unique_char', title: 'Unique character', function_name: 'unique', comparator: 'strict_structural', catalog_status: 'READY', description: 'Find the first unique character.', difficulty: 'beginner', collection: 'Strings', core_concepts: ['Hash map'], starter_code: 'def unique(): pass', default_spec_version: 'v1', spec_versions: [spec] },
];
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); history.replaceState({}, '', '/'); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });
function catalog() { return vi.spyOn(apiClient, 'getExercises').mockResolvedValue(problems); }

// These are component/contract doubles, not provider, sandbox, or browser-layout evidence.
describe('real-data product journeys', () => {
  it('resumes the newest known problem specification and ignores orphaned drafts', async () => {
    history.replaceState({}, '', '/dashboard'); catalog();
    localStorage.setItem('vcc-product-v1', JSON.stringify({ drafts: {
      [draftKey(problems[0].exercise_id, 'v1')]: { sourceCode: 'old', transcript: '', status: 'Draft', updatedAt: 1 },
      [draftKey(problems[0].exercise_id, 'v2')]: { sourceCode: 'new', transcript: '', status: 'In progress', updatedAt: 2 },
      unknown: { sourceCode: 'orphan', transcript: '', status: 'Draft', updatedAt: 3 },
    } }));
    render(<ProductApp />);
    const resume = await screen.findByRole('link', { name: 'Resume practice' });
    expect(resume).toHaveAttribute('href', problemUrl(problems[0].exercise_id, 'v2'));
    expect(screen.getByRole('heading', { name: 'Continue Shortest window' })).toBeInTheDocument();
    expect(screen.getByText('Negatives allowed')).toBeInTheDocument();
    expect(screen.queryByText('orphan')).not.toBeInTheDocument();
  });
  it('shows all actual learning collections and their canonical destinations', async () => {
    history.replaceState({}, '', '/paths'); catalog(); render(<ProductApp />);
    await screen.findByRole('heading', { name: 'Arrays & windows' });
    expect(screen.getByRole('heading', { name: 'Strings' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Explore collection' }).map(a => a.getAttribute('href'))).toEqual(['/paths/Arrays%20%26%20windows', '/paths/Strings']);
    expect(screen.getAllByText('1 available problems')).toHaveLength(2);
  });
  it('opens a specific collection from an encoded path without changing exercise IDs', async () => {
    history.replaceState({}, '', '/paths/Arrays%20%26%20windows'); catalog(); render(<ProductApp />);
    const open = await screen.findByRole('link', { name: 'Open problem' });
    expect(open).toHaveAttribute('href', problemUrl(problems[0].exercise_id, 'v1'));
    expect(screen.queryByRole('heading', { name: 'Unique character' })).not.toBeInTheDocument();
  });
  it.each(['/paths/Unknown', '/paths/%'])('recovers missing/malformed collection %s with a paths link', async path => {
    history.replaceState({}, '', path); catalog(); render(<ProductApp />);
    await screen.findByText('No collection found.');
    expect(screen.getByRole('link', { name: 'View learning paths' })).toHaveAttribute('href', '/paths');
  });
  it('retries a failed dashboard catalog request and renders actual collections', async () => {
    history.replaceState({}, '', '/dashboard');
    const fetcher = vi.spyOn(apiClient, 'getExercises').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(problems);
    render(<ProductApp />);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await screen.findByRole('heading', { name: 'Arrays & windows' });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('offers an explicit recovery route for unavailable pages', () => {
    history.replaceState({}, '', '/does-not-exist'); render(<ProductApp />);
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to your workspace' })).toHaveAttribute('href', '/dashboard');
  });
  it('removes the appearance listener when the product page unmounts', () => {
    const add = vi.fn(); const remove = vi.fn();
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: add, removeEventListener: remove }));
    const view = render(<ProductApp />);
    expect(document.documentElement.dataset.theme).toBe('light');
    view.unmount(); expect(remove).toHaveBeenCalledWith('change', add.mock.calls[0][1]);
  });
});

describe('library discovery controls preserve URL state', () => {
  function library(overrides: Partial<typeof DEFAULT_PRODUCT_STATE> = {}) {
    const route = readRoute(new URL('https://viva.test/library'));
    const change = vi.fn(); const open = vi.fn(); const bookmark = vi.fn();
    render(<ProblemLibrary exercises={problems} product={{ ...DEFAULT_PRODUCT_STATE, ...overrides }} route={route} onRouteChange={change} onOpen={open} onBookmark={bookmark} />);
    return { route, change, open, bookmark };
  }
  it.each([
    ['Search problems', 'hash', 'query'], ['Difficulty', 'beginner', 'difficulty'],
    ['Topic', 'Sliding window', 'topic'], ['Progress', 'draft', 'progress'], ['Sort', 'title', 'sort'],
  ])('updates %s without discarding other filters', (label, value, key) => {
    const { route, change } = library();
    if (['Topic', 'Progress', 'Sort'].includes(label)) fireEvent.click(screen.getByText('More filters'));
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect(change).toHaveBeenCalledWith({ ...route, [key]: value });
  });
  it('toggles saved-only filtering and uses one bookmarked problem action', () => {
    const { route, change, bookmark } = library({ bookmarks: [problems[0].exercise_id] });
    fireEvent.click(screen.getByText('More filters'));
    fireEvent.click(screen.getByRole('button', { name: 'Bookmarks' }));
    expect(change).toHaveBeenCalledWith({ ...route, bookmarked: true });
    fireEvent.click(screen.getByRole('button', { name: `Remove bookmark for ${problems[0].title}` }));
    expect(bookmark).toHaveBeenCalledWith(problems[0].exercise_id);
  });
  it('opens and resumes the latest draft specification, not the default version', () => {
    const { open } = library({ drafts: {
      [draftKey(problems[0].exercise_id, 'v1')]: { sourceCode: 'old', transcript: '', status: 'Draft', updatedAt: 1 },
      [draftKey(problems[0].exercise_id, 'v2')]: { sourceCode: 'new', transcript: '', status: 'In progress', updatedAt: 2 },
    } });
    fireEvent.click(screen.getByRole('link', { name: 'Shortest window' }));
    expect(open).toHaveBeenLastCalledWith(problems[0].exercise_id, 'v2');
    fireEvent.click(screen.getByRole('link', { name: 'Resume Shortest window' }));
    expect(open).toHaveBeenCalledTimes(2);
  });
  it('explains a genuinely empty catalog rather than a failed search', () => {
    render(<ProblemLibrary exercises={[]} product={DEFAULT_PRODUCT_STATE} route={readRoute(new URL('https://viva.test/library'))} onRouteChange={vi.fn()} onOpen={vi.fn()} onBookmark={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'No problems available yet' })).toBeInTheDocument();
    expect(screen.getByText('Showing 0 of 0 problems')).toBeInTheDocument();
  });
});

describe('keyboard and modal controls', () => {
  it.each([
    ['horizontal', 'ArrowUp', 240], ['horizontal', 'ArrowDown', 280],
    ['vertical', 'ArrowLeft', 240], ['vertical', 'ArrowRight', 280],
    ['vertical', 'Enter', 300], ['vertical', 'Home', 300],
  ] as const)('resizes %s using %s', (orientation, key, expected) => {
    const change = vi.fn();
    render(<ResizeHandle label="Resize panel" value={260} min={240} max={480} defaultValue={300} orientation={orientation} onChange={change} />);
    fireEvent.keyDown(screen.getByRole('separator', { name: 'Resize panel' }), { key });
    expect(change).toHaveBeenCalledWith(expected);
  });
  it('ignores unrelated keys and clamps reversed horizontal resizing', () => {
    const change = vi.fn();
    render(<ResizeHandle label="Resize results" value={240} min={240} max={480} defaultValue={300} orientation="horizontal" reverse onChange={change} />);
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'Escape' }); expect(change).not.toHaveBeenCalled();
    fireEvent.keyDown(handle, { key: 'ArrowDown' }); expect(change).toHaveBeenCalledWith(240);
    fireEvent.doubleClick(handle); expect(change).toHaveBeenLastCalledWith(300);
  });
  it.each([['ArrowLeft', 'Results'], ['Home', 'Code'], ['End', 'Results'], ['ArrowRight', 'Coach']] as const)('selects and focuses %s tabs', (key, expected) => {
    const select = vi.fn();
    render(<AccessibleTabs label="Views" tabs={['Code', 'Coach', 'Results']} selected="Code" onSelect={select} controls={{ Code: 'code', Coach: 'coach', Results: 'results' }} />);
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Code' }), { key });
    expect(select).toHaveBeenCalledWith(expected);
    expect(screen.getByRole('tab', { name: expected })).toHaveFocus();
  });
  it('keeps modal focus inside and restores the launch button on unmount', () => {
    const launch = document.createElement('button'); document.body.appendChild(launch); launch.focus();
    const close = vi.fn(); const view = render(<SettingsDialog onClose={close}><button>Last setting</button></SettingsDialog>);
    const first = screen.getByRole('button', { name: 'Close settings' }); const last = screen.getByRole('button', { name: 'Last setting' });
    last.focus(); fireEvent.keyDown(last, { key: 'Tab' }); expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true }); expect(last).toHaveFocus();
    fireEvent.click(last); expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('dialog').parentElement!); expect(close).toHaveBeenCalledTimes(1);
    view.unmount(); expect(launch).toHaveFocus(); launch.remove();
  });
  it('uses local header actions without decorative controls', () => {
    const library = vi.fn(); const settings = vi.fn(); const toggle = vi.fn();
    const view = render(<WorkspaceHeader productName="VIVA" shortName="V" title="A problem" isLibrary={false} collapsed={false} onLibrary={library} onSettings={settings} onToggleCoach={toggle} />);
    fireEvent.click(screen.getByRole('link', { name: 'VIVA library' }));
    fireEvent.click(screen.getByRole('button', { name: 'Problem library' }));
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Hide coach' }));
    expect(library).toHaveBeenCalledTimes(2); expect(settings).toHaveBeenCalledOnce(); expect(toggle).toHaveBeenCalledOnce();
    view.rerender(<WorkspaceHeader productName="VIVA" shortName="V" isLibrary collapsed onLibrary={library} onSettings={settings} onToggleCoach={toggle} />);
    expect(screen.queryByRole('button', { name: 'Show coach' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Problem library' })).toHaveAttribute('aria-current', 'page');
  });
});
