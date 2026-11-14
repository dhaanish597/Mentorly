"""Coaching engine, claim extractor, Socratic templates, and prompt guardrail package (`backend/app/coaching`)."""

from .claim_extractor import ModelAssistedClaimExtractor, extract_claim_deterministic
from .coach_engine import CoachEngine
from .prompt_guard import validate_model_coaching_output, wrap_untrusted_learner_inputs
from .templates import (
    CoachingHintPrompt,
    find_divergence_trace_step,
    render_deterministic_hint,
)

__all__ = [
    "CoachEngine",
    "ModelAssistedClaimExtractor",
    "CoachingHintPrompt",
    "extract_claim_deterministic",
    "find_divergence_trace_step",
    "render_deterministic_hint",
    "validate_model_coaching_output",
    "wrap_untrusted_learner_inputs",
]
