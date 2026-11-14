import { useState } from 'react';
import type { Difficulty, InterviewCatalog, InterviewConfig, InterviewConfiguration, InterviewType, LanguageMode } from './types';

export const TYPE_LABELS: Record<InterviewType, string> = { dsa: 'DSA', cs: 'Computer science', system_design: 'System design', codebase_defense: 'Codebase defense' };
type SetupProps = { config: InterviewConfig; catalog: InterviewCatalog; busy: boolean; onStart: (value: InterviewConfiguration) => void };
export function InterviewSetup({ config, catalog, busy, onStart }: SetupProps): JSX.Element {
  const [value, setValue] = useState<InterviewConfiguration>({ type: 'dsa', difficulty: 'beginner', topics: [], duration_minutes: config.duration_minutes.default, language_mode: 'en-IN' });
  const topics = catalog.topics[value.type];
  return <form className="interview-setup" onSubmit={event => { event.preventDefault(); onStart(value); }}>
    <h2>Set the interview brief</h2>
    <p>One question at a time. Neutral acknowledgements during the interview; an evidence-limited report at the end.</p>
    <div className="interview-fields">
      <label>Interview type<select value={value.type} disabled={busy} onChange={event => setValue({ ...value, type: event.target.value as InterviewType, topics: [] })}>{config.types.map(type => <option key={type} value={type}>{TYPE_LABELS[type]}</option>)}</select></label>
      <label>Difficulty<select value={value.difficulty} disabled={busy} onChange={event => setValue({ ...value, difficulty: event.target.value as Difficulty })}>{config.difficulties.map(level => <option key={level} value={level}>{level}</option>)}</select></label>
      <label>Duration in minutes<input type="number" min={config.duration_minutes.minimum} max={config.duration_minutes.maximum} required value={value.duration_minutes} disabled={busy} onChange={event => setValue({ ...value, duration_minutes: Number(event.target.value) })} /></label>
      <label>Language preference<select value={value.language_mode} disabled={busy} onChange={event => setValue({ ...value, language_mode: event.target.value as LanguageMode })}>{config.language_modes.map(mode => <option key={mode} value={mode}>{mode === 'en-IN' ? 'English (India)' : 'Tamil + English'}</option>)}</select></label>
    </div>
    <fieldset disabled={busy}><legend>Topics (optional, up to eight)</legend><div className="interview-topics">{topics.map(topic => <label key={topic}><input type="checkbox" checked={value.topics.includes(topic)} disabled={!value.topics.includes(topic) && value.topics.length >= 8} onChange={event => setValue({ ...value, topics: event.target.checked ? [...value.topics, topic] : value.topics.filter(t => t !== topic) })} />{topic.replace(/-/g, ' ')}</label>)}</div></fieldset>
    {value.type === 'codebase_defense' && <p>Discuss your own code without secrets. File references are claimed, not verified against a repository.</p>}
    <p className="interview-note">Question text is currently English. Language mode is a voice preference; multilingual semantic validity is not graded.</p>
    <button type="submit" className="primary" disabled={busy}>{busy ? 'Starting…' : 'Start interview'}</button>
  </form>;
}
