"""Verification shrinker and property-based case generation package (`backend/app/verification`)."""

from .hypothesis_strategies import generate_property_cases
from .minimizer import shrink_counterexample

__all__ = ["generate_property_cases", "shrink_counterexample"]
