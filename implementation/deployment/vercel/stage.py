#!/usr/bin/env python3
"""Create a new, audited Vercel upload directory without deploying anything."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = PACKAGE_ROOT.parents[1]
MAX_UPLOAD_BYTES = 95 * 1024 * 1024  # Headroom below Hobby's 100 MB source limit.
FORBIDDEN_PARTS = {".git", ".vercel", "node_modules", "__pycache__", "tests", "data", "evidence", "imports"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".wav", ".mp3", ".pem", ".key", ".map"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_path(path: Path) -> None:
    if any(part in FORBIDDEN_PARTS or part.startswith((".env", ".venv")) for part in path.parts):
        raise ValueError(f"Forbidden upload path: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValueError(f"Forbidden upload file: {path}")


def source_files(source: Path, allowlist: dict) -> dict[Path, Path]:
    selected: dict[Path, Path] = {}
    for group in allowlist["groups"]:
        directory = source / group["source"]
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"Missing or linked runtime directory: {group['source']}")
        for pattern in group["patterns"]:
            for path in sorted(directory.glob(pattern)):
                if not path.is_file():
                    continue
                if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != source.parent):
                    raise ValueError(f"Linked runtime file: {path.relative_to(source)}")
                target = Path(group["destination"]) / path.relative_to(directory)
                validate_path(target)
                if path.resolve().is_relative_to(source.resolve()) is False:
                    raise ValueError(f"Runtime path escapes source: {path}")
                if target in selected and selected[target] != path:
                    raise ValueError(f"Duplicate upload path: {target}")
                selected[target] = path
    for required in allowlist["required"]:
        if Path(required) not in selected:
            raise ValueError(f"Required runtime file missing: {required}")
    for required in allowlist["required_directories"]:
        if not any(path.is_relative_to(required) for path in selected):
            raise ValueError(f"Required runtime directory empty: {required}")
    dist = source / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise ValueError("Build the frontend before staging: frontend/dist/index.html is missing")
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != source.parent):
            raise ValueError(f"Linked frontend asset: {path.relative_to(source)}")
        relative = path.relative_to(dist)
        validate_path(relative)
        if relative.parts[0].lower() in {"api", "ws", "backend", "config", "exec_worker"}:
            raise ValueError(f"Frontend asset shadows backend namespace: {relative}")
        if path.suffix.lower() not in allowlist["static_extensions"]:
            raise ValueError(f"Unexpected frontend asset extension: {relative}")
        selected[Path("public") / relative] = path
    selected[Path("frontend-index.html")] = dist / "index.html"
    return selected


def stage(source: Path, output: Path, manifest: Path) -> dict:
    source = source.resolve(strict=True)
    output = output.resolve()
    manifest = manifest.resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite an existing directory: {output}")
    if output.is_relative_to(source) or manifest.is_relative_to(output):
        raise ValueError("Keep the upload directory outside implementation/ and its manifest outside the upload")
    if manifest.exists():
        raise ValueError(f"Refusing to overwrite an existing manifest: {manifest}")
    policy = PACKAGE_ROOT / "allowlist.json"
    allowlist_bytes = policy.read_bytes()
    allowlist_hash = hashlib.sha256(allowlist_bytes).hexdigest()
    allowlist = json.loads(allowlist_bytes)
    selected = source_files(source, allowlist)
    source_hashes = {path: digest(original) for path, original in selected.items()}
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mentorly-stage-", dir=output.parent) as temporary:
        staged = Path(temporary) / "upload"
        staged.mkdir()
        for target, original in selected.items():
            destination = staged / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
            if digest(destination) != source_hashes[target] or digest(original) != source_hashes[target]:
                raise ValueError(f"Source changed while staging: {target}")
        for filename in ("api/index.py", "deployment_spa.py", "vercel.json", ".vercelignore"):
            template = PACKAGE_ROOT / "templates" / filename
            template_hash = digest(template)
            (staged / filename).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(template, staged / filename)
            if digest(staged / filename) != template_hash or digest(template) != template_hash:
                raise ValueError(f"Deployment template changed while staging: {filename}")
        requirements_path = PACKAGE_ROOT / "runtime-requirements.txt"
        requirements = requirements_path.read_text()
        requirements_hash = hashlib.sha256(requirements.encode()).hexdigest()
        (staged / "requirements.txt").write_text(requirements)
        dependencies = [line.strip() for line in requirements.splitlines() if line.strip() and not line.startswith("#")]
        (staged / "pyproject.toml").write_text(
            '[project]\nname = "mentorly-coordinator"\nversion = "0.1.0"\n'
            'requires-python = ">=3.12,<3.13"\ndependencies = [\n'
            + "".join(f"  {json.dumps(item)},\n" for item in dependencies)
            + ']\n'
        )
        (staged / ".python-version").write_text("3.12\n")
        files = []
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                files.append({"path": str(path.relative_to(staged)), "bytes": path.stat().st_size, "sha256": digest(path)})
        total_bytes = sum(item["bytes"] for item in files)
        if total_bytes > MAX_UPLOAD_BYTES or len(files) > 14000:
            raise ValueError(f"Upload exceeds conservative Hobby limit: {total_bytes} bytes, {len(files)} files")
        if source_files(source, allowlist) != selected:
            raise ValueError("Runtime file inventory changed while staging")
        if digest(policy) != allowlist_hash or digest(requirements_path) != requirements_hash:
            raise ValueError("Deployment policy or requirements changed while staging")
        for target, original in selected.items():
            if digest(original) != source_hashes[target]:
                raise ValueError(f"Source changed before staging completed: {target}")
        result = {"created_at": datetime.now(timezone.utc).isoformat(), "source": str(source),
                  "output": str(output), "file_count": len(files), "total_bytes": total_bytes,
                  "allowlist_sha256": allowlist_hash, "files": files}
        staged.rename(output)
        manifest.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Implementation directory")
    parser.add_argument("--output", type=Path, required=True, help="New upload directory outside implementation/")
    parser.add_argument("--manifest", type=Path, help="New inventory file outside the upload")
    args = parser.parse_args()
    manifest = args.manifest or args.output.with_name(args.output.name + ".manifest.json")
    try:
        result = stage(args.source, args.output, manifest)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Staging failed: {error}\n")
    print(json.dumps({key: result[key] for key in ("output", "file_count", "total_bytes", "allowlist_sha256")}, indent=2))


if __name__ == "__main__":
    main()
