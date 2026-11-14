import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CoachActionFooter, LearningStepIndicator, ProblemConstraintPanel, VoiceCaptureControls, VoiceTurnPanel } from '../components/WorkbenchComponents';
import { createInitialWorkbenchState } from '../state/useSessionStore';
import type { ExerciseMetadata } from '../types/api';

const base = createInitialWorkbenchState();
const proposal = { claim_type: 'INVARIANT_OR_MECHANISM_CLAIM' as const, mechanism_summary: 'The boundary stays sorted', extraction_method: 'DETERMINISTIC' as const };
const ready = { ...base, sessionId: 'session', revision: { session_id: 'session', exercise_id: base.exerciseId, spec_version: base.specVersion, code_hash: 'hash', code_version_id: 1, turn_generation: 1 }, activeTurnId: 'turn', proposedClaim: proposal };
afterEach(cleanup);
describe('Pinned coach actions', () => {
  it('holds the single real confirmation and audio controls outside scrollable content', () => {
    render(<aside className="coach-pane"><div className="coach-scroll"><VoiceTurnPanel state={ready} onSubmitTranscript={vi.fn()} onStartOrRerecordVoice={vi.fn()} onBargeInStop={vi.fn()} onChangeEditableTranscript={vi.fn()} onConfirmClaimAndExecute={vi.fn()} /></div><CoachActionFooter state={ready} busy={false} onConfirm={vi.fn()} onAbstain={vi.fn()}><VoiceCaptureControls state={ready} recording={false} textOnly={false} busy={false} onMicrophone={vi.fn()} onStop={vi.fn()} /></CoachActionFooter></aside>);
    const actions = screen.getByRole('group', { name: 'Coach actions' });
    expect(within(actions).getByRole('button', { name: 'Confirm Explanation (No Execution)' })).toBeEnabled();
    expect(within(actions).getByRole('button', { name: 'Stop / Barge-In' })).toBeEnabled();
    expect(screen.getAllByTestId('confirm-claim-btn')).toHaveLength(1);
    expect(actions.closest('.coach-scroll')).toBeNull();
  });
  it.each([{ editorDirty: true }, { specAcknowledged: false }, { saveInFlight: true }])('preserves confirmation gates for %j', patch => {
    render(<CoachActionFooter state={{ ...ready, ...patch }} busy={false} onConfirm={vi.fn()} onAbstain={vi.fn()} />);
    expect(screen.getByTestId('confirm-claim-btn')).toBeDisabled();
  });
  it('keeps audio stop active while busy but disallows confirmation', () => {
    render(<CoachActionFooter state={ready} busy onConfirm={vi.fn()} onAbstain={vi.fn()}><VoiceCaptureControls state={ready} recording={true} textOnly={false} busy onMicrophone={vi.fn()} onStop={vi.fn()} /></CoachActionFooter>);
    expect(screen.getByTestId('confirm-claim-btn')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Stop / Barge-In' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Done speaking' })).toBeEnabled();
  });
  it('derives the active step without presenting earlier steps as completed', () => {
    const { rerender } = render(<LearningStepIndicator state={base} />);
    expect(screen.getByText('Explain').closest('li')).toHaveAttribute('aria-current', 'step');
    rerender(<LearningStepIndicator state={{ ...base, learningState: 'VERIFYING' }} />);
    expect(screen.getByText('Run').closest('li')).toHaveAttribute('aria-current', 'step');
    rerender(<LearningStepIndicator state={{ ...base, learningState: 'FRESH_CASE_CHECK' }} />);
    expect(screen.getByText('Transfer').closest('li')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByRole('list', { name: 'Learning steps' })).not.toHaveTextContent('Completed');
  });
  it('formats bounded typed constraints into readable sentences, not schema JSON', () => {
    const exercise: ExerciseMetadata = { exercise_id: base.exerciseId, title: 'Bounded search', function_name: 'solve', difficulty: 'beginner', core_concepts: [], description: 'Find the boundary.', starter_code: '', default_spec_version: base.specVersion, comparator: 'strict_structural', catalog_status: 'READY', spec_versions: [{ spec_version: base.specVersion, label: 'Bounded', min_length: 0, max_length: 12, min_value: -5, max_value: 5, sorted_required: true, constraints_summary: ['nums: {"kind":"list","minimum":-5}'], input_schema: { nums: { kind: 'list', min_length: 0, max_length: 12, sorted_required: true, items: { kind: 'integer', minimum: -5, maximum: 5 } }, target: { kind: 'integer', minimum: -10, maximum: 10 } }, output_schema: { kind: 'boolean' } }] };
    render(<ProblemConstraintPanel exercise={exercise} state={base} onAcknowledgeSpec={vi.fn()} />);
    expect(screen.getByText(/nums:.*0 to 12.*integers/)).toBeInTheDocument();
    expect(screen.getByText(/non-decreasing/)).toBeInTheDocument();
    expect(screen.getByText(/target:.*-10 to 10/)).toBeInTheDocument();
    expect(screen.getByText(/Return true or false/)).toBeInTheDocument();
    expect(screen.queryByText(/"kind"/)).not.toBeInTheDocument();
  });
});
