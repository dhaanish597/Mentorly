import type { Dispatch, SetStateAction } from 'react';
import type { StudioSession } from './studioApi';
import { StudioVoice } from './StudioVoice';
import { MentorPortrait } from './components/HorizonVisuals';
import { readable } from './StudioViews';
import type { ScenarioView, Snapshot } from './StudioViews';

type Props = {
  session: StudioSession; snapshot: Snapshot | null; scenario: ScenarioView | null;
  reply: string; draft: string; onDraft: Dispatch<SetStateAction<string>>;
  kind: string; onKind: (kind: string) => void;
  locked: boolean; actionDisabled: boolean; dirty: boolean; assumptionsPending: boolean;
  busy: boolean; turnInFlight: boolean; onSend: () => void; onCoach: (action: string) => void;
  onInterrupt: () => void; onTeaching: () => void;
  correcting: boolean; onCancelCorrection: () => void;
};

function currentRecordedTurns(snapshot: Snapshot | null): NonNullable<Snapshot['events']> {
  const turns = new Map((snapshot?.turns ?? []).map(turn => [turn.id, turn]));
  function resolve(id: string | undefined): string | null {
    let seen = new Set<string>();
    while (id && turns.has(id) && !seen.has(id)) {
      const turn = turns.get(id)!;
      if (!turn.superseded_by) return id;
      const next = turns.get(turn.superseded_by);
      if (!next || (next.transcript_revision ?? 1) <= (turn.transcript_revision ?? 1)) return null;
      seen = new Set([...seen, id]);
      id = next.id;
    }
    return null;
  }
  return (snapshot?.events ?? []).filter(event => event.type === 'turn.recorded' && resolve(event.payload?.turn_id) !== null);
}

function nextStep(snapshot: Snapshot | null, scenario: ScenarioView | null): { action: string; label: string } | null {
  if (snapshot?.state === 'completed') return { action: 'reopen', label: 'Reopen practice' };
  if ((scenario?.constraint_index ?? 0) < 3) return { action: 'advance', label: 'Next constraint →' };
  if (snapshot?.posture === 'assessment') return { action: 'finish', label: 'Finish assessment' };
  const events = snapshot?.events ?? [];
  const teach = [...events].reverse().find(e => e.type === 'coach.action' && e.payload?.action === 'teachback');
  const transfer = [...events].reverse().find(e => e.type === 'coach.action' && e.payload?.action === 'transfer');
  if (!teach) return { action: 'teachback', label: 'Begin teach-back' };
  const recorded = currentRecordedTurns(snapshot);
  const restated = recorded.some(e => e.sequence > teach.sequence && (!transfer || transfer.sequence < teach.sequence || e.sequence < transfer.sequence));
  if (!restated) return null;
  if (!transfer || transfer.sequence < teach.sequence) return { action: 'transfer', label: 'Try a fresh case →' };
  return recorded.some(e => e.sequence > transfer.sequence) ? { action: 'finish', label: 'Finish practice' } : null;
}

export function StudioMentor({ session, snapshot, scenario, reply, draft, onDraft, kind, onKind, locked, actionDisabled, dirty, assumptionsPending, busy, turnInFlight, onSend, onCoach, onInterrupt, onTeaching, correcting, onCancelCorrection }: Props) {
  const completed = snapshot?.state === 'completed';
  const assessment = snapshot?.posture === 'assessment';
  const next = nextStep(snapshot, scenario);
  const groups = assessment ? [{ label: 'Assessment assistance', actions: ['hint', 'skip', 'advance', 'finish'] }]
    : [{ label: 'Understand and explore', actions: ['clarify', 'hint', 'options', 'sketch', 'explain'] }, { label: 'Practice your reasoning', actions: ['teachback', 'transfer'] }, { label: 'Move through the case', actions: ['rewind', 'skip', 'advance', 'finish'] }];
  return <aside className="studio-mentor studio-card" aria-label="Mentor conversation">
    <header className="studio-mentor-header">
      <MentorPortrait state={busy ? 'thinking' : 'idle'} teacher="nexus" className="studio-mentor-portrait" eager />
      <div><h2>Nexus</h2><p role="status">System Design Teacher · {busy ? 'Working with your reasoning…' : completed ? 'Practice complete' : 'Here to help you think'}</p></div>
    </header>
    <div className="studio-conversation" role="log" aria-label="Conversation">
      <div className="studio-mentor-bubble"><p>{scenario?.constraint.description ?? 'Build an architecture and tell me why you chose it.'}</p><span>What would you choose, and why?</span></div>
      {snapshot?.turns?.slice(-2).map(item => <div className="studio-student-bubble" key={item.id}><p>{item.content}</p><span>{readable(item.kind)} · revision {item.diagram_revision}</span></div>)}
      {reply && <div className="studio-mentor-bubble" role="status"><strong>Mentor</strong><p>{reply}</p></div>}
    </div>
    <div className="studio-composer">
      <StudioVoice session={session} epoch={snapshot?.epoch ?? 1} events={snapshot?.events ?? []} disabled={locked} onTranscript={text => onDraft(previous => previous ? `${previous}\n${text}` : text)} />
      <label htmlFor="studio-explanation">Your explanation</label>
      <textarea id="studio-explanation" disabled={locked} rows={3} value={draft} placeholder="Talk it through, or type your thinking…" onChange={e => onDraft(e.target.value)} onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
          event.preventDefault();
          if (!locked && !actionDisabled && draft.trim()) onSend();
        }
      }} />
      {!completed && <button className="primary studio-send" disabled={locked || actionDisabled || !draft.trim()} onClick={onSend}>{correcting ? 'Send correction' : 'Send explanation'}</button>}
      {correcting && <><p className="studio-muted">Correcting a saved explanation. The original stays in your timeline.</p><button disabled={busy} onClick={onCancelCorrection}>Cancel correction</button></>}
      {!correcting && next && <button className={completed ? 'primary studio-send' : 'studio-next'} disabled={actionDisabled} onClick={() => onCoach(next.action)}>{next.label}</button>}
      {!next && !completed && <p className="studio-muted">Answer this question before moving on.</p>}
      {dirty || assumptionsPending ? <p className="studio-muted" role="status">Save the diagram and apply any assumptions draft before sending or moving on.</p> : !completed && <p className="studio-composer-hint">Enter to send · Shift + Enter for a new line</p>}
      {turnInFlight && <button disabled={busy && !turnInFlight} onClick={onInterrupt}>Interrupt current turn</button>}
      <details className="studio-help"><summary>Help</summary>
        {completed ? <button disabled={actionDisabled} onClick={() => onCoach('reopen')}>Reopen</button> : groups.map(group => <fieldset key={group.label} className="studio-help-group"><legend>{group.label}</legend><div className="studio-actions">
          {group.actions.map(name => <button key={name} disabled={actionDisabled} onClick={() => onCoach(name)}>{name === 'teachback' ? 'Teach back' : name[0].toUpperCase() + name.slice(1)}</button>)}
        </div></fieldset>)}
        {assessment && <><p>One hint or a skip records assistance. Further teaching interrupts the assessment.</p><button disabled={actionDisabled} onClick={onTeaching}>Switch to teaching</button></>}
        <label>Turn type<select value={kind} onChange={e => onKind(e.target.value)}><option value="explain">Explain</option><option value="clarify">Clarify</option><option value="teachback">Teach back</option><option value="transfer">Transfer</option></select></label>
        {!turnInFlight && <button disabled={busy} onClick={onInterrupt}>Interrupt current turn</button>}
      </details>
    </div>
  </aside>;
}
