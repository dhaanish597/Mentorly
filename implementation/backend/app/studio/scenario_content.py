"""Reviewed, versioned scenario content; public views must omit teaching answers."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


def load_content(directory: Path | None = None) -> dict[str, dict]:
    directory = directory or Path(__file__).parent / "scenarios/catalog"
    result = {}
    for path in sorted(directory.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        required = {"scenario_id", "scenario_version", "title", "learning_mode", "difficulty",
                    "estimated_minutes", "linked_exercise_ids", "prerequisites", "learning_objectives",
                    "problem_statement", "clarification_facts", "seed_graph", "progressive_constraints",
                    "valid_architecture_families", "common_misconceptions", "hint_ladder",
                    "consolidation", "fresh_transfer_question", "fresh_transfer_checks", "rubric", "coach_instructions"}
        if required - spec.keys():
            raise ValueError(f"Incomplete authored scenario: {path.name}")
        sid = spec["scenario_id"]
        if path.stem != sid or sid in result or not re.fullmatch(r"\d+\.\d+\.\d+", spec["scenario_version"]):
            raise ValueError(f"Invalid scenario identity: {path.name}")
        if [c["id"] for c in spec["progressive_constraints"]] != ["C0", "C1", "C2", "C3"]:
            raise ValueError(f"Scenario must author all four constraints: {sid}")
        if len(spec["valid_architecture_families"]) < 2 or set(spec["hint_ladder"]) != {"level_1", "level_2", "level_3"}:
            raise ValueError(f"Missing alternatives or scaffold: {sid}")
        canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        spec["content_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        result[sid] = spec
    if len(result) != 12:
        raise ValueError("Launch catalog must include all twelve authored scenarios")
    return result


CONTENT = load_content()


def get_content(scenario_id: str) -> dict:
    """Return a copy so an active caller cannot mutate catalog content."""
    return deepcopy(CONTENT[scenario_id])
