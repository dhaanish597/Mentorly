import { afterEach, describe, expect, it, vi } from 'vitest';
import { confirmTurnClaim, registerSessionToken, requestVoiceOrientation, retryExecution, verifyRepair } from '../services/apiClient';
import type { RevisionRef } from '../types/api';
const revision: RevisionRef = { session_id: 'client-test', exercise_id: 'ex1_shortest_subarray', spec_version: 'v1_positive_only', code_version_id: 2, code_hash: 'hash', turn_generation: 4 };
afterEach(() => { vi.unstubAllGlobals(); });
describe('Repair and confirmation HTTP contracts', () => {
  it('requests only server-owned orientation text and preserves abort and playback identity', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(new Uint8Array([82, 73, 70, 70]), {
      headers: { 'Content-Type': 'audio/wav', 'X-Playback-ID': 'orientation-playback' },
    }));
    vi.stubGlobal('fetch', fetch);
    registerSessionToken('client-test', 'session-secret');
    const controller = new AbortController();
    const result = await requestVoiceOrientation('client-test', revision, 'introduction', controller.signal);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith('/api/v1/sessions/client-test/speech/introduction', expect.objectContaining({
      method: 'POST', signal: controller.signal, body: JSON.stringify({ revision }),
      headers: expect.objectContaining({ Authorization: 'Bearer session-secret' }),
    }));
    expect(result.audio.byteLength).toBe(4);
    expect(result.playbackId).toBe('orientation-playback');
  });
  it('surfaces voice provider failure without retrying or substituting audio', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Voice unavailable. Use text.' }), { status: 503 }));
    vi.stubGlobal('fetch', fetch);
    await expect(requestVoiceOrientation('client-test', revision, 'test-voice')).rejects.toThrow('Voice unavailable. Use text.');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('sends authenticated repair options and retries the exact turn without learner execution', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', fetch);
    registerSessionToken('client-test', 'session-secret');
    const body = { revision, prior_artifact_id: 'failure', run_curated_suite: true, generated_cases_target: 100 };
    await verifyRepair('client-test', body);
    expect(fetch).toHaveBeenNthCalledWith(1, '/api/v1/sessions/client-test/verify', expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Authorization: 'Bearer session-secret', 'Content-Type': 'application/json', 'X-Idempotency-Key': expect.any(String) }), body: JSON.stringify(body) }));
    await retryExecution('client-test', 'unavailable-turn', { revision });
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/v1/sessions/client-test/turns/unavailable-turn/retry-execution', expect.objectContaining({ method: 'POST', body: JSON.stringify({ revision }) }));
  });
  it('sends capture identity for explanation confirmation without a challenge or numeric claim', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    const body = { revision, capture_attempt_id: 6, claim: { claim_type: 'INVARIANT_OR_MECHANISM_CLAIM' as const, mechanism_summary: 'window grows', extraction_method: 'DETERMINISTIC' as const } };
    await confirmTurnClaim('client-test', 'explanation-turn', body);
    expect(fetch).toHaveBeenCalledWith('/api/v1/sessions/client-test/turns/explanation-turn/confirm-claim', expect.objectContaining({ body: JSON.stringify(body) }));
  });
  it('surfaces verifier availability errors without creating successful artifacts', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: 'Accepted worker unavailable' } }), { status: 503 })));
    await expect(verifyRepair('client-test', { revision, run_curated_suite: true, generated_cases_target: 100 })).rejects.toThrow('Accepted worker unavailable');
  });
});
