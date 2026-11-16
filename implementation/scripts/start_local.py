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
sys.path.insert(0, str(IMPLEMENTATION))
from backend.app.core.local_config import local_development


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
        "VCC_DATABASE_URL": "",
        "VCC_CLOUD_RUNTIME": "false",
        "VCC_CORS_ORIGINS": local_development(environment).cors_origins,
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
    local = local_development(os.environ)
    parser.add_argument("--port", type=int, default=local.backend_port)
    parser.add_argument("--frontend-port", type=int, default=local.frontend_port)
    parser.add_argument(
        "--reload",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reload backend source changes (default); --no-reload disables watching.",
    )
    args = parser.parse_args(argv)
    if not all(1024 <= port <= 65535 for port in (args.port, args.frontend_port)):
        parser.error("Use an unprivileged valid port.")
    if args.env_file:
        from backend.app.core.config import validate_env_file
        try:
            path = validate_env_file(args.env_file)
        except ValueError as exc:
            parser.error(str(exc))
        os.environ["VCC_ENV_FILE"] = str(path)
    elif not args.preview and os.environ.get('VCC_ENV_FILE', '').strip():
        from backend.app.core.config import validate_env_file
        try:
            os.environ['VCC_ENV_FILE'] = str(validate_env_file(os.environ['VCC_ENV_FILE']))
        except ValueError as exc:
            parser.error(str(exc))
    else:
        clean = preview_environment({**os.environ, 'VCC_FRONTEND_PORT': str(args.frontend_port)})
        os.environ.clear()
        os.environ.update(clean)
    os.environ['VCC_BACKEND_PORT'] = str(args.port)
    os.environ['VCC_FRONTEND_PORT'] = str(args.frontend_port)
    os.environ.setdefault('VCC_CORS_ORIGINS', local_development(os.environ).cors_origins)
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
