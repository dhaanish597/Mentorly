"""Deep grounded repository analysis and architectural discovery."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


ENTRYPOINT_PATTERNS = (
    r"(?:^|/)(?:main|app|server|index|cli|manage|run|wsgi|asgi)\.(?:py|ts|js|jsx|tsx|go|rs)$",
    r"(?:^|/)__main__\.py$",
    r"(?:^|/)cmd/[^/]+/main\.go$",
)

FRAMEWORK_SIGNATURES = {
    "FastAPI": (r"from fastapi import", r"import fastapi", r"FastAPI\("),
    "Flask": (r"from flask import", r"import flask", r"Flask\("),
    "Django": (r"django", r"from django"),
    "React": (r"from ['\"]react['\"]", r"import React", r"['\"]react['\"]"),
    "Next.js": (r"from ['\"]next/", r"next/router", r"next/navigation"),
    "Express": (r"require\(['\"]express['\"]\)", r"from ['\"]express['\"]", r"express\(\)"),
    "SQLAlchemy": (r"from sqlalchemy", r"import sqlalchemy", r"declarative_base"),
    "Pydantic": (r"from pydantic import", r"import pydantic", r"BaseModel"),
    "Pytest": (r"import pytest", r"def test_"),
    "Docker": (r"FROM ", r"ENTRYPOINT "),
}


def analyze_repository(files: dict[str, str], structures: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Extract entrypoints, frameworks, modules, models, endpoints, and architectural overview."""
    entry_points: list[str] = []
    frameworks: set[str] = set()
    database_models: list[dict[str, str]] = []
    api_endpoints: list[dict[str, str]] = []
    components: dict[str, list[str]] = {
        "api": [],
        "models": [],
        "services": [],
        "core": [],
        "database": [],
        "speech": [],
        "tests": [],
        "other": [],
    }

    readme_content = ""
    for path, content in files.items():
        lower_path = path.lower()
        if lower_path in ("readme.md", "readme.rst", "readme.txt", "readme"):
            readme_content = content[:1500]

        # Entry points
        for pat in ENTRYPOINT_PATTERNS:
            if re.search(pat, path, re.IGNORECASE):
                entry_points.append(path)
                break

        # Framework detection
        for fw, sigs in FRAMEWORK_SIGNATURES.items():
            if any(re.search(sig, content) for sig in sigs):
                frameworks.add(fw)

        # Categorize by directory / role
        parts = PurePosixPath(path).parts
        categorized = False
        for part in parts:
            part_lower = part.lower()
            if "test" in part_lower:
                components["tests"].append(path)
                categorized = True
                break
            elif part_lower in ("api", "routes", "routers", "endpoints"):
                components["api"].append(path)
                categorized = True
                break
            elif part_lower in ("models", "schemas", "entities"):
                components["models"].append(path)
                categorized = True
                break
            elif part_lower in ("services", "controllers", "handlers"):
                components["services"].append(path)
                categorized = True
                break
            elif part_lower in ("core", "config", "settings"):
                components["core"].append(path)
                categorized = True
                break
            elif part_lower in ("db", "database", "migrations"):
                components["database"].append(path)
                categorized = True
                break
            elif part_lower in ("speech", "voice", "audio"):
                components["speech"].append(path)
                categorized = True
                break
        if not categorized:
            components["other"].append(path)

        # Extract models & endpoints from Python structure
        struct = structures.get(path, {})
        for sym in struct.get("symbols", []):
            name = sym.get("name", "")
            # Models
            if any(marker in name.lower() for marker in ("model", "schema", "entity", "dto", "table", "base")):
                database_models.append({
                    "path": path,
                    "name": name,
                    "start_line": sym.get("start_line", 1),
                    "end_line": sym.get("end_line", 1),
                })

        # Search for route definitions
        for match in re.finditer(r'@(?:app|router)\.(get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]', content):
            method, route_path = match.groups()
            line_num = content[:match.start()].count("\n") + 1
            api_endpoints.append({
                "method": method.upper(),
                "path": route_path,
                "file": path,
                "line": line_num,
            })

    # Deduplicate and sort
    sorted_entry_points = sorted(set(entry_points))
    sorted_frameworks = sorted(frameworks)
    top_models = database_models[:20]
    top_endpoints = api_endpoints[:30]

    # Generate architectural summary text
    primary_language = "Python"
    lang_counts: dict[str, int] = {}
    for st in structures.values():
        lang = st.get("language", "text")
        if lang != "text":
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    if lang_counts:
        primary_language = max(lang_counts.items(), key=lambda kv: kv[1])[0].capitalize()

    fw_str = ", ".join(sorted_frameworks[:4]) if sorted_frameworks else primary_language
    overview_sentences = [
        f"This repository is primarily built with {primary_language} using {fw_str}.",
    ]
    if sorted_entry_points:
        overview_sentences.append(f"Application entry points include `{sorted_entry_points[0]}`.")
    if components["api"]:
        overview_sentences.append(f"HTTP and API routing is handled under `{PurePosixPath(components['api'][0]).parent}`.")
    if components["models"]:
        overview_sentences.append(f"Data domain and validation models are concentrated in `{PurePosixPath(components['models'][0]).parent}`.")

    summary_text = " ".join(overview_sentences)

    return {
        "primary_language": primary_language,
        "frameworks": sorted_frameworks,
        "entry_points": sorted_entry_points,
        "component_counts": {k: len(v) for k, v in components.items()},
        "database_models": top_models,
        "api_endpoints": top_endpoints,
        "overview": summary_text,
        "readme_excerpt": readme_content[:500].strip(),
    }
