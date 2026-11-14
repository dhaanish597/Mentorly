"""Offline evaluation regressions; learner source stays inert data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation import run_code_eval as code_eval

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "evaluation/speech_ablation/audio_manifest.json"


def readiness():
    from evaluation import validate_readiness
    return validate_readiness


def manifest():
    return json.loads(MANIFEST.read_text())


def test_pending_manifest_has_four_anonymous_slots_and_24_balanced_clips():
    data = manifest()
    result = readiness().validate_manifest(data)
    assert result["status"] == "BLOCKED_EXTERNAL"
    assert result["clips_total"] == 24
    assert result["clips_ready"] == 0
    assert result["speakers_consented"] == 0
    assert result["split_counts"] == {"development": 12, "heldout": 12}
    assert all(s["participant_status"] == "PENDING_RECRUITMENT" for s in data["speakers"])
    assert all(c["reference_text"] is None for c in data["clips"])


@pytest.mark.parametrize("bad", [None, [], "", {}, {"speakers": [], "clips": []}])
def test_rejects_invalid_manifest_shapes(bad):
    with pytest.raises(ValueError):
        readiness().validate_manifest(bad)


@pytest.mark.parametrize("change", ["missing_clip", "duplicate", "language", "speaker", "split", "fake_ready", "upload", "split_tamper"])
def test_rejects_incomplete_or_privacy_unsafe_manifest(change):
    data = manifest()
    if change == "missing_clip":
        data["clips"] = data["clips"][:-1]
    elif change == "duplicate":
        data["clips"][1]["clip_id"] = data["clips"][0]["clip_id"]
    elif change == "language":
        data["clips"][0]["language_mode"] = "hi-IN"
    elif change == "speaker":
        data["clips"][0]["speaker_id"] = "unknown"
    elif change == "split":
        data["speakers"][0]["split"] = "heldout"
    elif change == "fake_ready":
        data["clips"][0]["status"] = "READY"
    elif change == "upload":
        data["privacy"]["no_upload"] = False
    else:
        data["split_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        readiness().validate_manifest(data)


def recorded_manifest():
    data = manifest()
    data["speakers"] = [dict(s, participant_status="ENROLLED", consent_status="GRANTED", consent_ref=f"consents/{s['speaker_id']}.json", retention_expires_at="2026-12-01T00:00:00+00:00") for s in data["speakers"]]
    data["clips"] = [dict(c, status="READY", local_audio_ref=f"recordings/{c['clip_id']}.wav", audio_sha256="a" * 64, reference_text="minus two தமிழ்", reference_tokens=["-2", "nums"], reference_status="HUMAN_REVIEWED") for c in data["clips"]]
    return data


def test_freeze_requires_human_data_and_is_immutable_and_detects_changes():
    module = readiness()
    pending = manifest()
    with pytest.raises(ValueError):
        module.freeze_manifest(pending)
    data = recorded_manifest()
    original = deepcopy(data)
    frozen = module.freeze_manifest(data)
    assert data == original
    assert module.validate_manifest(frozen)["status"] == "READY_LOCAL"
    frozen["clips"][0]["reference_text"] += " changed"
    with pytest.raises(ValueError, match="frozen"):
        module.validate_manifest(frozen)


@pytest.mark.parametrize("field,value", [("local_audio_ref", "https://example.invalid/audio"), ("local_audio_ref", "../private.wav"), ("audio_sha256", "not-a-hash"), ("reference_tokens", []), ("reference_text", ""), ("reference_status", "PROVIDER_GENERATED")])
def test_recorded_clip_requires_local_hash_and_human_annotations(field, value):
    data = recorded_manifest()
    data["clips"][0][field] = value
    with pytest.raises(ValueError):
        readiness().validate_manifest(data)


def test_exact_plan_corpus_metadata_without_executing_sources():
    data = json.loads((ROOT / "evaluation/corpora/buggy_implementations.json").read_text())
    fixtures = data["fixtures"]
    assert len(fixtures) == 12
    categories = {f["plan_bug"] for f in fixtures}
    assert categories == {"strict_gt", "off_by_one_length", "negative_sliding_window", "first_window_full_length", "immediate_mid", "discarded_mid", "missing_post_check", "nonprogressing_left_mid", "uncached_hi", "positive_only_kadane", "ans_zero", "reset_zero_to_one"}
    for f in fixtures:
        assert f["code_hash"] == hashlib.sha256(f["source_code"].encode()).hexdigest()
        assert f["trigger_input"] and f["expected_trace_predicates"]
        assert f["replay_outcome"] == "PENDING_ACCEPTED_RUNSC"
    zero = next(f for f in fixtures if f["plan_bug"] == "reset_zero_to_one")
    assert zero["trigger_input"] == {"nums": [-2, 0, -1]}
    assert zero["reference_output"] == 0 and zero["expected_student_output"] == 1
    extras = json.loads((ROOT / "evaluation/corpora/extra_buggy_implementations.json").read_text())
    assert len(extras["fixtures"]) == 6


def report(status="COUNTEREXAMPLE_CONFIRMED", kind="RETURN", **changes):
    values = dict(status=code_eval.VerificationStatus(status), counterexample_input={"nums": [5], "target": 5}, student_observation=SimpleNamespace(kind=code_eval.ExecutionObservationKind(kind), return_value=0), reference_output=1, curated_cases_run=8, curated_cases_total=8, generated_cases_run=40, generated_cases_target=40, completed_stages=["curated_suite", "generated_suite"], runtime_version="runsc-test", terminal_reason="test report", seed=42)
    return SimpleNamespace(**(values | changes))


def run_fake(monkeypatch, bug_report, correct_report, ready=True):
    runner = SimpleNamespace(check_preflight=lambda: SimpleNamespace(ready=ready, acceptance_verified=ready, summary="test unavailable"))
    monkeypatch.setattr(code_eval, "GVisorSandboxRunner", lambda: runner)
    calls = []
    def verify(req, sandbox):
        calls.append(req)
        return bug_report if len(calls) <= 12 else correct_report
    monkeypatch.setattr(code_eval, "run_verification_job", verify)
    return code_eval.run_evaluation_suite(), calls


@pytest.mark.parametrize("status,kind", [("EXECUTION_ERROR", "INVALID_RESULT"), ("EXECUTION_ERROR", "RESOURCE_LIMIT"), ("TIMEOUT", "TIMEOUT"), ("EXECUTION_UNAVAILABLE", "UNAVAILABLE"), ("COUNTEREXAMPLE_CONFIRMED", "INVALID_RESULT"), ("REPLAY_UNCONFIRMED", "RETURN")])
def test_infrastructure_timeout_protocol_never_count_as_detection(monkeypatch, status, kind):
    result, calls = run_fake(monkeypatch, report(status, kind), report("NO_FAILURE_FOUND"))
    assert len(calls) == 18
    assert result["overall_pass"] is False
    assert result["buggy_detected_count"] == 0
    assert result["buggy_reports_observed"] == 12
    assert result["correct_reports_observed"] == 6


@pytest.mark.parametrize("changes", [{"generated_cases_run": 39}, {"curated_cases_run": 7}, {"completed_stages": ["curated_suite"]}, {"generated_cases_target": 0}, {"curated_cases_total": 0}, {"student_observation": SimpleNamespace(kind=code_eval.ExecutionObservationKind.INVALID_RESULT)}])
def test_alternatives_require_completed_full_requested_suites(monkeypatch, changes):
    result, _ = run_fake(monkeypatch, report(), report("NO_FAILURE_FOUND", **changes))
    assert result["overall_pass"] is False
    assert result["correct_passed_count"] == 0


def test_valid_replayed_mismatch_and_complete_alternatives_pass(monkeypatch):
    result, _ = run_fake(monkeypatch, report(), report("NO_FAILURE_FOUND", student_observation=None, counterexample_input=None))
    assert result["overall_pass"] is True
    assert result["buggy_detected_count"] == 12
    assert result["correct_passed_count"] == 6
    assert result["buggy_results"][0]["curated_cases_run"] == 8


def test_preflight_blocks_without_any_verification(monkeypatch):
    result, calls = run_fake(monkeypatch, report(), report("NO_FAILURE_FOUND"), ready=False)
    assert calls == []
    assert result["status"] == "BLOCKED_EXTERNAL"
    assert result["overall_pass"] is False
    assert result["buggy_reports_observed"] == result["correct_reports_observed"] == 0
    assert result["buggy_total"] == 12 and result["correct_total"] == 6


def test_ready_runtime_without_acceptance_still_blocks(monkeypatch):
    runner = SimpleNamespace(check_preflight=lambda: SimpleNamespace(ready=True, acceptance_verified=False, summary="unaccepted"))
    monkeypatch.setattr(code_eval, "GVisorSandboxRunner", lambda: runner)
    monkeypatch.setattr(code_eval, "run_verification_job", lambda *_: pytest.fail("must not execute"))
    assert code_eval.run_evaluation_suite()["status"] == "BLOCKED_EXTERNAL"


def test_evaluator_exception_keeps_zero_observed_denominator(monkeypatch):
    runner = SimpleNamespace(check_preflight=lambda: SimpleNamespace(ready=True, acceptance_verified=True))
    monkeypatch.setattr(code_eval, "GVisorSandboxRunner", lambda: runner)
    def fail(*_):
        raise TimeoutError("private details must not appear in report")
    monkeypatch.setattr(code_eval, "run_verification_job", fail)
    result = code_eval.run_evaluation_suite()
    assert not result["overall_pass"]
    assert result["buggy_reports_observed"] == result["correct_reports_observed"] == 0
    assert result["buggy_results"][0]["error_type"] == "TimeoutError"
    assert "private details" not in json.dumps(result)


def test_manifest_cli_reports_pending_invalid_and_freezes_locally(tmp_path, capsys):
    module = readiness()
    assert module.main([str(MANIFEST)]) == 2
    assert json.loads(capsys.readouterr().out)["clips_ready"] == 0
    bad = tmp_path / "invalid.json"
    bad.write_text("not json")
    assert module.main([str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID"
    data = tmp_path / "local.json"
    data.write_text(json.dumps(recorded_manifest()))
    frozen = tmp_path / "frozen.json"
    assert module.main([str(data), "--freeze-output", str(frozen)]) == 0
    assert json.loads(capsys.readouterr().out)["frozen"] is True
    assert module.main([str(frozen)]) == 0
    capsys.readouterr()
    assert module.main([str(data), "--freeze-output", str(frozen)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID"


def test_rejects_large_wrong_sized_manifest_before_processing_clips():
    data = manifest()
    data["clips"] = data["clips"] * 500
    with pytest.raises(ValueError, match="24"):
        readiness().validate_manifest(data)


def test_replayed_exception_is_detection_but_matching_return_is_not(monkeypatch):
    result, _ = run_fake(monkeypatch, report(kind="EXCEPTION"), report("NO_FAILURE_FOUND", student_observation=None, counterexample_input=None))
    assert result["buggy_detected_count"] == 12
    result, _ = run_fake(monkeypatch, report(reference_output=0), report("NO_FAILURE_FOUND"))
    assert result["buggy_detected_count"] == 0
