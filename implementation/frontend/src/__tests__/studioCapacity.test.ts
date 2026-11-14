import { describe, expect, it } from 'vitest';
import { calculateCapacity } from '../studioCapacity';
describe('capacity estimates', () => {
  it('calculates only estimates supported by nonnegative numeric inputs', () => {
    const result = calculateCapacity({read_rps:1000,miss_fraction:.1,requests_per_second:20,latency_seconds:.25,bytes_per_request:-1});
    expect(result['Origin reads (requests/s)']).toBe(100);
    expect(result['Concurrent requests']).toBe(5);
    expect(result['Bandwidth (bytes/s)']).toBeNull();
    expect(result['Retry storage (bytes)']).toBeNull();
  });
});
