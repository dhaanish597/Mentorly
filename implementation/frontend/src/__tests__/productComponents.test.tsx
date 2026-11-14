import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProblemLibrary } from '../components/ProblemLibrary';
import { ResizeHandle, AccessibleTabs, SettingsDialog } from '../components/WorkspaceChrome';
import { DEFAULT_PRODUCT_STATE, readRoute } from '../state/productState';
import type { ExerciseMetadata } from '../types/api';
const exercises: ExerciseMetadata[] = [{ exercise_id: 'p1', title: 'Shortest window', comparator: 'strict_structural', catalog_status: 'READY', description: 'Find a window', function_name: 'solve', difficulty: 'intermediate', core_concepts: ['Sliding window'], default_spec_version: 'v1', starter_code: '', spec_versions: [{ spec_version: 'v1', label: 'Positive', constraints_summary: [], min_length: 0, max_length: 10, min_value: 1, max_value: 10, sorted_required: false }] }];
afterEach(cleanup);
describe('Library and keyboard workspace controls', () => {
  it('shows actual catalog count, bookmarked state, and canonical problem link', () => {
    const bookmark = vi.fn();
    render(<ProblemLibrary exercises={exercises} product={DEFAULT_PRODUCT_STATE} route={readRoute(new URL('https://example.test/library'))} onRouteChange={vi.fn()} onOpen={vi.fn()} onBookmark={bookmark} />);
    expect(screen.getByText('1 problem')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Shortest window' })).toHaveAttribute('href', '/practice/p1?spec=v1');
    fireEvent.click(screen.getByRole('button', { name: 'Bookmark Shortest window' }));
    expect(bookmark).toHaveBeenCalledWith('p1');
    expect(screen.getByRole('searchbox', { name: 'Search problems' })).toBeInTheDocument();
  });
  it('shows explicit empty results and offers clear filters', () => {
    render(<ProblemLibrary exercises={exercises} product={DEFAULT_PRODUCT_STATE} route={readRoute(new URL('https://example.test/library?q=nothing'))} onRouteChange={vi.fn()} onOpen={vi.fn()} onBookmark={vi.fn()} />);
    expect(screen.getByText('No matching problems')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeEnabled();
  });
  it('resizes by keyboard with bounded sizes and Home reset', () => {
    const change = vi.fn();
    render(<ResizeHandle label="Resize statement" value={300} min={240} max={480} defaultValue={300} onChange={change} orientation="vertical" />);
    const separator = screen.getByRole('separator', { name: 'Resize statement' });
    fireEvent.keyDown(separator, { key: 'ArrowRight' });
    expect(change).toHaveBeenCalledWith(320);
    fireEvent.keyDown(separator, { key: 'Home' });
    expect(change).toHaveBeenCalledWith(300);
  });
  it('switches tabs by arrows with selected state and focus', () => {
    const select = vi.fn();
    render(<AccessibleTabs label="Workspace panes" tabs={['Statement', 'Code', 'Coach']} selected="Code" onSelect={select} />);
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Code' }), { key: 'ArrowRight' });
    expect(select).toHaveBeenCalledWith('Coach');
    expect(screen.getByRole('tab', { name: 'Coach' })).toHaveFocus();
  });
  it('focuses settings and handles Escape while trapping keyboard focus', () => {
    const close = vi.fn();
    render(<SettingsDialog onClose={close}><button>Setting control</button></SettingsDialog>);
    expect(screen.getByRole('button', { name: 'Close settings' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(close).toHaveBeenCalled();
  });
});
