// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { developmentApiTarget } from '../../dev/backendRouting';

describe('explicit local backend recovery', () => {
  it('proxies built previews as well as development without accepting arbitrary hosts', async () => {
    const { default: config } = await import('../../vite.config');
    const proxy = { '/api': expect.objectContaining({ target: expect.any(String), changeOrigin: true, ws: true }) };
    expect(config).toMatchObject({ server: { proxy }, preview: { proxy } });
    expect(config).not.toMatchObject({ server: { allowedHosts: true } });
  });
  const replacements = { 'http://127.0.0.1:8026': 'http://127.0.0.1:8028', 'http://127.0.0.1:8020': 'http://127.0.0.1:8029' };
  it('routes managed stale API origins to their database-preserving replacements', () => {
    expect(developmentApiTarget('http://127.0.0.1:8026', replacements)).toBe('http://127.0.0.1:8028');
    expect(developmentApiTarget('http://127.0.0.1:8020', replacements)).toBe('http://127.0.0.1:8029');
  });
  it('keeps the already updated server and custom deployments untouched', () => {
    expect(developmentApiTarget('http://127.0.0.1:8027', replacements)).toBe('http://127.0.0.1:8027');
    expect(developmentApiTarget('https://example.org', replacements)).toBe('https://example.org');
  });
  it('never forwards authenticated local API requests to an external recovery origin', () => {
    expect(() => developmentApiTarget('http://127.0.0.1:8026', { 'http://127.0.0.1:8026':'https://example.org' })).toThrow(/loopback/);
    expect(() => developmentApiTarget('http://127.0.0.1:8026', { 'http://127.0.0.1:8026':'http://user:secret@127.0.0.1:8028' })).toThrow(/loopback/);
  });
});
