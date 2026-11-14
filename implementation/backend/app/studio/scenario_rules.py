"""Deterministic checks of declared artifacts, never keyword grading of prose.

Passing means the submitted declarations satisfy the modeled constraint. It is
not proof of throughput, a running implementation, or semantic understanding.
"""
from __future__ import annotations

from math import isfinite
from backend.app.studio.scenario_content import CONTENT

CAPACITY_FIELDS = {
    "queue_capacity": ("arrival_rps", "service_rate_per_worker", "workers"),
    "origin_capacity": ("read_rps", "miss_fraction", "origin_capacity_rps"),
    "storage_capacity": ("users", "bytes_per_entry", "replicas", "storage_budget_bytes"),
    "retry_capacity": ("events_per_second", "retry_window_seconds", "bytes_per_event", "replicas", "storage_budget_bytes"),
    "keyspace": ("alphabet_size", "key_length", "issued_links"),
    "fanout_capacity": ("event_rate_per_second", "recipients_per_event", "dispatch_capacity_rps"),
    "query_capacity": ("query_rps", "query_capacity_per_replica", "available_replicas"),
    "forwarded_capacity": ("origin_forwarded_rps", "origin_capacity_rps"),
}


def rule_input_fields(spec: dict, constraint_index: int, *, transfer: bool = False) -> list[dict]:
    """Describe inputs for active checks without revealing future constraints."""
    if type(constraint_index) is not int or not 0 <= constraint_index < 4:
        raise ValueError("Constraint index must be 0–3")
    fields = {}

    def collect(rule):
        if rule["op"] == "any_of":
            for group in rule["groups"]:
                for child in group:
                    collect(child)
        elif rule["op"] == "property":
            fields[rule["key"]] = {"key": rule["key"], "type": "policy", "location": "node.properties",
                                     "values": rule["values"], "description": "Declared policy on a connected component; implementation is unverified."}
        elif rule["op"] == "number":
            fields[rule["key"]] = {"key": rule["key"], "type": "number", "location": "assumptions",
                                     "minimum": rule.get("minimum"), "maximum": rule.get("maximum")}
        else:
            for key in CAPACITY_FIELDS.get(rule["op"], ()):
                fields.setdefault(key, {"key": key, "type": "number", "location": "assumptions", "minimum": 0,
                                        "description": "Explicit modeled input; not a measured performance claim."})
    for constraint in spec["progressive_constraints"][:constraint_index + 1]:
        for rule in constraint["checks"]:
            collect(rule)
    if transfer:
        for rule in spec.get("fresh_transfer_checks", []):
            collect(rule)
    return list(fields.values())


def _number(assumptions: dict, key: str) -> float | None:
    value = assumptions.get(key)
    return float(value) if type(value) in (int, float) and 0 <= value <= 1e18 and isfinite(value) else None


def _reachable(graph: dict) -> set[str]:
    reached = {n["node_id"] for n in graph.get("nodes", []) if n.get("kind") == "client"}
    for _ in range(len(graph.get("nodes", []))):
        next_ids = {e["target_node_id"] for e in graph.get("edges", []) if e.get("source_node_id") in reached}
        if next_ids <= reached:
            break
        reached |= next_ids
    return reached


