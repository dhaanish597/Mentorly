"""Distinct deterministic policies for each interview domain."""
from . import cs, dsa, system_design, codebase_defense

POLICIES = {'dsa': dsa, 'cs': cs, 'system_design': system_design, 'codebase_defense': codebase_defense}
