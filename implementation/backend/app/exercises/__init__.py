"""Trusted exercise specifications, input validators, and reference oracles."""

from .registry import (
    ExerciseSpec,
    case_key,
    cases,
    compare_output,
    evaluate,
    get_spec,
    list_specs,
    validate_input,
    validate_output,
    validate_prediction,
    public_catalog,
    validate_catalog,
    load_catalog,
)

__all__ = [
    "ExerciseSpec",
    "case_key",
    "cases",
    "compare_output",
    "evaluate",
    "get_spec",
    "list_specs",
    "validate_input",
    "validate_output",
    "validate_prediction",
    "public_catalog",
    "validate_catalog",
    "load_catalog",
]
