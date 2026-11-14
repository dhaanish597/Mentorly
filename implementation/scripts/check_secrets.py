"""Basic secret hygiene check for Phase 0 repository files."""

from __future__ import annotations

from pathlib import Path
import re
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", ".pytest_cache"}
_SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9_]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_]{16,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main() -> int:
    violations: list[str] = []
    for path in _REPO_ROOT.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.name == ".env":
            violations.append(f"Committed .env file found: {path.relative_to(_REPO_ROOT)}")
            continue
        if not path.is_file() or path.suffix in {".png", ".jpg", ".wav", ".db", ".sqlite3"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(f"Potential secret pattern in {path.relative_to(_REPO_ROOT)}")

    if violations:
        for v in violations:
            print(v, file=sys.stderr)
        return 1

    print("Secret hygiene check passed (0 violations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
