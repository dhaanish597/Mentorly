import { beforeEach, describe, expect, it } from 'vitest';
import { webcrypto } from 'node:crypto';
import { exportDraftBackup, importDraftBackup } from '../state/draftBackup';
import { DEFAULT_PRODUCT_STATE, loadProductState, saveProductState } from '../state/productState';

describe('versioned private draft backups', () => {
  beforeEach(() => { localStorage.clear(); Object.defineProperty(crypto, 'subtle', { value: webcrypto.subtle, configurable: true }); });
  it('restores after storage loss without exporting bearer capabilities', async () => {
    saveProductState({ ...DEFAULT_PRODUCT_STATE, drafts: { 'exercise::v1': { sourceCode: 'return 3', transcript: 'Three', updatedAt: 20, status: 'Draft' } } });
    sessionStorage.setItem('vcc-tab-sessions', JSON.stringify({ secret: 'bearer-must-not-export' }));
    const backup = await exportDraftBackup();
    expect(backup).not.toContain('bearer-must-not-export');
    localStorage.clear();
    expect(await importDraftBackup(backup)).toEqual({ restored: 1, skipped: 0 });
    expect(loadProductState().drafts['exercise::v1'].sourceCode).toBe('return 3');
  });
  it('preserves newer drafts and rejects tampered/unknown/prototype fields', async () => {
    saveProductState({ ...DEFAULT_PRODUCT_STATE, drafts: { 'exercise::v1': { sourceCode: 'old', transcript: '', updatedAt: 10, status: 'Draft' } } });
    const backup = await exportDraftBackup();
    saveProductState({ ...DEFAULT_PRODUCT_STATE, drafts: { 'exercise::v1': { sourceCode: 'new', transcript: '', updatedAt: 30, status: 'Draft' } } });
    expect(await importDraftBackup(backup)).toEqual({ restored: 0, skipped: 1 });
    expect(loadProductState().drafts['exercise::v1'].sourceCode).toBe('new');
    await expect(importDraftBackup(backup.replace('old', 'tampered'))).rejects.toThrow('integrity');
    const raw = JSON.parse(backup); raw.workspace_token = 'not-allowed';
    await expect(importDraftBackup(JSON.stringify(raw))).rejects.toThrow('format');
    await expect(importDraftBackup(backup.replace('exercise::v1', '__proto__'))).rejects.toThrow('record');
  });
});
