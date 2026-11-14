import { lazy, Suspense, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import type { Challenge, EvidenceArtifact, ExerciseMetadata, HintLevel, TraceExecutionReport, ValueSchema } from '../types/api';
import type { WorkbenchSessionState } from '../state/useSessionStore';
import { publicExamples } from '../catalog/metadata';
import { formatPrediction, type OutputKind } from '../catalog/prediction';
import { Icon } from './HorizonVisuals';
const PythonEditor = lazy(() => import('./PythonEditor').then(module => ({ default: module.PythonEditor })));

function boundRange(min: number | null | undefined, max: number | null | undefined): string {
  return min != null && max != null ? `${min} to ${max}` : min != null ? `at least ${min}` : max != null ? `at most ${max}` : 'any supported number of';
}
function readableValue(rule: ValueSchema): string {
  if (rule.kind === 'boolean') return 'true or false';
  if (rule.kind === 'integer') return rule.minimum != null || rule.maximum != null ? `an integer from ${boundRange(rule.minimum, rule.maximum)} (inclusive)` : 'an integer';
  if (rule.kind === 'string') return `a string with ${boundRange(rule.min_length, rule.max_length)} characters`;
  const item = rule.items?.kind === 'integer' ? 'integers' : rule.items?.kind === 'boolean' ? 'boolean values' : rule.items?.kind === 'string' ? 'strings' : 'scalar values';
  const values = rule.items?.kind === 'integer' && (rule.items.minimum != null || rule.items.maximum != null) ? `, each from ${boundRange(rule.items.minimum, rule.items.maximum)} (inclusive)` : '';
  return `a list containing ${boundRange(rule.min_length, rule.max_length)} ${item}${values}${rule.sorted_required ? ', in non-decreasing order' : ''}`;
}
function readableConstraints(exercise: ExerciseMetadata | undefined, spec: ExerciseMetadata['spec_versions'][number] | undefined): string[] {
  const inputs = spec?.input_schema ?? exercise?.input_schema;
  if (!inputs || !Object.keys(inputs).length) return spec?.constraints_summary ?? [];
  const output = spec?.output_schema ?? exercise?.output_schema;
  const notes = (spec?.constraints_summary ?? []).filter(note => !/[{}]|"kind"|"minimum"/.test(note));
  return [...Object.entries(inputs).map(([name, rule]) => `${name}: ${readableValue(rule)}.`), ...(output ? [`Return ${readableValue(output)}.`] : []), ...notes];
}
export function LearningStepIndicator({ state }: { state: WorkbenchSessionState }) {
  const transfer = ['FRESH_CASE_CHECK', 'FRESH_CASE_REVIEW', 'PRACTICE_CHECKPOINT_COMPLETED'].includes(state.learningState);
  const repair = state.learningState === 'REPAIR_REQUIRED' || (state.editorDirty && !!state.priorFailureArtifactId);
  const run = ['VERIFYING', 'INSPECTING_RESULT', 'PREDICTION_REVIEW'].includes(state.learningState);
  const step = transfer ? 'Transfer' : repair ? 'Repair' : run ? 'Run' : state.activeChallenge || state.proposedClaim?.claim_type === 'OUTPUT_PREDICTION_AND_REASON' ? 'Predict' : 'Explain';
  return <ol className="learning-steps" aria-label="Learning steps">{['Explain', 'Predict', 'Run', 'Repair', 'Transfer'].map(label => <li key={label} aria-current={step === label ? 'step' : undefined}><span>{label}</span></li>)}</ol>;
}
type ProblemProps = { exercise: ExerciseMetadata | undefined; state: WorkbenchSessionState; onAcknowledgeSpec: () => void; onSelectSpec?: (spec: string) => void };
export function ProblemConstraintPanel({ exercise, state, onAcknowledgeSpec, onSelectSpec }: ProblemProps) {
  const spec = exercise?.spec_versions.find(item => item.spec_version === state.specVersion);
  const examples = publicExamples(exercise);
  return <section className="surface problem-panel" aria-label="Problem & Domain Specification"><p className="eyebrow">Problem / Python</p><h1>{exercise?.title ?? state.exerciseId}</h1>{exercise && <><p className="difficulty">{exercise.difficulty}</p><p>{exercise.description}</p><code className="function-signature">{exercise.function_name}(…)</code></>}
    {exercise && exercise.spec_versions.length > 1 && <div className="spec-controls" aria-label="Domain specifications">{exercise.spec_versions.map(item => <button type="button" aria-pressed={state.specVersion === item.spec_version} key={item.spec_version} onClick={() => onSelectSpec?.(item.spec_version)}>{item.label}</button>)}</div>}
    <h2>Constraints</h2><p className="muted">{spec?.label ?? state.specVersion}</p><ul>{readableConstraints(exercise, spec).map(constraint => <li key={constraint}>{constraint}</li>)}</ul>
    {(!state.specAcknowledged || state.sessionState === 'SPEC_ACK_REQUIRED') && <div role="alert" data-testid="domain-ack-banner"><strong>Domain Specification Shift ({state.specVersion})</strong><p>Review the domain constraints before predicting or executing this revision.</p><button type="button" disabled={!state.sessionId || state.editorDirty || state.saveInFlight} onClick={onAcknowledgeSpec}>Acknowledge Domain Specification</button></div>}
    <h2>Examples</h2>{examples.length ? examples.map((example, index) => <article className="public-example" key={index}><h3>Example {index + 1}</h3><dl><dt>Input</dt><dd><code>{JSON.stringify(example.input_args)}</code></dd><dt>Output</dt><dd><code>{JSON.stringify(example.output)}</code></dd></dl><p>{example.explanation}</p></article>) : <p className="muted">This catalog entry has no published examples. Your challenge answer stays hidden until you confirm a prediction.</p>}
    <p className="statement-note">Explain the mechanism, not just the answer. Private check cases are never listed here.</p>
  </section>;
}
type CodeProps = { state: WorkbenchSessionState; highlightedLine: number | null; onChangeCode: (code: string) => void; onSaveCode: () => void; onSubmitCode?: () => void; isBusy?: boolean };
export function CodeWorkspace({ state, highlightedLine, onChangeCode, onSaveCode, onSubmitCode, isBusy = false }: CodeProps) {
  return <section id="code-pane" className="surface code-panel" aria-label="Code Workspace"><div className="section-heading"><div><p className="eyebrow">02 / Python workspace</p><h2>Your solution <span className="badge">Python · v{state.revision?.code_version_id ?? 1}</span></h2></div><div className="button-row"><button type="button" disabled={!state.sessionId || !state.editorDirty || state.saveInFlight || isBusy} onClick={onSaveCode}>{state.saveInFlight ? 'Saving…' : 'Save Code Version'}</button>{onSubmitCode && <button type="button" className="primary" disabled={!state.sessionId || state.saveInFlight || isBusy || !state.specAcknowledged} onClick={onSubmitCode}>{isBusy ? 'Checking…' : 'Submit code'}</button>}</div></div>
    {state.editorDirty && <p className="notice" data-testid="stale-buffer-badge">Unsaved Edits — Prior Feedback Superseded</p>}
    {highlightedLine !== null && !state.editorDirty && <p className="notice" data-testid="active-trace-line-banner">Active Trace Line Highlight: Line {highlightedLine}</p>}
    <Suspense fallback={<p role="status">Loading code editor…</p>}><PythonEditor value={state.sourceCode} onChange={onChangeCode} highlightedLine={state.editorDirty ? null : highlightedLine} /></Suspense>
    {state.syntaxError && <p role="alert">Syntax Error: {state.syntaxError}</p>}
  </section>;
}
type PredictionProps = { outputKind?: OutputKind; challenge: Challenge | null; predictedValue: string; predictionReason: string; onChangePredictedValue: (value: string) => void; onChangePredictionReason: (value: string) => void; onIssueDiagnosticChallenge: () => void; onSubmitPredictionProposal: () => void };
export function PredictionCaptureCard({ outputKind = 'integer', challenge, predictedValue, predictionReason, onChangePredictedValue, onChangePredictionReason, onIssueDiagnosticChallenge, onSubmitPredictionProposal }: PredictionProps) {
  return <section className="surface prediction-panel" aria-label="Challenge & Prediction Capture"><div className="section-heading"><h2>{challenge?.purpose === 'TRANSFER' ? 'Fresh Held-Out Transfer Challenge' : 'Active Diagnostic Challenge'}</h2><button type="button" onClick={onIssueDiagnosticChallenge}>Issue Challenge Input</button></div>
    {challenge ? <><p><strong>Input Arguments:</strong> <code data-testid="challenge-input-json">{JSON.stringify(challenge.input_args)}</code></p><p className="badge" data-testid="challenge-reveal-badge">Reveal State: {challenge.reveal_state ?? 'HIDDEN'}</p>
      <div className="prediction-fields"><label>{outputKind === 'integer' ? 'Predicted Integer Output' : `Predicted ${outputKind} output (JSON)`} <input aria-label={outputKind === 'integer' ? 'Predicted Integer Output' : 'Predicted Output'} type={outputKind === 'integer' ? 'number' : 'text'} step={outputKind === 'integer' ? '1' : undefined} placeholder={outputKind === 'boolean' ? 'true or false' : outputKind === 'string' ? '"your answer"' : outputKind === 'list' ? '[1, 2, 3]' : '0'} value={predictedValue} onChange={event => onChangePredictedValue(event.target.value)} /></label><label>Why (Mechanism / Invariant) <input aria-label="Prediction Rationale" type="text" value={predictionReason} onChange={event => onChangePredictionReason(event.target.value)} placeholder="Explain why this program returns your prediction" /></label></div><button type="button" className="primary" onClick={onSubmitPredictionProposal}>Propose Claim</button>
    </> : <p className="muted">Explain your approach below, or issue a concrete input bound to your saved code revision.</p>}
  </section>;
}
type CaptureProps = { state: WorkbenchSessionState; recording: boolean; textOnly: boolean; busy: boolean; onMicrophone: () => void; onStop: () => void };
export function VoiceCaptureControls({ state, recording, textOnly, busy, onMicrophone, onStop }: CaptureProps) {
  const disabled = textOnly || !state.sessionId || state.editorDirty || state.saveInFlight || !state.specAcknowledged || (busy && !recording);
  return <div className="button-row" aria-label="Microphone and audio interruption controls"><button type="button" className="mic-primary" disabled={disabled} onClick={onMicrophone}><Icon name="mic"/>{recording ? 'Done speaking' : 'Talk to your mentor'}</button><button type="button" className="danger" onClick={onStop}>Stop / Barge-In</button></div>;
}
type CoachFooterProps = { state: WorkbenchSessionState; busy: boolean; onConfirm: () => void; onAbstain: () => void; children?: ReactNode };
export function CoachActionFooter({ state, busy, onConfirm, onAbstain, children }: CoachFooterProps) {
  const proposal = state.proposedClaim;
  const isOutput = proposal?.claim_type === 'OUTPUT_PREDICTION_AND_REASON';
  const canConfirm = !busy && !!state.sessionId && !!state.revision && !state.editorDirty && !state.saveInFlight && state.specAcknowledged && state.sessionState !== 'SPEC_ACK_REQUIRED' && !!proposal && !!state.activeTurnId && proposal.claim_type !== 'UNSUPPORTED_CLAIM' && (!isOutput || proposal.challenge_id === state.activeChallenge?.challenge_id);
  return <footer className={`coach-action-footer ${proposal ? 'has-proposal' : 'no-proposal'}`} role="group" aria-label="Coach actions"><button type="button" className="primary" data-testid="confirm-claim-btn" disabled={!canConfirm} onClick={onConfirm}>{proposal && !isOutput ? 'Confirm Explanation (No Execution)' : 'Confirm Claim & Run in Sandbox'}</button>{proposal && <button className="revise-interpretation" type="button" disabled={busy} onClick={onAbstain}>Abstain / Revise Interpretation</button>}{children}</footer>;
}
type VoiceProps = { state: WorkbenchSessionState; onSubmitTranscript: () => void; recording?: boolean; textOnly?: boolean; onStartOrRerecordVoice: () => void; onBargeInStop: () => void; onChangeEditableTranscript: (value: string) => void; onConfirmClaimAndExecute: () => void; onAbstain?: () => void };
export function VoiceTurnPanel({ state, onSubmitTranscript, onChangeEditableTranscript }: VoiceProps) {
  const confirmation = useRef<HTMLDivElement | null>(null);
  useEffect(() => { if (state.proposedClaim) confirmation.current?.focus(); }, [state.proposedClaim]);
  const proposal = state.proposedClaim;
  const isOutput = proposal?.claim_type === 'OUTPUT_PREDICTION_AND_REASON';
  const claimLabels = { OUTPUT_PREDICTION_AND_REASON: 'Prediction', INVARIANT_OR_MECHANISM_CLAIM: 'Explanation', DOMAIN_VALIDITY_CLAIM: 'Domain assumption', CLARIFICATION_OR_HINT_REQUEST: 'Question', UNSUPPORTED_CLAIM: 'Needs clarification' };
  let summary = '';
  if (proposal?.claim_type === 'OUTPUT_PREDICTION_AND_REASON') summary = `Predicted output: ${formatPrediction(proposal.predicted_output)}. Reason: ${proposal.reason_summary ?? 'No reason extracted'}. Edit the output value and rationale above before confirming.`;
  if (proposal?.claim_type === 'INVARIANT_OR_MECHANISM_CLAIM') summary = proposal.mechanism_summary;
  if (proposal?.claim_type === 'DOMAIN_VALIDITY_CLAIM') summary = `Domain: ${proposal.target_spec_version}. Polarity: ${proposal.polarity}.`;
  if (proposal?.claim_type === 'CLARIFICATION_OR_HINT_REQUEST') summary = proposal.question_text;
  if (proposal?.claim_type === 'UNSUPPORTED_CLAIM') summary = `No supported interpretation: ${proposal.raw_summary}. Edit your explanation or abstain.`;
  return <section className="surface voice-panel" aria-label="Voice & Transcript Confirmation Turn Panel"><h2>Explain your reasoning</h2><p className="muted">Type first, or record your voice. Both need your confirmation.</p>    <label className="transcript-label">Your explanation / editable caption<textarea aria-label="Editable Learner Transcript" rows={3} value={state.editableTranscript} onChange={event => onChangeEditableTranscript(event.target.value)} placeholder="What does your code do, and why?" /></label><button type="button" onClick={onSubmitTranscript} disabled={!state.editableTranscript.trim()}>Propose Transcript Interpretation</button>
    {proposal && <div className="confirmation" aria-label="Editable claim interpretation" tabIndex={-1} ref={confirmation}><p><strong>Interpretation: </strong>{claimLabels[proposal.claim_type]}</p><p>{summary}</p>{!isOutput && <p>This confirms an explanation only. It does not run your code or reveal a hidden answer.</p>}</div>}
  </section>;
}
type ComparisonProps = { artifact: EvidenceArtifact | null; verificationReport?: EvidenceArtifact['verification_report'] | null; isStale: boolean; diagnosticHidden?: boolean };
function VerificationProcess({ report, artifact, diagnosticHidden }: { report: EvidenceArtifact['verification_report']; artifact: EvidenceArtifact | null; diagnosticHidden: boolean }) {
  return <div className="verification-process"><h3>Bounded verification process</h3><p>Curated cases: {report.curated_cases_run} / {report.curated_cases_total}</p><p>Generated cases: {report.generated_cases_run} / {report.generated_cases_target}</p><details><summary>Advanced verification diagnostics</summary><p>Completed stages: {report.completed_stages?.join(' → ') || 'None reported'}</p><p>Terminal reason: {report.terminal_reason}</p><p>Minimization: {report.minimization_status ?? artifact?.minimization_status ?? 'NOT_ATTEMPTED'}</p><p>Case identity: <code>{report.counterexample_case_hash ?? artifact?.case_hash ?? 'Not reported'}</code></p></details>
    {diagnosticHidden ? <p className="notice">The verifier found a diagnostic to predict. Its output, oracle and trace stay hidden until confirmation.</p> : artifact && report.counterexample_input && <div><p>Failing input: <code>{JSON.stringify(report.counterexample_input)}</code></p>{report.student_observation && <p>Failing learner observation: <code>{report.student_observation.kind === 'RETURN' ? formatPrediction(report.student_observation.return_value) : report.student_observation.kind}</code></p>}{report.reference_output !== null && report.reference_output !== undefined && <p>Failing reference output: <code>{formatPrediction(report.reference_output)}</code></p>}</div>}
  </div>;
}
export function ExecutionComparisonCard({ artifact, verificationReport, isStale, diagnosticHidden = false }: ComparisonProps) {
  const report = verificationReport ?? artifact?.verification_report;
  if (!report || isStale) return null;
  const observation = artifact?.actual_observation;
  const explanation = observation?.kind === 'UNAVAILABLE' || report.status === 'EXECUTION_UNAVAILABLE' ? 'Execution worker unavailable. This is not a learner-code failure. Retry when capacity returns.' : observation?.kind === 'TIMEOUT' ? 'Learner invocation timed out within its execution budget.' : observation?.kind === 'EXCEPTION' ? `Learner code raised ${observation.error_type ?? 'an exception'}.` : observation?.kind === 'RESOURCE_LIMIT' ? 'Learner code reached an execution resource limit.' : null;
  return <section className="surface result-panel" aria-label="Execution & Prediction Comparison" aria-live="polite"><p className="eyebrow">04 / Observed evidence</p><h2>{artifact ? 'Revealed Execution & Verification Result' : 'Bounded Verification Result'}</h2><div className="button-row">{artifact && <span className="badge" data-testid="prediction-status-badge">Prediction: {artifact.prediction_status}</span>}<span className="badge" data-testid="verification-status-badge">Verification: {report.status}</span></div>
    {explanation && <p className="notice">{explanation}</p>}
    {artifact && observation && <dl className="comparison"><div><dt>Confirmed Prediction:</dt><dd><code>{artifact.confirmed_prediction === null || artifact.confirmed_prediction === undefined ? 'N/A' : formatPrediction(artifact.confirmed_prediction)}</code></dd></div><div><dt>Your Code Output:</dt><dd><code>{observation.kind === 'RETURN' ? formatPrediction(observation.return_value) : observation.kind}</code></dd></div><div><dt>Reference Oracle:</dt><dd><code>{formatPrediction(artifact.reference_output)}</code></dd></div></dl>}
    <VerificationProcess report={report} artifact={artifact} diagnosticHidden={diagnosticHidden} />
  </section>;
}
type TraceProps = { trace: TraceExecutionReport | null; selectedIndex: number; onSelectIndex: (index: number) => void };
export function TraceScrubberPanel({ trace, selectedIndex, onSelectIndex }: TraceProps) {
  if (!trace) return null;
  const steps = trace.steps ?? [];
  const index = Math.max(0, Math.min(selectedIndex, Math.max(0, steps.length - 1)));
  const step = steps[index];
  return <section className="surface trace-panel" aria-label="Post-Line Trace Scrubber"><h2>Post-Line Execution Trace ({steps.length} retained / {trace.total_observed} observed)</h2><p>Status: {trace.status}</p>{(trace.status !== 'COMPLETED' || trace.trace_truncated) && <p role="status" className="notice">Trace Note: {trace.termination_reason}</p>}
    {step && <><div className="button-row"><button type="button" aria-label="Previous Trace Step" disabled={index === 0} onClick={() => onSelectIndex(index - 1)}>Prev</button><input aria-label="Trace Step Slider" type="range" min={0} max={steps.length - 1} value={index} onChange={event => onSelectIndex(Number(event.target.value))} /><button type="button" aria-label="Next Trace Step" disabled={index === steps.length - 1} onClick={() => onSelectIndex(index + 1)}>Next</button></div><div data-testid="trace-step-details" className="trace-details"><p><strong>Event #{step.event_id}:</strong> {step.event_kind} at Line <code>{step.source_line}</code> (Frame <code>{step.frame_id}</code>, Attribution: <code>{step.attribution_status}</code>)</p><p>Locals Snapshot: <code>{JSON.stringify(step.locals_snapshot ?? {})}</code></p></div></>}
  </section>;
}
type HintProps = { state: WorkbenchSessionState; onRequestHintLevel: (level: HintLevel) => void; onSelectTracePointer?: (event: number | null, line: number | null) => void; onPlayMessage?: (level: HintLevel) => void; replayableLevels?: readonly number[]; voiceEnabled?: boolean; isBusy?: boolean };
export function CoachingHintFeed({ state, onRequestHintLevel, onSelectTracePointer, onPlayMessage, replayableLevels = [], voiceEnabled = true, isBusy = false }: HintProps) {
  const highest = Math.max(0, ...state.coachingHistory.filter(item => !item.stale).map(item => item.hintLevel));
  return <section className="surface hint-panel" aria-label="Graduated Socratic Coaching Feed"><h2>A nudge, not the solution</h2><div className="button-row">{onPlayMessage ? ([1, 2, 3] as HintLevel[]).map(level => <button key={level} type="button" disabled={isBusy || state.editorDirty || state.diagnosticHidden || !state.activeArtifact || level !== highest + 1} onClick={() => onRequestHintLevel(level)}>Level {level} Hint</button>) : (state.activeArtifact && !state.editorDirty && !state.diagnosticHidden && highest < 3 && <button type="button" disabled={isBusy} onClick={() => onRequestHintLevel((highest + 1) as HintLevel)}>Level {highest + 1} Hint</button>)}</div>
    {state.editorDirty ? <p className="notice">Prior coaching is suppressed while the code buffer has unsaved edits. Save and rerun verification.</p> : state.diagnosticHidden ? <p>Predict and confirm the diagnostic before opening grounded hints.</p> : !state.coachingHistory.length ? <p className="muted">Confirm a prediction on the active challenge to unlock grounded Socratic hints.</p> : <ol>{state.coachingHistory.map((item, index) => <li key={`${index}-${item.hintLevel}`}><p><strong>[Level {item.hintLevel} — {item.sourceMode}]</strong> {item.displayText}{item.stale && ' (Superseded)'}</p>{onPlayMessage && <button type="button" disabled={isBusy || item.stale || !voiceEnabled || state.saveInFlight || !state.specAcknowledged || !state.activeArtifact || !state.activeTurnId || item.hintLevel < 1 || item.hintLevel > 3} onClick={() => onPlayMessage(item.hintLevel as HintLevel)}>{!item.stale && replayableLevels.includes(item.hintLevel) ? 'Replay message' : 'Play message'}</button>}{(item.pointedEventId !== null || item.pointedLine !== null) && <button type="button" disabled={item.stale || !state.activeTrace || !onSelectTracePointer} onClick={() => onSelectTracePointer?.(item.pointedEventId, item.pointedLine)}>{item.pointedEventId !== null ? `Inspect trace event ${item.pointedEventId}` : `Inspect trace line ${item.pointedLine}`}</button>}</li>)}</ol>}
  </section>;
}
type TransferProps = { state: WorkbenchSessionState; onIssueTransferChallenge: () => void; isBusy?: boolean };
export function FreshCaseTransferCard({ state, onIssueTransferChallenge, isBusy = false }: TransferProps) {
  const canTransfer = state.learningState === 'FRESH_CASE_CHECK' || state.learningState === 'FRESH_CASE_REVIEW';
  if (!canTransfer && state.learningState !== 'PRACTICE_CHECKPOINT_COMPLETED') return null;
  return <section className="surface transfer-panel" aria-label="Fresh Transfer Progression & Checkpoint"><h2>Fresh Held-Out Transfer Check</h2><button type="button" disabled={isBusy || state.editorDirty || state.saveInFlight || !canTransfer} onClick={onIssueTransferChallenge}>Load Held-Out Transfer Case</button><p>{state.learningState === 'PRACTICE_CHECKPOINT_COMPLETED' ? 'Practice checkpoint completed on a disjoint held-out transfer input — not proven mastery.' : state.learningState === 'FRESH_CASE_REVIEW' ? 'Review your prediction, then try the next unseen transfer input.' : 'After bounded verification, predict the output on a fresh held-out input not seen in diagnostic or search stages.'}</p></section>;
}
export function DiagnosticsDrawer({ state }: { state: WorkbenchSessionState }) {
  if (!state.diagnosticsOpen) return null;
  return <aside className="diagnostics-panel" aria-label="Speech & Sandbox Diagnostics Drawer"><h2>Operational &amp; Speech Gatekeeper Diagnostics</h2><p>Active UI View: <code>{state.activeView}</code> / Learning State: <code>{state.learningState}</code></p><p>Speech Degradation: <code>{state.speechDegradation}</code></p><p>Single-Concurrency Speech Dispatcher: SINGLE_PROCESS_LOCAL_SEMAPHORE (max_concurrency=1)</p><p>Tariff Status: UNKNOWN_UNVERIFIED_TARIFF</p></aside>;
}
