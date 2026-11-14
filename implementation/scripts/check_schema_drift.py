"""Deterministic TypeScript Contract Generator & Structural Drift Gate (`check_schema_drift.py`).

Repairs Applied (R7 & P2-02):
- Deterministically generates all TypeScript `type` and `interface` declarations directly
  from the canonical Pydantic models (`backend/app/models/{enums,domain,api_schemas}.py`),
  preserving `BrandingInfo`, `ExerciseMetadata`, `ExerciseSpecMetadata`, `DemoPresetMetadata`,
  `HealthResponse`, `RevisionRef`, `Challenge`, `ClaimInterpretation`, `ExecutionObservation`,
  `VerificationReport`, `EvidenceArtifact`, `HiddenEvidenceArtifactView`, `TraceStep`,
  `TraceExecutionReport`, `SpeechJob`, `ApiError`, all P0/P1 request/response DTOs, and
  all Phase 2 (`T-03`) speech DTOs (`STTRequest`, `STTResult`, `TTSAudioConfig`, `TTSRequest`,
  `AudioEvent`, `SpeechCapacityStatus`, `VoicePlaybackAckRequest`, `VoicePlaybackAckResponse`).
- Properly unwraps `Annotated` (`StrictInt`, discriminated unions) and enum-backed `Literal` values.
- Compares structural field signatures (field name, optionality `?`, full TypeScript type
  expression including `| null`, tuple/array types, literal discriminators, and union members)
  without modifying `frontend/src/types/api.ts`.
- Implements `--self-test` with 6 distinct mutation probes (number->string field mutation,
  nullability removal, optional-to-required flip, union member mutation, enum value mutation,
  and missing field mutation) and fails if any mutation passes undetected.
"""

from __future__ import annotations

import argparse
import enum
import re
import sys
from pathlib import Path
from types import NoneType, UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import BaseModel  # noqa: E402
from pydantic_core import PydanticUndefined  # noqa: E402

from backend.app.models import api_schemas, domain, enums  # noqa: E402

TS_TYPES_PATH = REPO_ROOT / "frontend" / "src" / "types" / "api.ts"

ENUM_CLASSES: tuple[type[enum.Enum], ...] = (
    enums.ExerciseId,
    enums.SpecVersion,
    enums.LanguageMode,
    enums.InteractionMode,
    enums.TransportMode,
    enums.SessionState,
    enums.LearningState,
    enums.TurnState,
    enums.JobStatus,
    enums.ChallengePurpose,
    enums.RevealState,
    enums.ClaimType,
    enums.ClaimPolarity,
    enums.ExtractionMethod,
    enums.ExecutionObservationKind,
    enums.VerificationStatus,
    enums.PredictionStatus,
    enums.MinimizationStatus,
    enums.TraceEventKind,
    enums.TraceAttributionStatus,
    enums.TraceExecutionStatus,
    enums.SpeechMode,
    enums.SpeechDegradationStatus,
    enums.PlaybackStatus,
    enums.HintLevel,
)

