"""Export or verify the coordinator OpenAPI 3.1 schema (R9 repaired)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.main import create_app  # noqa: E402


def _normalize_openapi_node(node: Any) -> Any:
    """Recursively normalize OpenAPI 3.1 schema dicts for deterministic cross-version output."""
    if isinstance(node, dict):
        cleaned = {k: _normalize_openapi_node(v) for k, v in sorted(node.items())}
        any_of = cleaned.get("anyOf")
        if (
            isinstance(any_of, list)
            and any(isinstance(item, dict) and item.get("type") == "null" for item in any_of)
            and "default" not in cleaned
        ):
            cleaned["default"] = None
            cleaned = {k: cleaned[k] for k in sorted(cleaned.keys())}
        return cleaned
    if isinstance(node, list):
        return [_normalize_openapi_node(item) for item in node]
    return node


def render_canonical_openapi() -> str:
    """Render deterministic OpenAPI 3.1 JSON string for the coordinator app."""
    app = create_app()
    schema = _normalize_openapi_node(app.openapi())
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or verify OpenAPI schema.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only check that openapi.json matches the canonical app schema",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_BACKEND_DIR / "openapi.json",
        help="Target OpenAPI JSON path",
    )
    args = parser.parse_args(argv)

    rendered = render_canonical_openapi()

    if args.check:
        if not args.output.is_file():
            print(f"OpenAPI schema file missing: {args.output}", file=sys.stderr)
            return 1
        existing = args.output.read_text(encoding="utf-8")
        if existing != rendered:
            print(f"OpenAPI schema drift detected in {args.output}", file=sys.stderr)
            return 1
        print(f"OpenAPI schema matches {args.output}")
        return 0

    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote OpenAPI schema to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
