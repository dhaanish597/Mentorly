export type PredictionScalar = number | boolean | string;
export type PredictionValue = PredictionScalar | PredictionScalar[];
export type OutputKind = 'integer' | 'boolean' | 'string' | 'list';
const MAX_STRING_LENGTH = 256;
const MAX_LIST_LENGTH = 128;
function isScalar(value: unknown): value is PredictionScalar {
  return typeof value === 'boolean' || (typeof value === 'string' && value.length <= MAX_STRING_LENGTH) || (typeof value === 'number' && Number.isSafeInteger(value));
}
export function parsePrediction(text: string, kind?: OutputKind): PredictionValue {
  let value: unknown;
  const trimmed = text.trim();
  if (/^-?\d+(?:\.\d+|[eE][+-]?\d+)$/.test(trimmed)) throw new Error('Enter an exact integer without decimal or exponent notation.');
  try { value = JSON.parse(trimmed); }
  catch { throw new Error('Enter an exact integer, true/false, a quoted string, or a scalar list using JSON syntax.'); }
  if (typeof value === 'string' && value.length > MAX_STRING_LENGTH) throw new Error('String predictions are limited to 256 characters.');
  if (Array.isArray(value) && value.length > MAX_LIST_LENGTH) throw new Error('List predictions are limited to 128 scalar values.');
  if (!isScalar(value) && !(Array.isArray(value) && value.every(isScalar))) throw new Error('Use an exact integer within JavaScript’s safe range, boolean, string, or scalar list. Floats, null, objects, and nested lists are not supported.');
  const actual: OutputKind = typeof value === 'number' ? 'integer' : typeof value === 'boolean' ? 'boolean' : typeof value === 'string' ? 'string' : 'list';
  if (kind && actual !== kind) throw new Error(`This problem expects a ${kind} prediction, not ${actual}.`);
  return value as PredictionValue;
}
export function formatPrediction(value: unknown): string {
  return JSON.stringify(value) ?? '';
}