MODEL_CLASSES: tuple[tuple[str, type[BaseModel]], ...] = (
    ("TTSPlaybackRequest", api_schemas.TTSPlaybackRequest),
    ("HealthResponse", api_schemas.HealthResponse),
    ("BrandingInfo", api_schemas.BrandingResponse),
    ("BrandingResponse", api_schemas.BrandingResponse),
    ("ValueSchema", api_schemas.ValueSchema),
    ("ExerciseExample", api_schemas.ExerciseExample),
    ("CatalogProvenance", api_schemas.CatalogProvenance),
    ("ExerciseSpecMetadata", api_schemas.ExerciseSpecMetadata),
    ("ExerciseMetadata", api_schemas.ExerciseMetadata),
    ("DemoPresetMetadata", api_schemas.DemoPresetMetadata),
    ("RevisionRef", domain.RevisionRef),
    ("Challenge", domain.Challenge),
    ("OutputPredictionClaim", domain.OutputPredictionClaim),
    ("InvariantOrMechanismClaim", domain.InvariantOrMechanismClaim),
    ("DomainValidityClaim", domain.DomainValidityClaim),
    ("ClarificationOrHintClaim", domain.ClarificationOrHintClaim),
    ("UnsupportedClaim", domain.UnsupportedClaim),
    ("ExecutionObservation", domain.ExecutionObservation),
    ("HypothesisStatistics", domain.HypothesisStatistics),
    ("VerificationReport", domain.VerificationReport),
    ("TraceStep", domain.TraceStep),
    ("TraceExecutionReport", domain.TraceExecutionReport),
    ("ExecutionBudgetConfig", domain.ExecutionBudgetConfig),
    ("ExecutionRequest", domain.ExecutionRequest),
    ("VerifyJobRequest", domain.VerifyJobRequest),
    ("TraceRequest", domain.TraceRequest),
    ("JobHandle", domain.JobHandle),
    ("EvidenceArtifact", domain.EvidenceArtifact),
    ("HiddenEvidenceArtifactView", domain.HiddenEvidenceArtifactView),
    ("SpeechJob", domain.SpeechJob),
    ("ApiError", domain.ApiError),
    ("CreateSessionRequest", api_schemas.CreateSessionRequest),
    ("CreateSessionResponse", api_schemas.CreateSessionResponse),
    ("CodeUpdateRequest", api_schemas.CodeUpdateRequest),
    ("CodeUpdateResponse", api_schemas.CodeUpdateResponse),
    ("SpecUpdateRequest", api_schemas.SpecUpdateRequest),
    ("SpecAckRequest", api_schemas.SpecAckRequest),
    ("CreateChallengeRequest", api_schemas.CreateChallengeRequest),
    ("TextTurnRequest", api_schemas.TextTurnRequest),
    ("ConfirmClaimRequest", api_schemas.ConfirmClaimRequest),
    ("VerifyRequest", api_schemas.VerifyRequest),
    ("RetryExecutionRequest", api_schemas.RetryExecutionRequest),
    ("FreshCaseCheckRequest", api_schemas.FreshCaseCheckRequest),
    ("HintRequest", api_schemas.HintRequest),
    ("PlaybackAckRequest", api_schemas.PlaybackAckRequest),
    ("CancelRequest", api_schemas.CancelRequest),
    ("CancelResponse", api_schemas.CancelResponse),
    ("JobAcceptedResponse", api_schemas.JobAcceptedResponse),
    ("JobStatusResponse", api_schemas.JobStatusResponse),
    ("OperationsReadinessResponse", api_schemas.OperationsReadinessResponse),
    ("CapacityResponse", api_schemas.CapacityResponse),
    ("SessionExportResponse", api_schemas.SessionExportResponse),
    ("DeleteSessionResponse", api_schemas.DeleteSessionResponse),
    ("STTRequest", api_schemas.STTRequest),
    ("STTResult", api_schemas.STTResult),
    ("TTSAudioConfig", api_schemas.TTSAudioConfig),
    ("TTSRequest", api_schemas.TTSRequest),
    ("AudioEvent", api_schemas.AudioEvent),
    ("SpeechCapacityStatus", api_schemas.SpeechCapacityStatus),
    ("VoicePlaybackAckRequest", api_schemas.VoicePlaybackAckRequest),
    ("VoicePlaybackAckResponse", api_schemas.VoicePlaybackAckResponse),
)

UNION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "ClaimInterpretation",
        (
            "OutputPredictionClaim",
            "InvariantOrMechanismClaim",
            "DomainValidityClaim",
            "ClarificationOrHintClaim",
            "UnsupportedClaim",
        ),
    ),
)


def _py_type_to_ts(tp: Any) -> str:
    """Deterministically map a Python/Pydantic field annotation to its TypeScript type."""
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Annotated and args:
        inner_origin = get_origin(args[0])
        inner_args = get_args(args[0])
        if inner_origin in (Union, UnionType) and any(
            getattr(a, "__name__", "") == "OutputPredictionClaim" for a in inner_args
        ):
            return "ClaimInterpretation"
        return _py_type_to_ts(args[0])

    if tp is Any:
        return "unknown"
    if tp is str:
        return "string"
    if tp in (int, float):
        return "number"
    if tp is bool:
        return "boolean"
    if tp is None or tp is NoneType:
        return "null"
    if hasattr(tp, "__name__") and tp.__name__ in ("datetime", "UUID"):
        return "string"
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return tp.__name__
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return tp.__name__

    if origin is Literal:
        rendered_lits: list[str] = []
        for a in args:
            val = a.value if isinstance(a, enum.Enum) else a
            if isinstance(val, str):
                rendered_lits.append(f"'{val}'")
            elif isinstance(val, bool):
                rendered_lits.append("true" if val else "false")
            else:
                rendered_lits.append(str(val))
        return " | ".join(rendered_lits)

    if origin in (Union, UnionType):
        non_none = [a for a in args if a is not NoneType]
        has_none = any(a is NoneType for a in args)
        parts = [_py_type_to_ts(a) for a in non_none]
        if has_none:
            parts.append("null")
        return " | ".join(parts)

    if origin is list:
        inner = _py_type_to_ts(args[0]) if args else "unknown"
        if " | " in inner:
            return f"({inner})[]"
        return f"{inner}[]"

    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            inner = _py_type_to_ts(args[0])
            return f"{inner}[]"
        return "[" + ", ".join(_py_type_to_ts(a) for a in args) + "]"

    if origin is dict:
        k_ts = _py_type_to_ts(args[0]) if len(args) >= 1 else "string"
        v_ts = _py_type_to_ts(args[1]) if len(args) >= 2 else "unknown"
        return f"Record<{k_ts}, {v_ts}>"

    return "unknown"


