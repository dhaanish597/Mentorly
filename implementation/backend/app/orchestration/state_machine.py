"""Coordinator State Machine & Coaching Loop Orchestrator (`backend/app/orchestration/state_machine.py`).

Implements Plan §7.1–§7.4 (Phases P3, P4, P5, P7):
- Enforces server-owned immutable `Challenge` bound to `RevisionRef` and `case_hash`.
- Keeps reference outputs, actual execution observations, and traces strictly hidden (`RevealState.HIDDEN`)
  until the learner confirms their prediction (`confirm_claim_and_execute`).
- Enforces `v2_negatives_allowed` domain acknowledgement gate (`SPEC_ACK_REQUIRED` -> `READY`).
- Reuses the current logical turn (`turn_generation` unchanged) with monotonic `capture_attempt_id`
  when re-recording on the active challenge, while advancing `turn_generation` on a new turn.
- Enforces disjoint `TRANSFER` case selection excluding `case_history` and static `curriculum` cases.
- Evaluates `PredictionStatus` (`MATCH` vs `MISMATCH`) independently of `VerificationStatus`
  (`NO_FAILURE_FOUND` vs `COUNTEREXAMPLE_CONFIRMED` vs `VERIFICATION_INCOMPLETE`), supporting:
  - Buggy code -> `REPAIR_REQUIRED`
  - Correct code + wrong prediction -> `PREDICTION_REVIEW`
  - Correct code (including initially-correct starter code) + matching prediction -> `FRESH_CASE_CHECK`
  - Passing fresh transfer prediction -> `PRACTICE_CHECKPOINT_COMPLETED` (never "proven mastery").
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

try:
    from backend.app.db.repository import (
        RevisionConflictError,
        SQLiteRepository,
    )
    from backend.app.exercises import registry as exercise_registry
    from backend.app.models.domain import (
        Challenge,
        ClaimInterpretation,
        EvidenceArtifact,
        ExecutionBudgetConfig,
        ExecutionObservation,
        ExecutionRequest,
        HiddenEvidenceArtifactView,
        OutputPredictionClaim,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from backend.app.models.enums import (
        ChallengePurpose,
        ExecutionObservationKind,
        ExerciseId,
        InteractionMode,
        LanguageMode,
        LearningState,
        MinimizationStatus,
        PlaybackStatus,
        PredictionStatus,
        RevealState,
        SessionState,
        SpecVersion,
        TurnState,
        VerificationStatus,
    )
    from backend.app.speech.ast_keyterms import extract_bias_keyterms
except ImportError:  # pragma: no cover
    from app.db.repository import (  # type: ignore[no-redef]
        RevisionConflictError,
        SQLiteRepository,
    )
    from app.exercises import registry as exercise_registry  # type: ignore[no-redef]
    from app.models.domain import (  # type: ignore[no-redef]
        Challenge,
        ClaimInterpretation,
        EvidenceArtifact,
        ExecutionBudgetConfig,
        ExecutionObservation,
        ExecutionRequest,
        HiddenEvidenceArtifactView,
        OutputPredictionClaim,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ChallengePurpose,
        ExecutionObservationKind,
        ExerciseId,
        InteractionMode,
        LanguageMode,
        LearningState,
        MinimizationStatus,
        PlaybackStatus,
        PredictionStatus,
        RevealState,
        SessionState,
        SpecVersion,
        TurnState,
        VerificationStatus,
    )
    from app.speech.ast_keyterms import extract_bias_keyterms  # type: ignore[no-redef]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CoordinatorStateMachine:
    """Authoritative coordinator state machine for Voice Coding Coach."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        worker_client: Any = None,
        coach_engine: Any = None,
        speech_gatekeeper: Any = None,
    ) -> None:
        self.repo = repository
        self.worker_client = worker_client
        self.coach_engine = coach_engine
        self.speech_gatekeeper = speech_gatekeeper

    def build_revision_ref(self, session_id: str) -> RevisionRef:
        s_rec = self.repo.get_session(session_id)
        if s_rec is None:
            raise KeyError(f"Session not found: {session_id}")
        cv_rec = self.repo.get_code_version(session_id, s_rec.active_code_version_id)
        code_hash = cv_rec.code_hash if cv_rec else ("0" * 64)
        return RevisionRef(
            session_id=UUID(s_rec.id),
            exercise_id=ExerciseId(s_rec.exercise_id),
            spec_version=SpecVersion(s_rec.spec_version),
            code_version_id=s_rec.active_code_version_id,
            code_hash=code_hash,
            turn_generation=s_rec.active_turn_generation,
        )

    def assert_revision_matches(self, session_id: str, expected: RevisionRef) -> RevisionRef:
        current = self.build_revision_ref(session_id)
        if (
            current.session_id != expected.session_id
            or current.turn_generation != expected.turn_generation
            or current.exercise_id != expected.exercise_id
            or current.spec_version != expected.spec_version
            or current.code_version_id != expected.code_version_id
            or current.code_hash != expected.code_hash
        ):
            raise RevisionConflictError(
                "Revision mismatch against active session state",
                expected=expected.model_dump(mode="json"),
                actual=current.model_dump(mode="json"),
            )
        return current

    def issue_challenge(
        self,
        session_id: str,
        *,
        purpose: ChallengePurpose,
        expected_revision: RevisionRef,
        requested_input: dict[str, Any] | None = None,
    ) -> Challenge:
        """Issue a deeply immutable server-owned `Challenge` (`DIAGNOSTIC` or `TRANSFER`) with `reveal_state=HIDDEN`."""
        s_rec = self.repo.get_session(session_id)
        if s_rec is None:
            raise KeyError(f"Session not found: {session_id}")
        if not s_rec.spec_acknowledged or s_rec.state == SessionState.SPEC_ACK_REQUIRED.value:
            raise RevisionConflictError("Domain specification change must be acknowledged before issuing a challenge.")

        rev = self.assert_revision_matches(session_id, expected_revision)
        ex_id = str(rev.exercise_id.value)
        spec_ver = str(rev.spec_version.value)
        used_hashes = self.repo.get_used_case_hashes(session_id, ex_id, spec_ver)

        selected_input: dict[str, Any] | None = None
        if purpose == ChallengePurpose.TRANSFER:
            history = self.repo.export_session_bundle(session_id)["evidence_artifacts"]
            ready = any(a["revision"]["code_version_id"] == rev.code_version_id
                and a["revision"]["code_hash"] == rev.code_hash
                and a["revision"]["spec_version"] == rev.spec_version.value
                and a["prediction_status"] == "MATCH"
                and a["verification_report"]["status"] == "NO_FAILURE_FOUND"
                for a in history)
            if not ready and not self._completed_verification_allows_transfer(session_id,rev):
                raise RevisionConflictError('Complete bounded verification for this code revision before transfer.')
            # Transfer cases MUST come from the disjoint holdout pool and never reuse any session case
            holdouts = exercise_registry.cases(ex_id, spec_ver, "holdout")
            for cand in holdouts:
                validated = exercise_registry.validate_input(ex_id, spec_ver, cand)
                h = exercise_registry.case_key(ex_id, spec_ver, validated)
                if h not in used_hashes:
                    selected_input = validated
                    break
            if selected_input is None:
                from backend.app.orchestration.lifecycle_errors import TransferUnavailableError
                raise TransferUnavailableError('No unseen transfer case remains. Start another practice session.')
        else:
            if requested_input is not None:
                validated = exercise_registry.validate_input(ex_id, spec_ver, requested_input)
                # Ensure diagnostic requested_input is not a reserved holdout
                holdout_hashes = {
                    exercise_registry.case_key(ex_id, spec_ver, hc)
                    for hc in exercise_registry.cases(ex_id, spec_ver, "holdout")
                }
                h = exercise_registry.case_key(ex_id, spec_ver, validated)
                if h in holdout_hashes:
                    raise ValueError("Diagnostic challenge cannot use a reserved transfer holdout input.")
                selected_input = validated
            else:
                curated = exercise_registry.cases(ex_id, spec_ver, "curriculum")
                for cand in curated:
                    validated = exercise_registry.validate_input(ex_id, spec_ver, cand)
                    h = exercise_registry.case_key(ex_id, spec_ver, validated)
                    if h not in used_hashes:
                        selected_input = validated
                        break
                if selected_input is None and curated:
                    selected_input = exercise_registry.validate_input(ex_id, spec_ver, curated[0])

        assert selected_input is not None
        c_hash = exercise_registry.case_key(ex_id, spec_ver, selected_input)
        now = _utc_now()
        exp = now + timedelta(hours=24)
        cid = uuid4()
        published = self.repo.publish_challenge(
            session_id, expected_revision=rev, challenge_id=str(cid), input_args=selected_input,
            purpose=purpose.value, created_at=now.isoformat(), expires_at=exp.isoformat(),
        )
        return Challenge.model_validate(published)

    def confirm_claim_and_execute(
        self,
        session_id: str,
        *,
        turn_id: str | None,
        challenge_id: UUID | None,
        expected_revision: RevisionRef,
        claim: ClaimInterpretation,
        capture_attempt_id: int | None = None,
    ) -> dict[str, Any]:
        """Confirm a learner's claim/prediction, reveal the challenge, execute in isolation, and transition learning state."""
        rev = self.assert_revision_matches(session_id, expected_revision)
        if not isinstance(claim, OutputPredictionClaim):
            if turn_id is None or claim.confirmed_at is None or capture_attempt_id is None:
                raise RevisionConflictError('Explanation confirmation requires a current captured claim identity')
            turn = self.repo.get_turn(session_id,turn_id)
            if turn is None or (challenge_id is not None and str(challenge_id) != turn.challenge_id) or (claim.challenge_id is not None and str(claim.challenge_id) != turn.challenge_id):
                raise RevisionConflictError('Explanation does not bind this turn')
            self.repo.confirm_turn_claim(session_id, revision=rev, challenge_id=turn.challenge_id,
                turn_id=turn_id, claim_json=claim.model_dump_json(), capture_attempt_id=capture_attempt_id, reveal=False)
            session = self.repo.get_session(session_id)
            return {'turn_id':turn_id, 'revision':rev.model_dump(mode='json'), 'proposed_claim':claim.model_dump(mode='json'),
                'session_state':session.state, 'learning_state':session.learning_state, 'executed':False,
                'requires_prediction':True, 'coaching':{'display_text':'Your explanation is recorded. Predict the output on an input before we execute it.',
                'speakable_text':'Predict the output on an input before we execute it.'}}
        if challenge_id is None:
            raise RevisionConflictError('Output predictions require a matching challenge identity')
        c_dict = self.repo.get_challenge(session_id, str(challenge_id))
        if c_dict is None:
            raise KeyError(f"Challenge not found: {challenge_id}")
        if (c_dict["session_id"] != str(rev.session_id)
            or c_dict["exercise_id"] != rev.exercise_id.value
            or c_dict["spec_version"] != rev.spec_version.value
            or c_dict["turn_generation"] != rev.turn_generation
            or c_dict["code_version_id"] != rev.code_version_id
            or c_dict["code_hash"] != rev.code_hash):
            raise RevisionConflictError("Challenge is bound to an older code revision.")

        if claim.challenge_id != challenge_id or claim.confirmed_at is None:
            raise RevisionConflictError("The confirmed claim must bind this challenge.")
        if c_dict["reveal_state"] != "HIDDEN":
            raise RevisionConflictError("Challenge was already confirmed; request a fresh challenge.")
        if datetime.fromisoformat(c_dict["expires_at"]) <= _utc_now():
            raise RevisionConflictError("Challenge expired")
        if turn_id is not None:
            turn = self.repo.get_turn(session_id, turn_id)
            if turn is None or turn.challenge_id != str(challenge_id) or turn.turn_generation != rev.turn_generation:
                raise RevisionConflictError("Turn does not bind this challenge")
        ex_id = str(rev.exercise_id.value)
        spec_ver = str(rev.spec_version.value)
        exercise_registry.validate_prediction(ex_id, spec_ver, claim.predicted_output)
        canonical_input = exercise_registry.validate_input(ex_id, spec_ver, c_dict["input_args"])
        expected_case_hash = exercise_registry.case_key(ex_id, spec_ver, canonical_input)
        if expected_case_hash != c_dict["case_hash"]:
            raise ValueError("Challenge case_hash integrity check failed.")

        turn = self.repo.confirm_turn_claim(session_id, revision=rev, challenge_id=str(challenge_id),
            turn_id=turn_id, claim_json=claim.model_dump_json(), capture_attempt_id=capture_attempt_id)
        return self._execute_confirmed_claim(session_id, rev=rev, c_dict=c_dict, claim=claim, turn_id=turn.id)

    def retry_execution(self, session_id: str, *, turn_id: str, expected_revision: RevisionRef) -> dict[str, Any]:
        rev = self.assert_revision_matches(session_id, expected_revision)
        turn = self.repo.begin_execution_retry(session_id,turn_id,rev)
        claim = OutputPredictionClaim.model_validate_json(turn.claim_json)
        c_dict = self.repo.get_challenge(session_id,turn.challenge_id)
        return self._execute_confirmed_claim(session_id,rev=rev,c_dict=c_dict,claim=claim,turn_id=turn.id)

    def _execute_confirmed_claim(self, session_id: str, *, rev: RevisionRef, c_dict: dict,
                                 claim: OutputPredictionClaim, turn_id: str) -> dict[str, Any]:
        challenge_id = UUID(c_dict['challenge_id'])
        ex_id, spec_ver = rev.exercise_id.value, rev.spec_version.value
        canonical_input = exercise_registry.validate_input(ex_id,spec_ver,c_dict['input_args'])
        expected_case_hash = exercise_registry.case_key(ex_id,spec_ver,canonical_input)
        cv_rec = self.repo.get_code_version(session_id, rev.code_version_id)
        source_code = cv_rec.source_code if cv_rec else ""
        ref_output = exercise_registry.evaluate(ex_id, spec_ver, deepcopy(canonical_input))

        obs, ver_report, trace_report = self._run_isolated_verification_and_trace(
            rev=rev,
            challenge_id=challenge_id,
            source_code=source_code,
            canonical_input=canonical_input,
            case_hash=expected_case_hash,
            reference_output=ref_output,
        )

        self.assert_revision_matches(session_id, rev)
        if trace_report is not None and (trace_report.revision != rev or trace_report.case_hash != expected_case_hash):
            self.repo.record_session_event(session_id,'TRACE_UNAVAILABLE',{
                'revision':rev.model_dump(mode='json'),'reason':'Worker trace did not bind the predicted input.'})
            trace_report = None
        for used_hash in ver_report.executed_case_hashes:
            self.repo.record_case_history(session_id, ex_id, spec_ver, used_hash, "SEARCH")
        confirmed_pred: object | None = None
        pred_status = PredictionStatus.NOT_EVALUATED
        if isinstance(claim, OutputPredictionClaim):
            confirmed_pred = deepcopy(claim.predicted_output)
            if obs.kind == ExecutionObservationKind.RETURN and obs.return_value is not None:
                # Independent prediction check: does the learner accurately predict what their current code outputs, or what the spec outputs?
                # Plan §4 & §7.2: Prediction correctness compares the learner's predicted output for their program on this input against actual/oracle.
                pred_status = (
                    PredictionStatus.MATCH
                    if exercise_registry.compare_output(confirmed_pred, obs.return_value)
                    else PredictionStatus.MISMATCH
                )
            else:
                pred_status = PredictionStatus.NOT_EVALUATED

        artifact_id = uuid4()
        trace_uuid = trace_report.trace_id if trace_report else None
        if trace_report is not None:
            self.repo.save_trace_report(
                trace_id=str(trace_report.trace_id),
                session_id=session_id,
                code_version_id=rev.code_version_id,
                turn_generation=rev.turn_generation,
                case_hash=expected_case_hash,
                status=trace_report.status.value,
                total_observed=trace_report.total_observed,
                trace_truncated=trace_report.trace_truncated,
                termination_reason=trace_report.termination_reason,
                runtime_version=trace_report.runtime_version,
                steps_json=json.dumps([s.model_dump(mode="json") for s in trace_report.steps]),
                observation_json=obs.model_dump_json(),
                revision=rev, challenge_id=str(challenge_id),
            )

        artifact = EvidenceArtifact(
            artifact_id=artifact_id,
            revision=rev,
            challenge_id=challenge_id,
            canonical_input=deepcopy(canonical_input),
            case_hash=expected_case_hash,
            confirmed_prediction=confirmed_pred,
            actual_observation=obs,
            reference_output=ref_output,
            prediction_status=pred_status,
            verification_report=ver_report,
            trace_id=trace_uuid,
            minimization_status=ver_report.minimization_status,
            timings_ms={"execution_ms": obs.duration_ms},
        )
        self.repo.save_artifact(
            artifact_id=str(artifact_id),
            session_id=session_id,
            challenge_id=str(challenge_id),
            code_version_id=rev.code_version_id,
            turn_generation=rev.turn_generation,
            case_hash=expected_case_hash,
            confirmed_prediction=confirmed_pred,
            prediction_status=pred_status.value,
            verification_status=ver_report.status.value,
            minimization_status=artifact.minimization_status.value,
            artifact_json=artifact.model_dump_json(),
            trace_id=str(trace_uuid) if trace_uuid else None,
        )

        # Determine next LearningState (§7.2)
        purpose = ChallengePurpose(c_dict["purpose"])
        code_matches_oracle_on_case = (
            obs.kind == ExecutionObservationKind.RETURN
            and exercise_registry.compare_output(obs.return_value, ref_output)
        )
        if purpose == ChallengePurpose.TRANSFER:
            if ((obs.kind == ExecutionObservationKind.RETURN and not code_matches_oracle_on_case)
                or ver_report.status in (VerificationStatus.COUNTEREXAMPLE_CONFIRMED, VerificationStatus.EXECUTION_ERROR,
                    VerificationStatus.TIMEOUT, VerificationStatus.SYNTAX_ERROR)):
                next_learning = LearningState.REPAIR_REQUIRED
            elif pred_status == PredictionStatus.MISMATCH:
                next_learning = LearningState.PREDICTION_REVIEW
            elif obs.kind == ExecutionObservationKind.UNAVAILABLE or ver_report.status == VerificationStatus.EXECUTION_UNAVAILABLE:
                next_learning = LearningState.INSPECTING_RESULT
            elif (
                code_matches_oracle_on_case
                and ver_report.status == VerificationStatus.NO_FAILURE_FOUND
                and exercise_registry.compare_output(confirmed_pred, ref_output)
            ):
                next_learning = LearningState.PRACTICE_CHECKPOINT_COMPLETED
            else:
                next_learning = LearningState.FRESH_CASE_REVIEW
        else:
            if (
                (obs.kind == ExecutionObservationKind.RETURN and not code_matches_oracle_on_case)
                or ver_report.status
                in (
                    VerificationStatus.COUNTEREXAMPLE_CONFIRMED,
                    VerificationStatus.EXECUTION_ERROR,
                    VerificationStatus.TIMEOUT,
                    VerificationStatus.SYNTAX_ERROR,
                )
            ):
                next_learning = LearningState.REPAIR_REQUIRED
            elif pred_status == PredictionStatus.MISMATCH:
                next_learning = LearningState.PREDICTION_REVIEW
            elif ver_report.status == VerificationStatus.NO_FAILURE_FOUND:
                next_learning = LearningState.FRESH_CASE_CHECK
            else:
                next_learning = LearningState.INSPECTING_RESULT

        updated_session = self.repo.update_session_states(
            session_id, learning_state=next_learning.value, expected_revision=rev
        )

        # Every downstream surface (including coaching) uses the authorized projection.
        public_artifact = self.repo.get_artifact_view(session_id,str(artifact_id))
        artifact_for_coaching = EvidenceArtifact.model_validate(public_artifact)
        coaching_payload: dict[str, Any] | None = None
        if self.coach_engine is not None:
            coaching_payload = self.coach_engine.build_coaching_turn_response(
                artifact=artifact_for_coaching,
                trace_report=trace_report,
                learning_state=next_learning,
                hint_level=1,
            )

        if coaching_payload is not None:
            self.repo.advance_hint(session_id,str(artifact_id),rev,1)
            self.repo.record_session_event(session_id,'COACHING_DELIVERED',{
                'revision':rev.model_dump(mode='json'), 'artifact_id':str(artifact_id), 'coaching':coaching_payload})
        self.repo.update_turn(session_id,turn_id,state=TurnState.COACH_PROMPT_DELIVERED.value)
        diagnostic = self._publish_counterexample(session_id,rev,ver_report,expected_case_hash)
        current = self.repo.get_session(session_id)
        return {
            'turn_id':turn_id, 'executed':obs.kind != ExecutionObservationKind.UNAVAILABLE,
            'session_state':current.state, 'learning_state':current.learning_state,
            'revision':self.build_revision_ref(session_id).model_dump(mode='json'),
            'artifact':public_artifact,
            'challenge':Challenge(
                challenge_id=challenge_id, revision=rev, input_args=canonical_input,
                case_hash=expected_case_hash, purpose=ChallengePurpose(c_dict['purpose']),
                reveal_state=RevealState.REVEALED, created_at=c_dict['created_at'],
                expires_at=c_dict['expires_at'],
            ).model_dump(mode='json'),
            'trace_report':trace_report.model_dump(mode='json') if trace_report else None,
            'coaching':coaching_payload, 'diagnostic_challenge':diagnostic,
        }

    def _publish_counterexample(self, session_id: str, rev: RevisionRef, report: VerificationReport,
                                predicted_case_hash: str | None = None) -> dict | None:
        if report.counterexample_input is None:
            return None
        case = exercise_registry.validate_input(rev.exercise_id.value,rev.spec_version.value,report.counterexample_input)
        case_hash = exercise_registry.case_key(rev.exercise_id.value,rev.spec_version.value,case)
        if case_hash == predicted_case_hash:
            return None
        challenge = self.issue_challenge(session_id,purpose=ChallengePurpose.DIAGNOSTIC,
            expected_revision=rev,requested_input=case)
        # Keep verifier observations in immutable hidden evidence bound to this input.
        if report.student_observation is not None and report.reference_output is not None:
            artifact = EvidenceArtifact(artifact_id=uuid4(), revision=challenge.revision,
                challenge_id=challenge.challenge_id, canonical_input=case, case_hash=case_hash,
                confirmed_prediction=None, actual_observation=report.student_observation,
                reference_output=report.reference_output, prediction_status=PredictionStatus.NOT_EVALUATED,
                verification_report=report, minimization_status=report.minimization_status)
            self.repo.save_artifact(artifact_id=str(artifact.artifact_id),session_id=session_id,
                challenge_id=str(challenge.challenge_id),code_version_id=challenge.revision.code_version_id,
                turn_generation=challenge.revision.turn_generation,case_hash=case_hash,confirmed_prediction=None,
                prediction_status=PredictionStatus.NOT_EVALUATED.value,verification_status=report.status.value,
                minimization_status=report.minimization_status.value,artifact_json=artifact.model_dump_json())
        return challenge.model_dump(mode='json')

    def _verification_requirements(self, revision: RevisionRef, *, run_curated_suite: bool,
                                   generated_cases_target: int, prior_input: dict | None) -> dict[str, Any]:
        cases = exercise_registry.cases(revision.exercise_id.value,revision.spec_version.value,'curriculum') if run_curated_suite else []
        hashes = {exercise_registry.case_key(revision.exercise_id.value,revision.spec_version.value,case) for case in cases}
        stages = ['curated_suite'] if run_curated_suite else []
        if prior_input is not None:
            hashes = hashes | {exercise_registry.case_key(revision.exercise_id.value,revision.spec_version.value,prior_input)}
            stages = [*stages,'prior_failing_input']
        if generated_cases_target:
            stages = [*stages,'generated_suite']
        return {'curated_cases':len(cases), 'generated_cases':generated_cases_target,
            'case_hashes':sorted(hashes), 'completed_stages':stages}

    @staticmethod
    def _report_covers_requirements(report: VerificationReport, requirements: dict[str, Any]) -> bool:
        required_hashes = set(requirements['case_hashes'])
        generated = requirements['generated_cases']
        executed = set(report.executed_case_hashes)
        return (report.status == VerificationStatus.NO_FAILURE_FOUND
            and report.counterexample_input is None and report.counterexample_case_hash is None
            and len(required_hashes) + generated > 0
            and report.curated_cases_run == requirements['curated_cases']
            and report.curated_cases_total == requirements['curated_cases']
            and report.generated_cases_run == generated and report.generated_cases_target == generated
            and required_hashes <= executed and len(executed) >= len(required_hashes) + generated
            and set(requirements['completed_stages']) <= set(report.completed_stages))

    def _completed_verification_allows_transfer(self, session_id: str, revision: RevisionRef) -> bool:
        from pydantic import ValidationError
        with self.repo._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM session_events WHERE session_id=? AND event_type='VERIFICATION_COMPLETED' ORDER BY sequence_no DESC",(session_id,)).fetchall()
        current = revision.model_dump(mode='json')
        for row in rows:
            event = json.loads(row[0])
            bound = event.get('revision',{})
            if any(bound.get(key) != current[key] for key in ('session_id','exercise_id','spec_version','code_version_id','code_hash')):
                continue
            try:
                report = VerificationReport.model_validate(event['verification_report'])
                requirements = event['verification_requirements']
            except (KeyError,ValidationError):
                continue
            if self._report_covers_requirements(report,requirements):
                return True
        return False

    def verify_revision(self, session_id: str, *, expected_revision: RevisionRef,
                        prior_artifact_id: UUID | None = None, run_curated_suite: bool = True,
                        generated_cases_target: int = 20) -> dict[str, Any]:
        """Repair verification performs only worker jobs and publishes undisclosed failures."""
        from backend.app.orchestration.worker_client import BrokerCommunicationError, BrokerAuthenticationError, PublicCustomCodeDisabledError
        rev = self.assert_revision_matches(session_id,expected_revision)
        session = self.repo.get_session(session_id)
        if not session.spec_acknowledged:
            raise RevisionConflictError('Acknowledge the specification before verification')
        prior = self.repo.get_prior_failing_input(session_id,rev,str(prior_artifact_id) if prior_artifact_id else None)
        request = VerifyJobRequest(job_id=uuid4(),revision=rev,
            source_code=self.repo.get_code_version(session_id,rev.code_version_id).source_code,
            prior_failing_input=prior,run_curated_suite=run_curated_suite,generated_cases_target=generated_cases_target,seed=42)
        if self.worker_client is None:
            _, report, _ = self._unavailable_execution_result(rev,'Isolated execution worker is not configured.')
        else:
            self.repo.register_execution_job(session_id,str(request.job_id),'VERIFY',rev,None)
            try:
                handle = self.worker_client.submit_verify(request)
                self.repo.finish_execution_job(session_id,str(request.job_id),str(handle.status))
                report = handle.verification_report or self._unavailable_execution_result(rev,'Worker returned no verification report.')[1]
            except (BrokerCommunicationError,BrokerAuthenticationError,PublicCustomCodeDisabledError):
                self.repo.finish_execution_job(session_id,str(request.job_id),'FAILED')
                report = self._unavailable_execution_result(rev,'Isolated execution worker is unavailable.')[1]
        self.assert_revision_matches(session_id,rev)
        for case_hash in report.executed_case_hashes:
            self.repo.record_case_history(session_id,rev.exercise_id.value,rev.spec_version.value,case_hash,'SEARCH')
        requirements = self._verification_requirements(rev,run_curated_suite=run_curated_suite,
            generated_cases_target=generated_cases_target,prior_input=prior)
        if report.status == VerificationStatus.NO_FAILURE_FOUND and not self._report_covers_requirements(report,requirements):
            report = report.model_copy(update={'status':VerificationStatus.VERIFICATION_INCOMPLETE,
                'terminal_reason':'Verification did not cover the required bounded cases.'})
        state = LearningState.REPAIR_REQUIRED if report.status == VerificationStatus.COUNTEREXAMPLE_CONFIRMED else (
            LearningState.FRESH_CASE_CHECK if report.status == VerificationStatus.NO_FAILURE_FOUND else LearningState.INSPECTING_RESULT)
        self.repo.update_session_states(session_id,learning_state=state.value,expected_revision=rev)
        # A verify request contains no learner prediction: never return verifier answers.
        public_report = report.model_copy(update={'student_observation':None,'reference_output':None,
            'terminal_reason':'Predict the diagnostic input before viewing its answer.' if report.counterexample_input else report.terminal_reason})
        self.repo.record_session_event(session_id,'VERIFICATION_COMPLETED',{
            'revision':rev.model_dump(mode='json'), 'verification_report':public_report.model_dump(mode='json'),
            'verification_requirements':requirements})
        self.assert_revision_matches(session_id,rev)
        diagnostic = self._publish_counterexample(session_id,rev,report)
        current = self.repo.get_session(session_id)
        return {'revision':self.build_revision_ref(session_id).model_dump(mode='json'),
            'session_state':current.state, 'learning_state':current.learning_state,
            'verification_report':public_report.model_dump(mode='json'), 'challenge':None,
            'diagnostic_challenge':diagnostic, 'artifact':None, 'trace_report':None}


    def cancel_active_work(self, session_id: str, job_id=None, *, tombstone: bool = False) -> dict[str, list[str]]:
        """Persist cancellation before contacting the broker; report acknowledgements honestly."""
        jobs = self.repo.request_execution_cancellation(session_id, str(job_id) if job_id else None)
        if tombstone:
            self.repo.tombstone_session(session_id)
        acknowledged,unconfirmed = [],[]
        for jid in jobs:
            try:
                accepted = self.worker_client is not None and self.worker_client.cancel(UUID(jid))
            except Exception:
                accepted = False
            if accepted:
                self.repo.acknowledge_execution_cancellation(session_id,jid)
            (acknowledged if accepted else unconfirmed).append(jid)
        return {"cancelled_job_ids":acknowledged,"unconfirmed_job_ids":unconfirmed}

    def _run_isolated_verification_and_trace(self, **kwargs):
        from backend.app.orchestration.worker_client import BrokerCommunicationError, BrokerAuthenticationError, PublicCustomCodeDisabledError
        try:
            return self._submit_isolated_verification_and_trace(**kwargs)
        except (BrokerCommunicationError, BrokerAuthenticationError, PublicCustomCodeDisabledError):
            # A transport/auth/capacity failure cannot establish code or prediction correctness.
            return self._unavailable_execution_result(kwargs['rev'], "Isolated execution worker is unavailable; retry after checking the worker connection.")

    def _submit_isolated_verification_and_trace(
        self,
        *,
        rev: RevisionRef,
        challenge_id: UUID,
        source_code: str,
        canonical_input: dict[str, Any],
        case_hash: str,
        reference_output: object,
    ) -> tuple[ExecutionObservation, VerificationReport, TraceExecutionReport | None]:
        """Dispatch only isolated worker jobs; injected test doubles provide protocol records, not execution evidence."""
        budget = ExecutionBudgetConfig()
        if self.worker_client is not None:
            def submit(job_type, request, method):
                self.repo.register_execution_job(str(rev.session_id), str(request.job_id), job_type, rev, str(challenge_id))
                try:
                    handle = method(request)
                except Exception as exc:
                    self.repo.finish_execution_job(str(rev.session_id),str(request.job_id),"FAILED")
                    from backend.app.orchestration.worker_client import BrokerCommunicationError, BrokerAuthenticationError, PublicCustomCodeDisabledError
                    if isinstance(exc,(BrokerCommunicationError,BrokerAuthenticationError,PublicCustomCodeDisabledError)):
                        return None
                    raise
                self.repo.finish_execution_job(str(rev.session_id),str(request.job_id),str(handle.status))
                return handle
            exec_handle = submit("EXECUTE",
                ExecutionRequest(
                    job_id=uuid4(),
                    revision=rev,
                    challenge_id=challenge_id,
                    source_code=source_code,
                    input_args=deepcopy(canonical_input),
                    case_hash=case_hash,
                    budget=budget,
                ), self.worker_client.submit_execution,
            )
            if exec_handle is None:
                return self._unavailable_execution_result(rev,'Isolated execution worker is unavailable.')
            obs = exec_handle.observation or ExecutionObservation(
                kind=ExecutionObservationKind.UNAVAILABLE,
                return_value=None,
                error_type="WorkerUnavailable",
                error_message="Worker returned no observation",
                duration_ms=0,
            )
            if obs.kind == ExecutionObservationKind.UNAVAILABLE:
                return self._unavailable_execution_result(rev,'Isolated execution worker returned no evaluated observation.')
            prior = self.repo.get_prior_failing_input(str(rev.session_id), rev)
            excluded = exercise_registry.cases(rev.exercise_id.value, rev.spec_version.value, 'curriculum') + [canonical_input]
            if prior is not None:
                excluded = [*excluded, prior]
            automatic_target = exercise_registry.bounded_generated_target(rev.exercise_id.value, rev.spec_version.value, 20, excluded)
            ver_handle = submit("VERIFY",
                VerifyJobRequest(
                    job_id=uuid4(),
                    revision=rev,
                    challenge_id=challenge_id,
                    source_code=source_code,
                    target_input=deepcopy(canonical_input),
                    prior_failing_input=prior,
                    run_curated_suite=True,
                    generated_cases_target=automatic_target,
                    seed=42,
                    budget=budget,
                ), self.worker_client.submit_verify,
            )
            ver_report = (ver_handle.verification_report if ver_handle else None) or VerificationReport(
                status=VerificationStatus.EXECUTION_UNAVAILABLE,
                curated_cases_run=0,
                curated_cases_total=0,
                generated_cases_run=0,
                generated_cases_target=20,
                completed_stages=[],
                terminal_reason="Worker verification report unavailable",
                runtime_version="runsc-unavailable",
            )
            if automatic_target != 20:
                ver_report = ver_report.model_copy(update={'requested_generated_cases_target': 20,
                    'terminal_reason': (ver_report.terminal_reason + f' Automatic finite-domain policy used {automatic_target} generated cases instead of default 20.')[:256]})
            trace_handle = submit("TRACE",
                TraceRequest(
                    job_id=uuid4(),
                    trace_id=uuid4(),
                    revision=rev,
                    challenge_id=challenge_id,
                    source_code=source_code,
                    input_args=deepcopy(canonical_input),
                    case_hash=case_hash,
                    budget=budget,
                ), self.worker_client.submit_trace,
            )
            return obs, ver_report, trace_handle.trace_report if trace_handle else None

        return self._unavailable_execution_result(rev, "Isolated gVisor execution worker is not configured in coordinator.")

    def _unavailable_execution_result(self, rev: RevisionRef, reason: str):
        # Fail-closed when no WorkerClient is configured (never execute learner code in the coordinator!)
        unavail_obs = ExecutionObservation(
            kind=ExecutionObservationKind.UNAVAILABLE,
            return_value=None,
            error_type="SandboxUnavailableError",
            error_message=reason,
            duration_ms=0,
        )
        unavail_ver = VerificationReport(
            status=VerificationStatus.EXECUTION_UNAVAILABLE,
            curated_cases_run=0,
            curated_cases_total=len(
                exercise_registry.cases(str(rev.exercise_id.value), str(rev.spec_version.value), "curriculum")
            ),
            generated_cases_run=0,
            generated_cases_target=0,
            completed_stages=[],
            terminal_reason=reason,
            runtime_version="runsc-unavailable",
            student_observation=unavail_obs,
        )
        return unavail_obs, unavail_ver, None
