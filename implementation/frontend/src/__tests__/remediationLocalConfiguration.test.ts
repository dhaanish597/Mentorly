import { describe, expect, it } from 'vitest';
import { localConfiguration } from '../../dev/localConfiguration';

describe('canonical local routing', () => {
  it('uses the same 8020/5173 identity as Python startup', () => {
    expect(localConfiguration({})).toEqual({ apiTarget: 'http://127.0.0.1:8020', frontendPort: 5173 });
    expect(localConfiguration({ VCC_BACKEND_HOST: 'localhost', VCC_BACKEND_PORT: '8037', VCC_FRONTEND_PORT: '5191' })).toEqual({ apiTarget: 'http://localhost:8037', frontendPort: 5191 });
  });
  it('rejects malformed port/host overrides and preserves explicit legacy target', () => {
    expect(() => localConfiguration({ VCC_FRONTEND_PORT: '8020/x' })).toThrow();
    expect(() => localConfiguration({ VCC_BACKEND_HOST: 'private.invalid' })).toThrow();
    expect(localConfiguration({ VCC_PREVIEW_API_TARGET: 'http://127.0.0.1:8000' }).apiTarget).toBe('http://127.0.0.1:8000');
  });
});