def _is_field_optional(field_info: Any) -> bool:
    """Return True if a Pydantic field has a default or default_factory."""
    if field_info.default_factory is not None:
        return True
    if field_info.default is not PydanticUndefined:
        ann = field_info.annotation
        if get_origin(ann) is Annotated and get_args(ann):
            ann = get_args(ann)[0]
        origin = get_origin(ann)
        if origin is Literal and len(get_args(ann)) == 1:
            return False
        return True
    return False


def render_typescript_contracts() -> str:
    """Render the complete, deterministic `frontend/src/types/api.ts` file from Python schemas."""
    lines: list[str] = [
        "/**",
        " * Canonical TypeScript Contracts for Voice Coding Coach (`frontend/src/types/api.ts`).",
        " * Deterministically generated and verified by `scripts/check_schema_drift.py`.",
        " * DO NOT EDIT MANUALLY without updating `backend/app/models/{enums,domain,api_schemas}.py`.",
        " */",
        "",
    ]

    for enum_cls in ENUM_CLASSES:
        unique_vals = list(dict.fromkeys(item.value for item in enum_cls))
        rendered_vals = [
            str(v) if isinstance(v, int) and not isinstance(v, bool) else f"'{v}'"
            for v in unique_vals
        ]
        values = " | ".join(rendered_vals)
        lines.append(f"export type {enum_cls.__name__} = {values};")
    lines.append("")

    for model_name, model_cls in MODEL_CLASSES:
        lines.append(f"export interface {model_name} {{")
        for field_name, field_info in model_cls.model_fields.items():
            ts_type = _py_type_to_ts(field_info.annotation)
            opt = "?" if _is_field_optional(field_info) else ""
            lines.append(f"  {field_name}{opt}: {ts_type};")
        lines.append("}")
        lines.append("")

    for union_name, members in UNION_ALIASES:
        lines.append(f"export type {union_name} =")
        for idx, member in enumerate(members):
            suffix = ";" if idx == len(members) - 1 else ""
            lines.append(f"  | {member}{suffix}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_ts_declarations(ts_source: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Parse TypeScript `export type X = ...;` and `export interface Y { ... }` declarations."""
    cleaned = re.sub(r"/\*.*?\*/", "", ts_source, flags=re.DOTALL)
    cleaned = re.sub(r"//[^\n]*", "", cleaned)

    type_aliases: dict[str, str] = {}
    for match in re.finditer(r"export\s+type\s+(\w+)\s*=\s*([^;]+);", cleaned):
        name = match.group(1)
        rhs = " ".join(match.group(2).split())
        if rhs.startswith("| "):
            rhs = rhs[2:]
        type_aliases[name] = rhs

    interfaces: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"export\s+interface\s+(\w+)\s*\{([^}]*)\}", cleaned):
        iface_name = match.group(1)
        body = match.group(2)
        fields: dict[str, str] = {}
        for line in body.split(";"):
            stmt = line.strip()
            if not stmt:
                continue
            f_match = re.match(r"^(\w+)(\??)\s*:\s*(.+)$", stmt)
            if not f_match:
                raise ValueError(f"Malformed field declaration in {iface_name}: {stmt!r}")
            fname, opt_flag, ftype = (
                f_match.group(1),
                f_match.group(2),
                " ".join(f_match.group(3).split()),
            )
            fields[f"{fname}{opt_flag}"] = ftype
        interfaces[iface_name] = fields

    return type_aliases, interfaces


