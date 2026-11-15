import { useId, useState, useSyncExternalStore } from 'react';
import { TYPE_LABELS } from '../interview/InterviewSetup';
import {
  INTERVIEW_PREFERENCE_CONFIG as config, getDefaultInterviewPreferences,
  loadInterviewPreferences, saveInterviewPreferences, subscribeInterviewPreferences,
} from '../interview/preferences';
import type { InterviewPreferences } from '../interview/preferences';
import type { Difficulty, InterviewType } from '../interview/types';

type InterviewDefaultsProps = { onSaved: (ok: boolean) => void };
type Snapshot = { readonly value: InterviewPreferences; readonly readError: boolean };
type Draft = { readonly base: Snapshot; readonly value: InterviewPreferences; readonly duration: string };

function readPreferenceSnapshot(): Snapshot {
  let readError = false;
  const value = loadInterviewPreferences(config, { getItem: key => {
    try { return window.localStorage.getItem(key); }
    catch (error) { readError = true; throw error; }
  } });
  return Object.freeze({ value, readError });
}

/** Stable snapshots for React's external-store contract; drafts stay local until Save. */
function createPreferenceStore() {
  let snapshot = readPreferenceSnapshot();
  const serverSnapshot: Snapshot = Object.freeze({ value: getDefaultInterviewPreferences(config), readError: false });
  return {
    getSnapshot: () => snapshot,
    getServerSnapshot: () => serverSnapshot,
    subscribe: (changed: () => void) => subscribeInterviewPreferences(config, next => {
      const { readError } = readPreferenceSnapshot();
      snapshot = Object.freeze({ value: next, readError });
      changed();
    }),
  };
}
function draftFrom(base: Snapshot): Draft {
  return { base, value: base.value, duration: String(base.value.duration_minutes) };
}

export function InterviewDefaults({ onSaved }: InterviewDefaultsProps): JSX.Element {
  const [store] = useState(createPreferenceStore);
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
  const [draft, setDraft] = useState(() => draftFrom(snapshot));
  const readError = 'Interview defaults could not be read on this device. Safe defaults are shown.';
  const [validation, setValidation] = useState({ base: snapshot, error: snapshot.readError ? readError : '', durationInvalid: false });
  const errorId = useId();
  const current = draft.base === snapshot ? draft : draftFrom(snapshot);
  const error = validation.base === snapshot ? validation.error : snapshot.readError ? readError : '';
  const durationInvalid = validation.base === snapshot && validation.durationInvalid;
  function save(): void {
    const duration = Number(current.duration);
    const valid = current.duration.trim() !== '' && Number.isSafeInteger(duration)
      && duration >= config.duration_minutes.minimum && duration <= config.duration_minutes.maximum;
    if (!valid) {
      setValidation({ base: snapshot, error: `Use a whole number from ${config.duration_minutes.minimum} to ${config.duration_minutes.maximum} minutes.`, durationInvalid: true });
      onSaved(false); return;
    }
    const ok = saveInterviewPreferences({ ...current.value, duration_minutes: duration }, config);
    setValidation({ base: snapshot, error: ok ? '' : 'Interview defaults could not be saved on this device. Try again; your draft is still here.', durationInvalid: false });
    onSaved(ok);
  }
  return <fieldset className="interview-defaults">
    <legend>Interview defaults</legend>
    <p className="settings-footnote">Saved only on this device in this browser, not to your account or other devices. These defaults apply to new interviews, not active sessions or reports.</p>
    <label className="setting-row">Default interview type<select value={current.value.type} onChange={event => setDraft({ ...current, value: { ...current.value, type: event.target.value as InterviewType } })}>{config.types.map(type => <option key={type} value={type}>{TYPE_LABELS[type]}</option>)}</select></label>
    <label className="setting-row">Default interview difficulty<select value={current.value.difficulty} onChange={event => setDraft({ ...current, value: { ...current.value, difficulty: event.target.value as Difficulty } })}>{config.difficulties.map(level => <option key={level} value={level}>{level}</option>)}</select></label>
    <label className="setting-row">Default interview duration<input type="number" min={config.duration_minutes.minimum} max={config.duration_minutes.maximum} step="1" value={current.duration} aria-invalid={durationInvalid || undefined} aria-describedby={durationInvalid ? errorId : undefined} onChange={event => setDraft({ ...current, duration: event.target.value })} /></label>
    <p className="settings-footnote">Only type, difficulty, and duration are saved. No consent or camera preferences are stored. Topics start empty; your shared speech language stays authoritative.</p>
    <p className="settings-footnote">These are locally shipped choices, not a server health check. The interview setup uses the server’s supported configuration for final validation.</p>
    {error && <p id={errorId} className="learning-notice" role="alert">{error}</p>}
    <button type="button" onClick={save}>Save interview defaults</button>
  </fieldset>;
}
