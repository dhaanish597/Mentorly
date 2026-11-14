import type { Graph } from './studioApi';
import { EvaluationView, FeedbackView, GraphComparison, SummaryView } from './StudioViews';
import type { ScenarioView, Snapshot } from './StudioViews';

type Proposal = { proposal_id: string; graph: Graph; validation: unknown };
type Review = { card_id: string; prompt: string; due_at: string };
type Props = {
  graph: Graph; snapshot: Snapshot | null; scenario: ScenarioView | null; busy: boolean; mutationDisabled: boolean;
  proposalText: string; onProposalText: (text: string) => void; proposal: Proposal | null;
  onPreview: () => void; onDecide: (decision: 'accept' | 'discard') => void;
  revisions: { revision: number; parent_revision: number | null; created_at: string }[];
  onRevisions: () => void; onRestore: (revision: number) => void; summary: unknown;
  onSummary: () => void; onExport: () => void; lastTurnId: string;
  externalFeedback: boolean; onExternalFeedback: (value: boolean) => void; feedback: unknown; onFeedback: () => void;
  reviewPrompt: string; onReviewPrompt: (value: string) => void; reviews: Review[];
  onCreateReview: () => void; onLoadReviews: () => void; onRateReview: (id: string, rating: number) => void;
  onReload: () => void; onLeave: () => void; onDelete: () => void;
  onEditTurn: (turn: NonNullable<Snapshot['turns']>[number]) => void; editDisabled: boolean;
};

export function StudioSessionTools({ graph, snapshot, scenario, busy, mutationDisabled, proposalText, onProposalText, proposal, onPreview, onDecide, revisions, onRevisions, onRestore, summary, onSummary, onExport, lastTurnId, externalFeedback, onExternalFeedback, feedback, onFeedback, reviewPrompt, onReviewPrompt, reviews, onCreateReview, onLoadReviews, onRateReview, onReload, onLeave, onDelete, onEditTurn, editDisabled }: Props) {
  const latest = [...(snapshot?.turns ?? [])].reverse().find(turn => !turn.superseded_by);
  const facts = scenario?.clarification_facts;
  return <section className="studio-session-tools studio-card" aria-label="Session details and evidence">
    <h2 className="sr-only">Session details and evidence</h2>
    {scenario && <details><summary>The case and learning objectives</summary>
      <h3>{scenario.title}</h3><p>{scenario.id.startsWith('REPO-') ? 'Explore the repository and support your explanation with source citations.' : scenario.problem_statement}</p>
      <ul>{scenario.learning_objectives.map((item, i) => <li key={i}>{item}</li>)}</ul>
      <p>{scenario.prerequisites.join(', ')}</p>
      {scenario.linked_exercise_ids.map(id => <a key={id} href={`/practice/${encodeURIComponent(id)}`}>Open related coding problem: {id}</a>)}
      {facts && <><h3>Clarification facts</h3><ul>{(Array.isArray(facts) ? facts : Object.entries(facts).map(([key, value]) => `${key}: ${String(value)}`)).map((fact, i) => <li key={i}>{fact}</li>)}</ul></>}
      <p className="studio-muted">Scenario {scenario.id} · version {scenario.version}</p>
    </details>}
    <details><summary>Review a proposed graph</summary>
      <p>Preview a proposed graph against the saved revision. Your diagram changes only after acceptance.</p>
      <label>Proposed graph<textarea disabled={busy} rows={5} value={proposalText} onChange={e => onProposalText(e.target.value)} /></label>
      <button disabled={mutationDisabled || !proposalText.trim()} onClick={onPreview}>Preview proposal</button>
      {proposal && <>
        <GraphComparison current={graph} proposed={proposal.graph} /><EvaluationView value={proposal.validation} />
        <details><summary>Advanced graph data</summary><pre>{JSON.stringify(proposal.graph, null, 2)}</pre></details>
        <div className="studio-actions"><button disabled={mutationDisabled} onClick={() => onDecide('accept')}>Accept proposal</button><button disabled={mutationDisabled} onClick={() => onDecide('discard')}>Discard proposal</button></div>
      </>}
    </details>
    <details><summary>Saved revisions and review</summary>
      <button disabled={busy} onClick={onRevisions}>Load revisions</button>
      {revisions.length > 0 && <ul>{revisions.map(r => <li key={r.revision}>Revision {r.revision} <button disabled={mutationDisabled || r.revision === snapshot?.diagram_revision} onClick={() => onRestore(r.revision)}>Restore as new revision</button></li>)}</ul>}
      <button disabled={busy} onClick={onSummary}>Load assessment summary</button>
      {summary !== null && <SummaryView value={summary} />}
      <button disabled={busy} onClick={onExport}>Export session</button>
    </details>
    <details><summary>Feedback on the last explanation</summary>
      <p>Without external consent the coordinator returns an explicit abstention where it cannot assess the answer.</p>
      <label className="studio-check"><input type="checkbox" checked={externalFeedback} onChange={e => onExternalFeedback(e.target.checked)} />Allow sending this explanation and relevant session context to the configured external model</label>
      <button disabled={busy || !lastTurnId} onClick={onFeedback}>Request feedback</button>
      {feedback !== null && <FeedbackView value={feedback} />}
    </details>
    <details><summary>Review queue</summary>
      <label>Review prompt linked to your last submitted turn<input value={reviewPrompt} onChange={e => onReviewPrompt(e.target.value)} /></label>
      <button disabled={busy || !lastTurnId || !reviewPrompt.trim()} onClick={onCreateReview}>Create review card</button>
      <button disabled={busy} onClick={onLoadReviews}>Load due cards</button>
      {reviews.map(card => <article key={card.card_id}><p>{card.prompt}</p><p>Due: <time dateTime={card.due_at}>{card.due_at}</time></p><div className="studio-actions" aria-label="Rate recall">{[1, 2, 3, 4].map(rating => <button key={rating} disabled={busy} onClick={() => onRateReview(card.card_id, rating)}>{['Again', 'Hard', 'Good', 'Easy'][rating - 1]}</button>)}</div></article>)}
    </details>
    <details><summary>Your decision timeline</summary>
      {snapshot?.turns?.length ? <ol>{snapshot.turns.map(item => <li key={item.id}><strong>{item.kind} · diagram revision {item.diagram_revision}</strong><p>{item.content}</p><time dateTime={item.created_at}>{item.created_at}</time>{item.superseded_by && <p className="studio-muted">Superseded by a corrected explanation.</p>}{item.id === latest?.id && <button disabled={editDisabled} onClick={() => onEditTurn(item)}>Edit latest explanation</button>}</li>)}</ol> : <p>No explanations submitted yet.</p>}
    </details>
    <details><summary>Session activity</summary>
      {snapshot?.events?.length ? <ol className="studio-events">{snapshot.events.map(event => <li key={event.sequence}>{event.type.replace(/[._]/g, ' ')}{event.payload?.text && <p>{event.payload.text}</p>}</li>)}</ol> : <p>No activity yet.</p>}
    </details>
    <details><summary>Session controls</summary>
      <div className="studio-actions"><button disabled={busy} onClick={onReload}>Reload saved</button><button disabled={busy} onClick={onLeave}>Leave session</button></div>
      <p>Delete permanently removes this session from the coordinator.</p><button className="danger" disabled={busy} onClick={onDelete}>Delete session</button>
    </details>
  </section>;
}
