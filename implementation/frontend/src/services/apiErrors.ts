/** Read error envelopes without rendering validation input or retrying requests. */
function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export async function readApiError(response: Response, fallback?: string): Promise<string> {
  const data: unknown = await response.json().catch(() => null);
  const envelope = record(data);
  const candidates = [envelope?.detail, envelope?.message, record(envelope?.error)?.message];
  const message = candidates.find((value): value is string => typeof value === 'string' && !!value.trim());
  if (response.status === 404 && message?.trim().toLowerCase() === 'not found') {
    return 'The connected backend does not provide this API endpoint. Restart the backend to load the current API, then retry.';
  }
  if (message) return message;
  if (response.status === 422) return 'The request was rejected (HTTP 422). Check your inputs and try again.';
  return fallback ?? `The API request failed (HTTP ${response.status}). Check the backend connection and retry.`;
}