def _check(rule: dict, graph: dict, evidence_verified: bool) -> tuple[str, str, dict]:
    nodes = graph.get("nodes", [])
    assumptions = graph.get("assumptions", {})
    if not isinstance(assumptions, dict):
        return "unknown", "Numeric assumptions must be structured fields.", {}
    op = rule["op"]
    reached = _reachable(graph)
    active = [n for n in nodes if n.get("node_id") in reached and n.get("kind") != "client"]
    if op == "repository_evidence":
        return ("satisfied_under_declared_assumptions" if evidence_verified else "unknown",
                "Only server-verified snapshot citations establish repository grounding.", {})
    if op == "any_of":
        groups = [[_check(r, graph, evidence_verified)[0] for r in group] for group in rule["groups"]]
        if any(all(s == "satisfied_under_declared_assumptions" for s in group) for group in groups):
            return "satisfied_under_declared_assumptions", "One modeled alternative meets the declarations.", {}
        return ("unknown" if any("unknown" in group for group in groups) else "contradicts_constraint",
                "No alternative is established by the connected artifact yet.", {})
    if op == "node_kind":
        found = any(n.get("kind") in rule["kinds"] for n in active)
        return ("satisfied_under_declared_assumptions" if found else "unknown",
                "A relevant component must be reachable from a client.", {})
    if op == "property":
        present = [n.get("properties", {}).get(rule["key"]) for n in active if rule["key"] in n.get("properties", {})]
        if not present:
            return "unknown", f"Declare {rule['key']} on a connected component.", {}
        matches = any(any(type(v) is type(allowed) and v == allowed for allowed in rule["values"]) for v in present)
        return ("satisfied_under_declared_assumptions" if matches else "contradicts_constraint",
                f"Check the declared {rule['key']} policy; this does not verify its implementation.", {})
    if op == "number":
        value = _number(assumptions, rule["key"])
        if value is None:
            return "unknown", f"Supply a finite nonnegative {rule['key']} with stated units.", {}
        valid = (rule.get("minimum") is None or value >= rule["minimum"]) and (rule.get("maximum") is None or value <= rule["maximum"])
        return ("satisfied_under_declared_assumptions" if valid else "contradicts_constraint",
                f"Compare declared {rule['key']} with this constraint's bound.", {rule["key"]: value})
    if op == "path":
        starts = {n["node_id"] for n in nodes if n.get("kind") in rule["from"]}
        targets = {n["node_id"] for n in nodes if n.get("kind") in rule["to"]}
        reached = set(starts)
        for _ in nodes:
            reached |= {e["target_node_id"] for e in graph.get("edges", []) if e.get("source_node_id") in reached}
        return ("satisfied_under_declared_assumptions" if reached & targets else "unknown", "Check the directed data path.", {})
    fields = CAPACITY_FIELDS.get(op)
    if fields is None:
        raise ValueError(f"Unknown authored predicate: {op}")
    values = [_number(assumptions, key) for key in fields]
    if any(v is None for v in values):
        return "unknown", "Missing declared inputs: " + ", ".join(k for k, v in zip(fields, values) if v is None), {}
    if op == "queue_capacity":
        load, capacity = values[0], values[1] * values[2] * .8
    elif op == "origin_capacity":
        if values[1] > 1:
            return "contradicts_constraint", "Miss fraction must be between zero and one.", {}
        load, capacity = values[0] * values[1], values[2] * .8
    elif op == "storage_capacity":
        load, capacity = values[0] * values[1] * values[2], values[3]
    elif op == "retry_capacity":
        load, capacity = values[0] * values[1] * values[2] * values[3], values[4]
    elif op == "keyspace":
        if not (2 <= values[0] <= 128 and values[0].is_integer() and 1 <= values[1] <= 32 and values[1].is_integer()):
            return "contradicts_constraint", "Alphabet and key length must be bounded positive integers.", {}
        load, capacity = values[2], values[0] ** int(values[1])
    elif op == "fanout_capacity":
        load, capacity = values[0] * values[1], values[2] * .8
    elif op == "forwarded_capacity":
        load, capacity = values[0], values[1] * .8
    else:
        load, capacity = values[0], values[1] * values[2] * .8
    valid = isfinite(load) and isfinite(capacity) and capacity > 0 and load <= capacity
    return ("satisfied_under_declared_assumptions" if valid else "contradicts_constraint",
            "Estimate under declared inputs; operational overhead and real measurements remain unverified.",
            {"estimated_load": load, "modeled_capacity": capacity, "units": "bytes" if "storage" in op or "retry" in op else "rate_or_identifier_count"})


def evaluate_scenario(graph: dict, scenario_id: str, constraint_index: int = 0, *, evidence_verified: bool = False, spec: dict | None = None, transfer: bool = False) -> dict:
    spec = spec if spec is not None else CONTENT[scenario_id]
    if spec["scenario_id"] != scenario_id:
        raise ValueError("Pinned scenario identity mismatch")
    if type(constraint_index) is not int or not 0 <= constraint_index < 4:
        raise ValueError("Constraint index must be 0–3")
    results = []
    constraints = spec["progressive_constraints"][:constraint_index + 1]
    if transfer:
        constraints = constraints + [{"id": "TRANSFER", "checks": spec.get("fresh_transfer_checks", [])}]
    for constraint in constraints:
        for index, rule in enumerate(constraint["checks"]):
            status, reason, calculation = _check(rule, graph, evidence_verified)
            results.append({"check_id": f"{constraint['id']}-{index}", "constraint_id": constraint["id"],
                            "status": status, "reason": reason, "calculation": calculation, "required_fields": rule})
    statuses = {r["status"] for r in results}
    if transfer and not spec.get("fresh_transfer_checks"):
        statuses.add("unknown")
    status = "contradicts_constraint" if "contradicts_constraint" in statuses else "unknown" if "unknown" in statuses else "satisfied_under_declared_assumptions"
    return {"scenario_id": scenario_id, "scenario_version": spec["scenario_version"],
            "content_sha256": spec["content_sha256"], "constraint_index": constraint_index,
            "status": status, "checks": results, "transfer": transfer, "semantic_reasoning_status": "unassessed",
            "limitation": "Checks inspect connected structured declarations; no runtime or prose understanding is certified."}