def check_ts_content(actual_ts: str) -> list[str]:
    """Compare `actual_ts` against the canonical model-derived TypeScript contracts."""
    expected_ts = render_typescript_contracts()
    expected_types, expected_ifaces = parse_ts_declarations(expected_ts)
    try:
        actual_types, actual_ifaces = parse_ts_declarations(actual_ts)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []

    for tname, exp_rhs in expected_types.items():
        if tname not in actual_types:
            errors.append(f"Missing TypeScript type alias: {tname}")
        elif actual_types[tname] != exp_rhs:
            errors.append(
                f"Type alias mismatch for {tname}: expected `{exp_rhs}`, found `{actual_types[tname]}`"
            )

    for extra_t in set(actual_types) - set(expected_types):
        errors.append(f"Unexpected extra TypeScript type alias: {extra_t}")

    for iname, exp_fields in expected_ifaces.items():
        if iname not in actual_ifaces:
            errors.append(f"Missing TypeScript interface: {iname}")
            continue
        act_fields = actual_ifaces[iname]
        for fkey, exp_ftype in exp_fields.items():
            if fkey not in act_fields:
                errors.append(
                    f"Interface {iname} missing field or optionality mismatch for `{fkey}: {exp_ftype}`"
                )
            elif act_fields[fkey] != exp_ftype:
                errors.append(
                    f"Interface {iname}.{fkey} type mismatch: expected `{exp_ftype}`, found `{act_fields[fkey]}`"
                )
        for extra_f in set(act_fields) - set(exp_fields):
            errors.append(f"Interface {iname} has unexpected/mismatched field `{extra_f}`")

    for extra_i in set(actual_ifaces) - set(expected_ifaces):
        errors.append(f"Unexpected extra TypeScript interface: {extra_i}")

    return errors


def run_self_test() -> int:
    """Run mutation tests against in-memory copies to prove structural drift detection (R7)."""
    baseline = render_typescript_contracts()
    base_errors = check_ts_content(baseline)
    if base_errors:
        print(f"SELF-TEST FAILED on baseline: {base_errors}", file=sys.stderr)
        return 1

    mutations: list[tuple[str, str]] = [
        (
            "number_to_string_field_mutation",
            baseline.replace("  code_version_id: number;", "  code_version_id: string;", 1),
        ),
        (
            "nullability_removal_mutation",
            baseline.replace(
                "  target_bounds?: [number, number] | null;",
                "  target_bounds?: [number, number];",
                1,
            ),
        ),
        (
            "optional_to_required_mutation",
            baseline.replace(
                "  seed?: number | null;",
                "  seed: number | null;",
                1,
            ),
        ),
        (
            "union_member_mutation",
            baseline.replace("  | OutputPredictionClaim", "  | FakePredictionClaim", 1),
        ),
        (
            "enum_value_mutation",
            baseline.replace("'NO_FAILURE_FOUND'", "'ALL_GOOD'", 1),
        ),
        (
            "missing_field_mutation",
            baseline.replace("  custom_code_execution_enabled: boolean;\n", "", 1),
        ),
    ]

    for label, mutated_ts in mutations:
        if mutated_ts == baseline:
            print(f"SELF-TEST FAILED: mutation {label} did not alter baseline text.", file=sys.stderr)
            return 1
        detected = check_ts_content(mutated_ts)
        if not detected:
            print(f"SELF-TEST FAILED: mutation {label} passed undetected!", file=sys.stderr)
            return 1

    print(f"OK: Self-test passed ({len(mutations)} structural mutations detected and rejected).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify or generate deterministic TypeScript contracts from Python schemas."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Read-only check that frontend/src/types/api.ts matches the canonical Python schemas.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Explicit maintenance action: write canonical TypeScript contracts to frontend/src/types/api.ts.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run mutation self-tests on disposable in-memory copies.",
    )
    parser.add_argument(
        "--ts-path",
        type=Path,
        default=TS_TYPES_PATH,
        help="Path to TypeScript contract file.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        rc = run_self_test()
        if rc != 0:
            return rc

    if args.write:
        rendered = render_typescript_contracts()
        args.ts_path.parent.mkdir(parents=True, exist_ok=True)
        args.ts_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote canonical TypeScript contracts to {args.ts_path}")
        return 0

    if not args.ts_path.exists():
        print(f"SCHEMA DRIFT ERROR: {args.ts_path} does not exist.", file=sys.stderr)
        return 1

    actual_text = args.ts_path.read_text(encoding="utf-8")
    errors = check_ts_content(actual_text)
    if errors:
        for err in errors:
            print(f"SCHEMA DRIFT ERROR: {err}", file=sys.stderr)
        return 1

    print(
        f"OK: Zero schema drift across {len(ENUM_CLASSES)} enums, "
        f"{len(MODEL_CLASSES)} interfaces, and {len(UNION_ALIASES)} union aliases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
