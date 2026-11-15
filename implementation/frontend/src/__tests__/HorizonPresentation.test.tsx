import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import ProductApp from '../ProductApp';
import { apiClient } from '../services/apiClient';

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });
describe('Horizon presentation with real VIVA destinations', () => {
  it('restores the mentor illustration and complete landing composition', () => {
    history.replaceState({}, '', '/');
    render(<ProductApp />);
    expect(screen.getByAltText('Your Mentorly mentor').getAttribute('src')).toBe('/mentor/mentor.png');
    expect(screen.getByRole('heading', { name: 'Three moves, every time' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Three ways to think deeper' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /Explore problems/ }).getAttribute('href')).toBe('/library');
    expect(screen.queryByText(/earn XP/)).toBeNull();
  });
  it('uses one shared app navigation with a real studio destination', async () => {
    history.replaceState({}, '', '/dashboard');
    vi.spyOn(apiClient, 'getExercises').mockResolvedValue([]);
    render(<ProductApp />);
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Design studio' }).getAttribute('href')).toBe('/studio');
    expect(screen.getByAltText('Your Mentorly mentor')).toBeTruthy();
    await screen.findByText('No saved practice yet. Your work will appear here as you begin.');
  });
});
