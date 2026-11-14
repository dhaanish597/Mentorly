"""Pure-stdlib in-sandbox post-line execution tracer (§9.4, R1 repaired).

Security & Packaging Contract (Review Finding R1):
- Zero imports from `backend.*` or `exec_worker.worker_app.*`.
- Uses ONLY the Python standard library (`collections.deque`, `dataclasses`,
  `hashlib`, `sys`, `types.FrameType`, `typing`) and `exec_worker.runner.safe_serializer`
  (`SerializationBudget`, `serialize_frame_locals`).
- Safe to execute inside the minimal `Dockerfile.runner` image containing ONLY
  `exec_worker/__init__.py` and `exec_worker/runner/`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import sys
from types import FrameType
from typing import Any, Callable

from exec_worker.runner.safe_serializer import (
    _safe_type_name,
    SerializationBudget,
    serialize_frame_locals,
)

LEARNER_FILENAME = "<learner_solution>"

EVENT_CALL = "CALL"
EVENT_LINE = "LINE"
EVENT_RETURN = "RETURN"
EVENT_EXCEPTION = "EXCEPTION"
EVENT_TRUNCATED = "TRUNCATED"

ATTR_ATTRIBUTED = "ATTRIBUTED"
ATTR_AMBIGUOUS = "AMBIGUOUS"
ATTR_UNAVAILABLE = "UNAVAILABLE"
ATTR_TAMPERED = "TAMPERED"

STATUS_COMPLETED = "COMPLETED"
STATUS_PARTIAL = "PARTIAL"
STATUS_TRACE_TIMEOUT = "TRACE_TIMEOUT"
STATUS_TRACE_UNAVAILABLE = "TRACE_UNAVAILABLE"
STATUS_TRACE_TAMPERED = "TRACE_TAMPERED"


@dataclass
class _PendingFrameState:
    frame_id: str
    parent_frame_id: str | None
    call_depth: int
    pending_line: int | None = None
    pending_event_kind: str = EVENT_LINE
    prev_pending_line: int | None = None


@dataclass(frozen=True)
class InSandboxTraceOutput:
    trace_status: str
    steps: list[dict[str, Any]]
    total_observed: int
    trace_truncated: bool
    termination_reason: str
    tampered: bool = False


class InSandboxTracer:
    """Best-effort post-line execution tracer using `sys.settrace` (§9.4)."""

    def __init__(
        self,
        *,
        source_code: str,
        source_hash: str | None = None,
        target_filename: str = LEARNER_FILENAME,
        max_trace_steps: int = 250,
        max_trace_snapshots_work: int = 2000,
        serialization_budget: SerializationBudget | None = None,
    ) -> None:
        self.source_code = source_code
        self.source_hash = (
            source_hash
            if (type(source_hash) is str and len(source_hash) == 64)
            else hashlib.sha256(source_code.encode("utf-8")).hexdigest()
        )
        self.target_filename = target_filename
        self.max_trace_steps = max(1, int(max_trace_steps))
        self.max_trace_snapshots_work = max(1, int(max_trace_snapshots_work))
        self.serialization_budget = serialization_budget or SerializationBudget()

        if self.max_trace_steps >= 250:
            self.head_capacity = self.max_trace_steps - 50
            self.tail_capacity = 50
        elif self.max_trace_steps > 2:
            self.head_capacity = (self.max_trace_steps * 4) // 5
            self.tail_capacity = self.max_trace_steps - self.head_capacity
        else:
            self.head_capacity = self.max_trace_steps
            self.tail_capacity = 0

        self._head_steps: list[dict[str, Any]] = []
        self._tail_steps: deque[dict[str, Any]] = (
            deque(maxlen=self.tail_capacity) if self.tail_capacity > 0 else deque()
        )

        self.total_observed: int = 0
        self.snapshots_work_done: int = 0
        self.work_cap_reached: bool = False
        self.tampered: bool = False
        self.tamper_reason: str | None = None

        self._next_frame_seq: int = 0
        self._frame_states: dict[int, _PendingFrameState] = {}
        self._active_frame_stack: list[str] = []

        self._trace_hook = self._trace_dispatch

    def _allocate_frame_state(self, frame: FrameType) -> _PendingFrameState:
        self._next_frame_seq += 1
        frame_id = f"f{self._next_frame_seq}"
        parent_frame_id: str | None = None
        call_depth = 1

        caller = frame.f_back
        if caller is not None and id(caller) in self._frame_states:
            parent_state = self._frame_states[id(caller)]
            parent_frame_id = parent_state.frame_id
            call_depth = parent_state.call_depth + 1
        elif self._active_frame_stack:
            parent_frame_id = self._active_frame_stack[-1]
            call_depth = len(self._active_frame_stack) + 1

        state = _PendingFrameState(
            frame_id=frame_id,
            parent_frame_id=parent_frame_id,
            call_depth=call_depth,
        )
        self._frame_states[id(frame)] = state
        self._active_frame_stack.append(frame_id)
        return state

    def _append_step(self, step: dict[str, Any]) -> None:
        if len(self._head_steps) < self.head_capacity:
            self._head_steps.append(step)
        elif self.tail_capacity > 0:
            self._tail_steps.append(step)

    def _record_step(
        self,
        *,
        state: _PendingFrameState,
        source_line: int,
        event_kind: str,
        attribution_status: str,
        frame: FrameType,
        extra_truncated: list[str] | None = None,
    ) -> None:
        if self.work_cap_reached:
            return

        if self.snapshots_work_done >= self.max_trace_snapshots_work:
            self.work_cap_reached = True
            return

        self.snapshots_work_done += 1
        event_id = self.total_observed
        self.total_observed += 1

        locals_snapshot, truncated_values = serialize_frame_locals(
            frame.f_locals,
            self.serialization_budget,
        )
        if extra_truncated:
            for item in extra_truncated:
                if item not in truncated_values:
                    truncated_values.append(item)

        step: dict[str, Any] = {
            "event_id": event_id,
            "frame_id": state.frame_id,
            "parent_frame_id": state.parent_frame_id,
            "call_depth": state.call_depth,
            "source_hash": self.source_hash,
            "source_line": max(1, int(source_line)),
            "event_kind": event_kind,
            "attribution_status": attribution_status,
            "locals_snapshot": locals_snapshot,
            "truncated_values": truncated_values,
        }
        self._append_step(step)

    def _flush_pending_line(
        self,
        state: _PendingFrameState,
        frame: FrameType,
        *,
        next_event: str,
        next_line: int,
    ) -> None:
        if state.pending_line is None or self.work_cap_reached:
            return

        executed_line = state.pending_line
        attribution = ATTR_ATTRIBUTED
        if next_event == "exception":
            attribution = ATTR_AMBIGUOUS

        self._record_step(
            state=state,
            source_line=executed_line,
            event_kind=EVENT_LINE,
            attribution_status=attribution,
            frame=frame,
        )
        state.prev_pending_line = executed_line
        state.pending_line = None

    def _trace_dispatch(
        self, frame: FrameType, event: str, arg: Any
    ) -> Callable[..., Any] | None:
        if self.work_cap_reached or self.tampered:
            return None

        code_obj = frame.f_code
        if code_obj.co_filename != self.target_filename:
            return None

        if frame.f_trace is not None and frame.f_trace != self._trace_hook:
            self.tampered = True
            self.tamper_reason = "Learner frame modified frame.f_trace"
            return None

        if event == "call":
            state = self._allocate_frame_state(frame)
            self._record_step(
                state=state,
                source_line=max(1, frame.f_lineno),
                event_kind=EVENT_CALL,
                attribution_status=ATTR_ATTRIBUTED,
                frame=frame,
            )
            return self._trace_hook

        state = self._frame_states.get(id(frame))
        if state is None:
            state = self._allocate_frame_state(frame)

        if event == "line":
            if state.pending_line is not None:
                self._flush_pending_line(
                    state,
                    frame,
                    next_event="line",
                    next_line=frame.f_lineno,
                )
                if self.work_cap_reached:
                    return None
            state.pending_line = max(1, frame.f_lineno)
            state.pending_event_kind = EVENT_LINE
            return self._trace_hook

        if event == "return":
            if state.pending_line is not None:
                self._flush_pending_line(
                    state,
                    frame,
                    next_event="return",
                    next_line=frame.f_lineno,
                )
            if not self.work_cap_reached:
                self._record_step(
                    state=state,
                    source_line=max(1, frame.f_lineno),
                    event_kind=EVENT_RETURN,
                    attribution_status=ATTR_ATTRIBUTED,
                    frame=frame,
                )
            self._pop_frame_state(frame, state)
            return self._trace_hook

        if event == "exception":
            exc_line = state.pending_line or max(1, frame.f_lineno)
            state.pending_line = None
            if not self.work_cap_reached:
                self._record_step(
                    state=state,
                    source_line=exc_line,
                    event_kind=EVENT_EXCEPTION,
                    attribution_status=ATTR_AMBIGUOUS,
                    frame=frame,
                )
            return self._trace_hook

        return self._trace_hook

    def _pop_frame_state(self, frame: FrameType, state: _PendingFrameState) -> None:
        self._frame_states.pop(id(frame), None)
        if self._active_frame_stack and self._active_frame_stack[-1] == state.frame_id:
            self._active_frame_stack.pop()
        elif state.frame_id in self._active_frame_stack:
            self._active_frame_stack.remove(state.frame_id)

    def mark_tampered(self, reason: str, frame: FrameType | None = None) -> None:
        self.tampered = True
        self.tamper_reason = reason
        if self._tail_steps:
            self._tail_steps[-1]["attribution_status"] = ATTR_TAMPERED
        elif self._head_steps:
            self._head_steps[-1]["attribution_status"] = ATTR_TAMPERED
        else:
            event_id = self.total_observed
            self.total_observed += 1
            line_no = max(1, frame.f_lineno) if frame is not None else 1
            self._append_step(
                {
                    "event_id": event_id,
                    "frame_id": "f1",
                    "parent_frame_id": None,
                    "call_depth": 1,
                    "source_hash": self.source_hash,
                    "source_line": line_no,
                    "event_kind": EVENT_TRUNCATED,
                    "attribution_status": ATTR_TAMPERED,
                    "locals_snapshot": {},
                    "truncated_values": ["trace_tampered"],
                }
            )

    def run_traced_callable(
        self, fn: Callable[..., Any], kwargs: dict[str, Any]
    ) -> tuple[str, Any, BaseException | None, InSandboxTraceOutput]:
        previous_trace = sys.gettrace()
        exc_caught: BaseException | None = None
        ret_val: Any = None
        outcome_kind = "RETURN"

        sys.settrace(self._trace_hook)
        try:
            ret_val = fn(**kwargs)
        except BaseException as exc:
            exc_caught = exc
            outcome_kind = "EXCEPTION"
        finally:
            active_trace_after = sys.gettrace()
            sys.settrace(previous_trace)

            if not self.work_cap_reached and active_trace_after != self._trace_hook:
                self.mark_tampered(
                    "Learner code disabled or replaced sys.settrace() during execution"
                )

        trace_output = self.build_output(outcome_kind=outcome_kind, exc=exc_caught)
        return outcome_kind, ret_val, exc_caught, trace_output

    def build_output(
        self,
        *,
        outcome_kind: str = "RETURN",
        exc: BaseException | None = None,
    ) -> InSandboxTraceOutput:
        retained = list(self._head_steps) + list(self._tail_steps)
        trace_truncated = (
            self.total_observed > len(retained) or self.work_cap_reached
        )

        if self.tampered:
            status = STATUS_TRACE_TAMPERED
            reason = (
                self.tamper_reason
                or "Learner code tampered with or disabled sys.settrace()"
            )
        elif outcome_kind == "TIMEOUT":
            status = STATUS_TRACE_TIMEOUT
            reason = "Trace invocation exceeded configured time limit"
        elif self.work_cap_reached:
            status = STATUS_PARTIAL
            reason = (
                f"Reached max_trace_snapshots_work ({self.max_trace_snapshots_work}); "
                f"retained {len(retained)} of {self.total_observed} steps"
            )
        elif trace_truncated:
            status = STATUS_PARTIAL
            reason = (
                f"Retained {len(retained)} of {self.total_observed} observed steps "
                f"(first {self.head_capacity} + last {len(self._tail_steps)} ring buffer)"
            )
        elif exc is not None:
            status = STATUS_COMPLETED
            reason = f"Traced execution terminated with {_safe_type_name(exc)}"
        else:
            status = STATUS_COMPLETED
            reason = f"Completed trace capture ({self.total_observed} steps observed)"

        return InSandboxTraceOutput(
            trace_status=status,
            steps=retained,
            total_observed=self.total_observed,
            trace_truncated=trace_truncated,
            termination_reason=reason[:256],
            tampered=self.tampered,
        )


__all__ = [
    "ATTR_AMBIGUOUS",
    "ATTR_ATTRIBUTED",
    "ATTR_TAMPERED",
    "ATTR_UNAVAILABLE",
    "EVENT_CALL",
    "EVENT_EXCEPTION",
    "EVENT_LINE",
    "EVENT_RETURN",
    "EVENT_TRUNCATED",
    "InSandboxTraceOutput",
    "InSandboxTracer",
    "LEARNER_FILENAME",
    "STATUS_COMPLETED",
    "STATUS_PARTIAL",
    "STATUS_TRACE_TAMPERED",
    "STATUS_TRACE_TIMEOUT",
    "STATUS_TRACE_UNAVAILABLE",
]
