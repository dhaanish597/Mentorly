import { loadProductState, saveProductState, type PracticeDraft } from './productState';

type DraftData = { drafts: Record<string, PracticeDraft>; bookmarks: string[] };
const MAX_BYTES = 10_000_000;
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value); }
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (record(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
async function hash(value: unknown): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(value)));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
function validate(data: unknown): DraftData {
  if (!record(data) || Object.keys(data).sort().join(',') !== 'bookmarks,drafts' || !record(data.drafts) || !Array.isArray(data.bookmarks)
    || Object.keys(data.drafts).length > 100 || data.bookmarks.length > 1000) throw new Error('Invalid or oversized draft backup.');
  const drafts: Record<string, PracticeDraft> = {};
  for (const [key, draft] of Object.entries(data.drafts)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key) || key.length > 512 || !record(draft)
      || Object.keys(draft).sort().join(',') !== 'sourceCode,status,transcript,updatedAt'
      || typeof draft.sourceCode !== 'string' || draft.sourceCode.length > 100_000
      || typeof draft.transcript !== 'string' || draft.transcript.length > 100_000
      || typeof draft.updatedAt !== 'number' || !Number.isFinite(draft.updatedAt) || draft.updatedAt < 0
      || !['Draft', 'In progress'].includes(String(draft.status))) throw new Error('Invalid draft backup record.');
    drafts[key] = { sourceCode: draft.sourceCode, transcript: draft.transcript, updatedAt: draft.updatedAt, status: draft.status as PracticeDraft['status'] };
  }
  if (!data.bookmarks.every(item => typeof item === 'string' && item.length <= 128)) throw new Error('Invalid backup bookmarks.');
  return { drafts, bookmarks: data.bookmarks as string[] };
}
export async function exportDraftBackup(): Promise<string> {
  const current = loadProductState();
  const data = validate({ drafts: current.drafts, bookmarks: current.bookmarks });
  return JSON.stringify({ format: 'viva-device-drafts', schema_version: 1, content_sha256: await hash(data), data }, null, 2);
}
export async function importDraftBackup(text: string): Promise<{ restored: number; skipped: number }> {
  if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new Error('Draft backup exceeds 10 MB.');
  const raw: unknown = JSON.parse(text);
  if (!record(raw) || Object.keys(raw).sort().join(',') !== 'content_sha256,data,format,schema_version'
    || raw.format !== 'viva-device-drafts' || raw.schema_version !== 1 || typeof raw.content_sha256 !== 'string') throw new Error('Unsupported draft backup format.');
  const incoming = validate(raw.data);
  if (await hash(incoming) !== raw.content_sha256) throw new Error('Draft backup integrity check failed.');
  const current = loadProductState();
  const drafts = { ...current.drafts };
  let restored = 0, skipped = 0;
  for (const [key, draft] of Object.entries(incoming.drafts)) {
    const existing = drafts[key];
    if (existing && existing.updatedAt >= draft.updatedAt) { skipped += 1; continue; }
    drafts[key] = draft; restored += 1;
  }
  const error = saveProductState({ ...current, drafts, bookmarks: [...new Set([...current.bookmarks, ...incoming.bookmarks])] });
  if (error) throw new Error(error);
  window.dispatchEvent(new Event('viva:preferences-changed'));
  return { restored, skipped };
}
