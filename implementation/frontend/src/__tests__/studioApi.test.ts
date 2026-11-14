import { afterEach, describe, expect, it, vi } from 'vitest';
import { readStudioTab, studioRequest, writeStudioTab } from '../studioApi';
afterEach(() => { sessionStorage.clear(); vi.unstubAllGlobals(); });
describe('studio capability client', () => {
  it('sends session capability only in authorization and generates a mutation key', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({revision: 1}), {status:200,headers:{'Content-Type':'application/json'}}));
    vi.stubGlobal('fetch', fetcher);
    await studioRequest('/studio/sessions/s/diagram', {method:'PUT',token:'secret-token',body:{base_revision:0,nodes:[],edges:[],assumptions:{}}});
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe('/api/v1/studio/sessions/s/diagram');
    expect(options.headers.Authorization).toBe('Bearer secret-token');
    expect(options.headers['X-Idempotency-Key']).toBeTruthy();
    expect(JSON.stringify(options.body)).not.toContain('secret-token');
  });
  it('reports conflicts without replacing the server status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'Revision conflict'}), {status:409})));
    await expect(studioRequest('/studio/sessions/s/diagram',{method:'PUT',token:'x',body:{}})).rejects.toMatchObject({status:409,message:'Revision conflict'});
  });
  it('keeps capabilities in tab storage and handles malformed records', () => {
    writeStudioTab({workspace:{id:'id',token:'secret'},sessions:[]});
    expect(readStudioTab().workspace?.id).toBe('id');
    expect(localStorage.getItem('viva-studio-tab-v1')).toBeNull();
    sessionStorage.setItem('viva-studio-tab-v1','{');
    expect(readStudioTab()).toEqual({sessions:[]});
  });
});
