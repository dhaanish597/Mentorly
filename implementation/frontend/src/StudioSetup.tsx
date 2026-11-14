import { useState } from 'react';
import type { Scenario, StudioSession, Workspace } from './studioApi';

type Props = {
  scenarios: Scenario[]; scenario: string; onScenario: (value: string) => void;
  mock: boolean; onMock: (value: boolean) => void; duration: number; onDuration: (value: number) => void;
  posture: string; onPosture: (value: string) => void; busy: boolean;
  sessions: StudioSession[]; workspace?: Workspace;
  onStart: () => void; onResume: (session: StudioSession) => void; onDeleteWorkspace: () => void;
};
const modeLabels: Record<string, string> = {
  guided_system_design: 'System design', dsa_to_system_bridge: 'Algorithms → architecture',
  repo_exploration: 'Explore a codebase', project_defense: 'Defend your project',
};
const modeDescriptions: Record<string, string> = {
  guided_system_design: 'Build a system. Explain the choices that make it work.',
  dsa_to_system_bridge: 'Take a familiar algorithm into a real system.',
  repo_exploration: 'Follow the code and make your reasoning traceable.',
  project_defense: 'Tell the story behind your architecture with evidence.',
};

export function StudioSetup({ scenarios, scenario, onScenario, mock, onMock, duration, onDuration, posture, onPosture, busy, sessions, workspace, onStart, onResume, onDeleteWorkspace }: Props) {
  const [resumeId, setResumeId] = useState('');
  const item = scenarios.find(s => s.id === scenario);
  const invalidDuration = mock && item?.mode === 'guided_system_design' && (duration < 60 || duration > 14400 || !Number.isInteger(duration));
  return <div className="studio-setup">
    <section className="studio-scenario-catalog" aria-labelledby="scenario-heading">
      <p className="studio-eyebrow">A conversation, not a checklist</p>
      <h2 id="scenario-heading">What will you design today?</h2>
      <p>Choose a case, sketch your architecture, then tell your mentor why.</p>
      <fieldset className="studio-scenario-cards" disabled={busy}>
        <legend className="sr-only">Scenario</legend>
        {scenarios.map((s, i) => <label className={`studio-scenario-choice ${scenario === s.id ? 'is-selected' : ''}`} key={s.id}>
          <input type="radio" name="studio-scenario" value={s.id} checked={scenario === s.id} onChange={() => onScenario(s.id)} />
          <span className="studio-choice-number" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
          <span className="studio-choice-kind">{modeLabels[s.mode] ?? 'Design practice'}</span>
          <strong>{s.title}</strong>
          <span>{modeDescriptions[s.mode] ?? 'Reason through a new case with your mentor.'}</span>
          <span className="studio-choice-link" aria-hidden="true">{scenario === s.id ? 'Selected ✓' : 'Explore this case →'}</span>
        </label>)}
      </fieldset>
      {!scenarios.length && <p role="status">The scenario catalog is loading or unavailable. Any error appears above.</p>}
    </section>
    <aside className="studio-start-card studio-card">
      <img className="studio-setup-mentor" src="/mentor/nexus.svg" width="180" height="180" alt="Nexus — System Design Teacher" />
      <h2>Start a session</h2>
      <p>{item?.title ?? 'Choose a scenario to begin.'}</p>
      <p className="studio-muted">Voice or text. Your pace. Your reasoning.</p>
      <button className="primary" disabled={busy || !scenario || invalidDuration} onClick={onStart}>Start session</button>
      {item && ['repo_exploration', 'project_defense'].includes(item.mode) ? (
        <p className="studio-muted" style={{ color: 'var(--horizon-coral, #ff735c)' }}>Repository cases need a snapshot imported under Codebase learning first. Session access stays in this browser tab.</p>
      ) : (
        <div style={{ margin: '10px 0', padding: '8px 12px', background: 'rgba(185, 228, 208, 0.1)', border: '1px solid rgba(185, 228, 208, 0.25)', borderRadius: '10px', fontSize: '12px', color: 'var(--horizon-mint, #b9e4d0)' }}>
          ✨ <strong>System architecture case</strong> · No repository required. Whiteboard + AI coach.
        </div>
      )}
      <details>
        <summary>Interview settings</summary>
        <label>Posture<select value={posture} onChange={e => onPosture(e.target.value)}><option value="teaching">Teaching</option><option value="assessment">Assessment</option></select></label>
        {item?.mode === 'guided_system_design' && <>
          <label className="studio-check"><input type="checkbox" checked={mock} onChange={e => onMock(e.target.checked)} />Time-boxed mock interview</label>
          {mock && <label>Duration in minutes<input type="number" min="1" max="240" value={duration / 60} onChange={e => onDuration(Number(e.target.value) * 60)} /></label>}
        </>}
        <p>Assessment records hints and skips as assistance. Duration must be 1–240 whole minutes.</p>
      </details>
      <details>
        <summary>Resume in this tab</summary>
        {sessions.length ? <>
          <label>Saved session<select value={resumeId || sessions[0].id} onChange={e => setResumeId(e.target.value)}>
            {sessions.map((s, i) => <option key={s.id} value={s.id}>Design session {i + 1}</option>)}
          </select></label>
          <button disabled={busy} onClick={() => { const session = sessions.find(s => s.id === resumeId) ?? sessions[0]; onResume(session); }}>Open session</button>
        </> : <p>No studio sessions in this tab yet.</p>}
      </details>
      {workspace && <details>
        <summary>Workspace data</summary>
        <p>Delete this workspace and its stored sessions and repository snapshots.</p>
        <button className="danger" disabled={busy} onClick={onDeleteWorkspace}>Delete workspace</button>
      </details>}
    </aside>
  </div>;
}
