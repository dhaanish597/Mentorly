"""Distinct deterministic policies for each interview domain."""

from . import codebase_defense, cs, dsa, system_design

POLICIES = {
    "dsa": dsa,
    "cs": cs,
    "system_design": system_design,
    "codebase_defense": codebase_defense,
}
