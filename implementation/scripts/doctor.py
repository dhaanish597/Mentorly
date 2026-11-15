"""Credential-safe local diagnostics; never synthesizes speech or invokes a model."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.core.config import Settings, validate_env_file
from backend.app.core.local_config import LocalDevelopment, local_development
from backend.app.studio.feedback import model_readiness
from scripts.start_local import preview_environment


def health_probe(origin: str) -> bool:
    try:
        # The origin comes only from the validated loopback development config.
        request = Request(origin + '/api/v1/health', headers={'Accept': 'application/json'})
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            return response.status == 200 and isinstance(json.loads(response.read(65536)), dict)
    except (URLError, OSError, ValueError):
        return False


def diagnostics(settings: Settings, local: LocalDevelopment, probe=health_probe) -> dict:
    expected = set(local.cors_origins.split(','))
    return {
        'backend_address': local.backend_origin,
        'frontend_address': local.frontend_origin,
        'api_reachable': probe(local.backend_origin),
        'cors_match': expected.issubset(settings.cors_origins_list),
        'speech_provider': 'configured_unverified' if settings.gnani_api_key else 'disabled',
        'speech_effective_concurrency': settings.gnani_effective_concurrency,
        'model_readiness': model_readiness(settings),
        'database_backend': 'postgresql' if settings.database_url else 'sqlite',
        'execution_worker': 'required_unverified' if settings.allow_public_custom_code else 'disabled',
        'production_api_contract': 'same-origin /api/v1 reverse proxy required',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--offline', action='store_true', help='Skip even the local health request')
    args = parser.parse_args(argv)
    try:
        selected = args.env_file or os.environ.get('VCC_ENV_FILE', '').strip()
        if selected:
            settings = Settings(_env_file=validate_env_file(selected))
        else:
            clean = preview_environment(dict(os.environ))
            os.environ.clear()
            os.environ.update(clean)
            settings = Settings(_env_file=None)
        report = diagnostics(settings, local_development(os.environ), (lambda origin: False) if args.offline else health_probe)
    except (ValueError, OSError):
        print(json.dumps({'configuration_valid': False, 'error': 'Invalid explicit configuration; check file permissions and documented settings'}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if args.offline or report['api_reachable'] and report['cors_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
