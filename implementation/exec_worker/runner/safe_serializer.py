"""Safe bounded value serializer for trace local snapshots (§9.4, P2-03 & R5 repaired).

Security & Isolation Contract (Plan §9.4/§9.5 & Review Finding R5):
- Preserves the complete canonical serializer API (`SerializationBudget`,
  `SerializationResult`, `serialize_frame_locals`, `serialize_value`, `_safe_type_name`)
  AND exports `safe_repr` and `sanitize_Locals`.
- NEVER invokes untrusted `__repr__`, `__str__`, `__iter__`, `__len__`, `__getitem__`,
  `__getattr__`, `__getattribute__`, `__eq__`, `__hash__`, or custom metaclass
  descriptors/properties (including a hostile `@property def __name__(cls)` on a
  custom metaclass).
- In `_safe_type_name(val)`, `object.__getattribute__(cls, "__name__")` is NOT used
  because `type(cls)` is the metaclass and `object.__getattribute__` still invokes
  data descriptors on `type(cls)`! Instead, we inspect `type.__dict__["__name__"].__get__(cls, type)`
  ONLY when `type(cls) is type`, and otherwise inspect `type.__dict__["__dict__"].__get__(cls, type(cls))`
  for a plain `str` `"__name__"` entry or fall back to `"untrusted_object"`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import FrameType, FunctionType, GeneratorType, ModuleType
from typing import Any

MAX_REPR_CHARS = 160
MAX_COLLECTION_ITEMS = 12
MAX_RECURSION_DEPTH = 3
MAX_TRACKED_LOCALS = 16

_REDACTED_LOCAL_NAMES: frozenset[str] = frozenset(
    {
        "__annotations__",
        "__builtins__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "__vcc_tracer__",
        "__vcc_payload__",
        "__vcc_runner__",
    }
)


@dataclass(frozen=True)
class SerializationBudget:
    """Bounds enforced while serializing frame local snapshots."""

    max_depth: int = 4
    max_items: int = 20
    max_str_len: int = 128
    max_int_bits: int = 256
    max_nodes: int = 250


@dataclass(frozen=True)
class SerializationResult:
    """Result of safely serializing a value or frame locals dictionary."""

    value: Any
    truncated_values: list[str] = field(default_factory=list)
    nodes_visited: int = 0


def _safe_type_name(val: object) -> str:
    """Return a bounded class name without invoking any instance or metaclass descriptor (R5)."""
    cls = type(val)
    if type(cls) is type:
        try:
            raw_name = type.__dict__["__name__"].__get__(cls, type)
            if type(raw_name) is str:
                return raw_name[:64]
        except Exception:
            pass
        return "untrusted_object"

    try:
        cls_dict = type.__dict__["__dict__"].__get__(cls, type(cls))
        raw_name = cls_dict.get("__name__")
        if type(raw_name) is str:
            return raw_name[:64]
    except Exception:
        pass
    return "untrusted_object"


class _SafeSerializerState:
    def __init__(self, budget: SerializationBudget) -> None:
        self.budget = budget
        self.nodes_visited: int = 0
        self.active_ids: set[int] = set()
        self.truncated_paths: list[str] = []
        self._truncated_set: set[str] = set()

    def mark_truncated(self, path: str, reason: str) -> None:
        marker = f"{path}:{reason}" if path else reason
        if marker not in self._truncated_set:
            self._truncated_set.add(marker)
            self.truncated_paths.append(marker)

    def serialize(self, val: object, path: str, depth: int) -> Any:
        self.nodes_visited += 1
        if self.nodes_visited > self.budget.max_nodes:
            self.mark_truncated(path, "max_nodes")
            return {"__vcc_truncated__": "max_nodes"}

        val_type = type(val)

        if val is None:
            return None

        if val_type is bool:
            return True if val else False

        if val_type is int:
            bit_len = int.bit_length(val)
            if bit_len > self.budget.max_int_bits:
                self.mark_truncated(path, "max_int_bits")
                sign = "-" if val < 0 else "+"
                return {
                    "__vcc_truncated__": "max_int_bits",
                    "sign": sign,
                    "bit_length": bit_len,
                }
            return int(val)

        if val_type is float:
            if math.isnan(val):
                return {"__vcc_float__": "NaN"}
            if math.isinf(val):
                return {"__vcc_float__": "Infinity" if val > 0 else "-Infinity"}
            return float(val)

        if val_type is str:
            str_len = str.__len__(val)
            if str_len > self.budget.max_str_len:
                self.mark_truncated(path, "max_str_len")
                prefix = str.__getitem__(val, slice(0, self.budget.max_str_len))
                return prefix + "...[truncated]"
            return val

        if any(val_type is builtin for builtin in (list, tuple, set, frozenset, dict)):
            obj_id = id(val)
            if obj_id in self.active_ids:
                self.mark_truncated(path, "cycle")
                return {
                    "__vcc_cycle__": _safe_type_name(val),
                }

            if depth >= self.budget.max_depth:
                self.mark_truncated(path, "max_depth")
                return {
                    "__vcc_truncated__": "max_depth",
                    "type": _safe_type_name(val),
                }

            self.active_ids.add(obj_id)
            try:
                if val_type is list:
                    return self._serialize_sequence(val, path, depth)
                if val_type is tuple:
                    return self._serialize_sequence(val, path, depth)
                if val_type is set:
                    return self._serialize_set(val, path, depth)
                if val_type is frozenset:
                    return self._serialize_set(val, path, depth)
                if val_type is dict:
                    return self._serialize_dict(val, path, depth)
            finally:
                self.active_ids.discard(obj_id)

        return {"__vcc_untrusted_type__": _safe_type_name(val)}

    def _serialize_sequence(
        self, seq: list[Any] | tuple[Any, ...], path: str, depth: int
    ) -> list[Any]:
        out: list[Any] = []
        limit = self.budget.max_items
        iterator = list.__iter__(seq) if type(seq) is list else tuple.__iter__(seq)
        for idx, item in enumerate(iterator):
            if idx >= limit:
                self.mark_truncated(path, "max_items")
                break
            child_path = f"{path}[{idx}]" if path else f"[{idx}]"
            out.append(self.serialize(item, child_path, depth + 1))
            if self.nodes_visited > self.budget.max_nodes:
                break
        return out

    def _serialize_set(
        self, s: set[Any] | frozenset[Any], path: str, depth: int
    ) -> list[Any]:
        iterator = set.__iter__(s) if type(s) is set else frozenset.__iter__(s)
        out: list[Any] = []
        limit = self.budget.max_items
        for idx, item in enumerate(iterator):
            if idx >= limit:
                self.mark_truncated(path, "max_items")
                break
            child_path = f"{path}{{{idx}}}" if path else f"{{{idx}}}"
            out.append(self.serialize(item, child_path, depth + 1))
            if self.nodes_visited > self.budget.max_nodes:
                break
        return out

    def _serialize_dict(
        self, d: dict[Any, Any], path: str, depth: int
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        limit = self.budget.max_items
        for idx, (k, v) in enumerate(dict.items(d)):
            if idx >= limit:
                self.mark_truncated(path, "max_items")
                break
            key_str = self._safe_dict_key(k, f"{path}.<key[{idx}]>" if path else f"<key[{idx}]>")
            child_path = f"{path}.{key_str}" if path else key_str
            out[key_str] = self.serialize(v, child_path, depth + 1)
            if self.nodes_visited > self.budget.max_nodes:
                break
        return out

    def _safe_dict_key(self, k: object, key_path: str) -> str:
        k_type = type(k)
        if k_type is str:
            if str.__len__(k) > self.budget.max_str_len:
                self.mark_truncated(key_path, "max_str_len")
                return str.__getitem__(k, slice(0, self.budget.max_str_len)) + "...[truncated]"
            return k
        if k is None:
            return "null"
        if k_type is bool:
            return "true" if k else "false"
        if k_type is int:
            if int.bit_length(k) > self.budget.max_int_bits:
                self.mark_truncated(key_path, "max_int_bits")
                return f"<int:{int.bit_length(k)}bits>"
            return int.__str__(k)
        if k_type is float:
            if math.isnan(k):
                return "NaN"
            if math.isinf(k):
                return "Infinity" if k > 0 else "-Infinity"
            return float.__str__(k)
        return f"<untrusted_key:{_safe_type_name(k)}>"


def serialize_value(
    val: object,
    budget: SerializationBudget | None = None,
    *,
    max_depth: int = 4,
    max_items: int = 20,
    max_str_len: int = 128,
    max_int_bits: int = 256,
    max_nodes: int = 250,
    root_path: str = "root",
) -> SerializationResult:
    effective_budget = budget or SerializationBudget(
        max_depth=max_depth,
        max_items=max_items,
        max_str_len=max_str_len,
        max_int_bits=max_int_bits,
        max_nodes=max_nodes,
    )
    state = _SafeSerializerState(effective_budget)
    serialized = state.serialize(val, root_path, depth=0)
    return SerializationResult(
        value=serialized,
        truncated_values=state.truncated_paths,
        nodes_visited=state.nodes_visited,
    )


def serialize_frame_locals(
    raw_locals: object,
    budget: SerializationBudget | None = None,
    *,
    max_depth: int = 4,
    max_items: int = 20,
    max_str_len: int = 128,
    max_int_bits: int = 256,
    max_nodes: int = 250,
) -> tuple[dict[str, Any], list[str]]:
    effective_budget = budget or SerializationBudget(
        max_depth=max_depth,
        max_items=max_items,
        max_str_len=max_str_len,
        max_int_bits=max_int_bits,
        max_nodes=max_nodes,
    )
    state = _SafeSerializerState(effective_budget)
    snapshot: dict[str, Any] = {}

    if type(raw_locals) is not dict:
        state.mark_truncated("locals", "non_dict_locals")
        return snapshot, state.truncated_paths

    count = 0
    for k, v in dict.items(raw_locals):
        if type(k) is not str:
            continue
        if k in _REDACTED_LOCAL_NAMES or str.startswith(k, "__vcc_"):
            continue
        if count >= effective_budget.max_items:
            state.mark_truncated("locals", "max_items")
            break
        count += 1
        snapshot[k] = state.serialize(v, k, depth=1)
        if state.nodes_visited > effective_budget.max_nodes:
            break

    return snapshot, state.truncated_paths


def safe_repr(
    val: Any,
    *,
    max_chars: int = MAX_REPR_CHARS,
    max_items: int = MAX_COLLECTION_ITEMS,
    _depth: int = 0,
    _active_ids: set[int] | None = None,
) -> str:
    """Produce a bounded, deterministic, hook-free string representation of `val`."""
    t = type(val)

    if val is None:
        return "None"
    if t is bool:
        return "True" if val else "False"
    if t is int:
        if int.bit_length(val) > 512:
            sign = "-" if val < 0 else "+"
            return f"<int {sign}{int.bit_length(val)}bits>"
        s = int.__repr__(val)
        return s if len(s) <= max_chars else s[: max_chars - 3] + "..."
    if t is float:
        if math.isnan(val):
            return "nan"
        if math.isinf(val):
            return "inf" if val > 0 else "-inf"
        s = float.__repr__(val)
        return s if len(s) <= max_chars else s[: max_chars - 3] + "..."
    if t is str:
        clipped = val if str.__len__(val) <= max_chars else str.__getitem__(val, slice(0, max_chars - 3)) + "..."
        s = str.__repr__(clipped)
        return s if len(s) <= max_chars else s[: max_chars - 3] + "..."
    if t is bytes:
        return f"<bytes len={bytes.__len__(val)}>"

    active = _active_ids if _active_ids is not None else set()
    if any(t is builtin for builtin in (list, tuple, set, frozenset, dict)):
        obj_id = id(val)
        if obj_id in active:
            return f"<cycle {_safe_type_name(val)}>"
        if _depth >= MAX_RECURSION_DEPTH:
            if t is list:
                return f"[... len={list.__len__(val)}]"
            if t is tuple:
                return f"(... len={tuple.__len__(val)})"
            if t is dict:
                return f"{{... len={dict.__len__(val)}}}"
            if t is set:
                return f"set(... len={set.__len__(val)})"
            return f"frozenset(... len={frozenset.__len__(val)})"

        active.add(obj_id)
        try:
            if t is list:
                n = list.__len__(val)
                parts: list[str] = []
                for idx, item in enumerate(list.__iter__(val)):
                    if idx >= max_items:
                        parts.append(f"... (+{n - max_items} more)")
                        break
                    parts.append(
                        safe_repr(
                            item,
                            max_chars=max(24, max_chars // 2),
                            max_items=max_items,
                            _depth=_depth + 1,
                            _active_ids=active,
                        )
                    )
                rendered = "[" + ", ".join(parts) + "]"
                return rendered if len(rendered) <= max_chars else rendered[: max_chars - 3] + "..."

            if t is tuple:
                n = tuple.__len__(val)
                parts = []
                for idx, item in enumerate(tuple.__iter__(val)):
                    if idx >= max_items:
                        parts.append(f"... (+{n - max_items} more)")
                        break
                    parts.append(
                        safe_repr(
                            item,
                            max_chars=max(24, max_chars // 2),
                            max_items=max_items,
                            _depth=_depth + 1,
                            _active_ids=active,
                        )
                    )
                suffix = "," if n == 1 else ""
                rendered = "(" + ", ".join(parts) + suffix + ")"
                return rendered if len(rendered) <= max_chars else rendered[: max_chars - 3] + "..."

            if t is set or t is frozenset:
                n = set.__len__(val) if t is set else frozenset.__len__(val)
                if n == 0:
                    return "set()" if t is set else "frozenset()"
                parts = []
                iterator = set.__iter__(val) if t is set else frozenset.__iter__(val)
                for idx, item in enumerate(iterator):
                    if idx >= max_items:
                        parts.append(f"... (+{n - max_items} more)")
                        break
                    parts.append(
                        safe_repr(
                            item,
                            max_chars=max(24, max_chars // 2),
                            max_items=max_items,
                            _depth=_depth + 1,
                            _active_ids=active,
                        )
                    )
                rendered = "{" + ", ".join(parts) + "}"
                return rendered if len(rendered) <= max_chars else rendered[: max_chars - 3] + "..."

            if t is dict:
                n = dict.__len__(val)
                parts = []
                for idx, (k, v) in enumerate(dict.items(val)):
                    if idx >= max_items:
                        parts.append(f"... (+{n - max_items} more)")
                        break
                    kr = safe_repr(k, max_chars=40, max_items=4, _depth=_depth + 1, _active_ids=active)
                    vr = safe_repr(
                        v,
                        max_chars=max(24, max_chars // 2),
                        max_items=max_items,
                        _depth=_depth + 1,
                        _active_ids=active,
                    )
                    parts.append(f"{kr}: {vr}")
                rendered = "{" + ", ".join(parts) + "}"
                return rendered if len(rendered) <= max_chars else rendered[: max_chars - 3] + "..."
        finally:
            active.discard(obj_id)

    if any(t is builtin for builtin in (FunctionType, GeneratorType, ModuleType, FrameType)) or t is type:
        return f"<{_safe_type_name(val)}>"

    return f"<{_safe_type_name(val)} object>"


def sanitize_Locals(
    raw_locals: dict[str, Any],
    *,
    max_locals: int = MAX_TRACKED_LOCALS,
    max_chars: int = MAX_REPR_CHARS,
) -> dict[str, str]:
    """Sanitize a frame's `f_locals` dictionary into hook-free string representations."""
    if type(raw_locals) is not dict:
        return {}
    out: dict[str, str] = {}
    count = 0
    for key, val in dict.items(raw_locals):
        if type(key) is not str:
            continue
        if key in _REDACTED_LOCAL_NAMES or str.startswith(key, "__"):
            continue
        if type(val) in (ModuleType, FunctionType, FrameType) or type(val) is type:
            continue
        out[str.__getitem__(key, slice(0, 64))] = safe_repr(val, max_chars=max_chars)
        count += 1
        if count >= max_locals:
            break
    return out
