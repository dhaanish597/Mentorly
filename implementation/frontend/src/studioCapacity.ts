/** Return only computable estimates; missing and invalid inputs remain unknown. */
export function calculateCapacity(a: Record<string, unknown>): Record<string, number | null> {
  const value = (key: string) => typeof a[key] === 'number' && Number.isFinite(a[key]) && (a[key] as number) >= 0 && (key !== 'miss_fraction' || (a[key] as number) <= 1) ? a[key] as number : null;
  const multiply = (...keys: string[]) => { const values = keys.map(value); if (values.some(v => v === null)) return null; const result = values.reduce<number>((acc, n) => acc * (n as number), 1); return Number.isFinite(result) ? result : null; };
  return { 'Write fan-out (operations/s)': multiply('event_rate_per_second','recipients_per_event'), 'Origin reads (requests/s)': multiply('read_rps','miss_fraction'), 'Retry storage (bytes)': multiply('events_per_second','retry_window_seconds','bytes_per_event','replicas'), 'Bandwidth (bytes/s)': multiply('requests_per_second','bytes_per_request'), 'Concurrent requests': multiply('requests_per_second','latency_seconds') };
}
