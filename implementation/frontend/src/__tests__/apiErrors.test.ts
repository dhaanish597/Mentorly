import { afterEach, describe, expect, it, vi } from 'vitest';
import { readApiError } from '../services/apiErrors';
import { fetchExercises, retryExecution } from '../services/apiClient';
import { studioRequest } from '../studioApi';
import type { RevisionRef } from '../types/api';

afterEach(() => vi.unstubAllGlobals());
const response = (data: unknown, status: number) => new Response(JSON.stringify(data), { status });
const revision: RevisionRef = { session_id: 'missing', exercise_id: 'ex2_binary_search', spec_version: 'v1_sorted_with_duplicates', code_version_id: 1, code_hash: 'hash', turn_generation: 1 };

describe('honest API failure reporting', () => {
  it('distinguishes a missing route on a stale backend from a missing session', async () => {
    const message = await readApiError(response({ detail: 'Not Found' }, 404));
    expect(message).toMatch(/backend/i);
    expect(message).toMatch(/restart/i);
    expect(message).not.toBe('Not Found');
    expect(await readApiError(response({ detail: 'Session not found' }, 404))).toBe('Session not found');
  });
  it.each([
    [{ detail: 'Workspace expired' }, 'Workspace expired'],
    [{ message: 'Provider unavailable' }, 'Provider unavailable'],
    [{ error: { message: 'Execution unavailable' } }, 'Execution unavailable'],
  ])('preserves actionable backend errors', async (data, message) => {
    expect(await readApiError(response(data, 503))).toBe(message);
  });
  it('does not render validation objects or their submitted input', async () => {
    const message = await readApiError(response({ detail: [{ msg: 'Invalid', input: 'private-input' }] }, 422));
    expect(message).toContain('422');
    expect(message).not.toContain('private-input');
    expect(message).not.toContain('[object Object]');
  });
  it.each([null, [], { detail: {} }, { error: null }, { message: 23 }])('handles incomplete error envelopes', async data => {
    expect(await readApiError(response(data, 500), 'Continue with text.')).toBe('Continue with text.');
  });
  it('handles non-JSON proxy failures without treating them as missing features', async () => {
    const message = await readApiError(new Response('<html>Bad gateway</html>', { status: 502 }));
    expect(message).toContain('502');
    expect(message).not.toContain('<html>');
    expect(message).not.toMatch(/restart/i);
  });
  it('reports stale curriculum routes through the shared workspace client', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ detail: 'Not Found' }, 404));
    vi.stubGlobal('fetch', fetch);
    await expect(studioRequest('/learning/catalog')).rejects.toThrow(/restart/i);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('reports missing metadata without automatic retries', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ detail: 'Not Found' }, 404));
    vi.stubGlobal('fetch', fetch);
    await expect(fetchExercises()).rejects.toThrow(/restart/i);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('never repeats a mutation to repair an API version mismatch', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ detail: 'Not Found' }, 404));
    vi.stubGlobal('fetch', fetch);
    await expect(retryExecution('missing', 'turn', { revision })).rejects.toThrow(/restart/i);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
