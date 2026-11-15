"""Explicit local server startup. Default preview is credential-free.

Run with --env-file /absolute/path/.env only when server-side live configuration
is intended. This is not a provider smoke and does not issue requests at startup.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

IMPLEMENTATION = Path(__file__).resolve().parents[1]
WORKSPACE = IMPLEMENTATION.parent


def preview_environment(environment: dict[str, str]) -> dict[str, str]:
    clean = {
        key: value
        for key, value in environment.items()
        if not any(marker in key.upper() for marker in ("API_KEY", "TOKEN", "SECRET"))
        and key
        not in {"VCC_ENV_FILE", "GNANI_API_KEY_ID", "VCC_ISOLATION_ACCEPTANCE_FILE"}
    }
    runtime = WORKSPACE / "data" / "credential-free-preview"
    return {
        **clean,
        "VCC_GNANI_API_KEY": "",
        "VCC_GROQ_API_KEY": "",
        "VCC_INTERNAL_WORKER_SECRET": "",
        "VCC_OPERATIONS_TOKEN": "",
        "VCC_ALLOW_PUBLIC_CUSTOM_CODE": "false",
        "VCC_LLM_PROVIDER": "deterministic",
        "VCC_DATABASE_PATH": str(runtime / "vcc.db"),
        "VCC_TTS_CACHE_DIR": str(runtime / "tts"),
        "VCC_CORS_ORIGINS": "http://localhost:5180,http://127.0.0.1:5180",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start the local coordinator with explicit server configuration."
    )
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument(
        "--env-file", type=Path, help="Explicit private server-side environment file."
    )
    choice.add_argument(
        "--preview",
        action="store_true",
        help="Credential-free isolated preview (default).",
    )
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument(
        "--reload",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reload backend source changes (default); --no-reload disables watching.",
    )
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged valid port.")
    if args.env_file:
        path = args.env_file.expanduser().resolve()
        if not path.is_file():
            parser.error("The explicitly selected environment file is unavailable.")
        os.environ["VCC_ENV_FILE"] = str(path)
    else:
        clean = preview_environment(dict(os.environ))
        os.environ.clear()
        os.environ.update(clean)
    os.chdir(WORKSPACE)
    sys.path.insert(0, str(IMPLEMENTATION))
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host="127.0.0.1",
        port=args.port,
        workers=1,
        proxy_headers=False,
        reload=args.reload,
        reload_dirs=[str(IMPLEMENTATION / "backend" / "app")] if args.reload else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
