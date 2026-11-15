const LABELS: Readonly<Record<string, string>> = {
  MODEL_DISABLED: 'Model feedback is disabled.', MODEL_NOT_CONFIGURED: 'Model feedback is not configured.',
  MODEL_TIMEOUT: 'Model feedback timed out.', MODEL_RATE_LIMITED: 'Model feedback capacity or budget is exhausted.',
  MODEL_INVALID_RESPONSE: 'The model response could not be validated.', MODEL_UNAVAILABLE: 'The model service is unavailable.',
  MODEL_ASSISTED: 'Model-assisted feedback.', DETERMINISTIC_FALLBACK: 'Deterministic feedback.',
};
export function modelAvailabilityLabel(status: string): string {
  return LABELS[status] ?? 'Feedback availability is unknown.';
}
