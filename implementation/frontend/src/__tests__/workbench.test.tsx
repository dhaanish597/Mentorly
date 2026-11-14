/**
 * Vitest Workbench & 13-View State Suite (`frontend/src/__tests__/workbench.test.tsx`).
 */

import { describe, expect, it } from 'vitest';
import {
  ALL_WORKBENCH_VIEWS,
  applyEditorBufferChange,
  applyRerecordCaptureAttempt,
  createInitialWorkbenchState,
  resolveActiveWorkbenchView,
} from '../state/useSessionStore';

describe('Phase 5 & Phase 7 Workbench State & 13 UI Views', () => {
  it('defines all 13 canonical UI views and resolves state transitions accurately', () => {
    expect(ALL_WORKBENCH_VIEWS).toHaveLength(13);

    const initial = createInitialWorkbenchState();
    expect(resolveActiveWorkbenchView(initial)).toBe('EXPLAIN_APPROACH_TURN');

    const unacked = {
      ...initial,
      specVersion: 'v2_negatives_allowed' as const,
      specAcknowledged: false,
      sessionState: 'SPEC_ACK_REQUIRED' as const,
    };
    expect(resolveActiveWorkbenchView(unacked)).toBe('DOMAIN_SHIFT_ACK_GATE');

    const checkpoint = {
      ...initial,
      learningState: 'PRACTICE_CHECKPOINT_COMPLETED' as const,
    };
    expect(resolveActiveWorkbenchView(checkpoint)).toBe('PRACTICE_CHECKPOINT_SUMMARY');
  });

  it('marks prior coaching feedback stale immediately when the editor buffer becomes dirty', () => {
    const base = {
      ...createInitialWorkbenchState(),
      sourceCode: 'def f(): return 0\n',
      persistedSourceCode: 'def f(): return 0\n',
      coachingHistory: [
        {
          hintLevel: 1,
          displayText: 'Check line 1.',
          pointedLine: 1,
          pointedEventId: 0,
          sourceMode: 'DETERMINISTIC_TEMPLATE',
          stale: false,
        },
      ],
    };

    const edited = applyEditorBufferChange(base, 'def f(): return 1\n');
    expect(edited.editorDirty).toBe(true);
    expect(edited.clientEditSequence).toBe(1);
    expect(edited.coachingHistory[0].stale).toBe(true);
  });

  it('increments captureAttemptId on re-record without incrementing turnGeneration', () => {
    const base = createInitialWorkbenchState();
    expect(base.turnGeneration).toBe(1);
    expect(base.captureAttemptId).toBe(0);

    const attempt1 = applyRerecordCaptureAttempt(base);
    expect(attempt1.turnGeneration).toBe(1);
    expect(attempt1.captureAttemptId).toBe(1);

    const attempt2 = applyRerecordCaptureAttempt(attempt1);
    expect(attempt2.turnGeneration).toBe(1);
    expect(attempt2.captureAttemptId).toBe(2);
  });
});
