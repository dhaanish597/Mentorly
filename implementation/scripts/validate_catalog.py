"""Validate original catalog data, trusted examples and bounded case generation.

Import accepts JSON data only. Source fixtures are syntax-checked, never executed
by this script or the engine tests. Behavioral source-fixture checks require the
accepted isolated runsc worker; no host Python fallback is provided.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.exercises import registry  # noqa: E402
from backend.app.verification.hypothesis_strategies import generate_property_batch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, help='Validate a data-only JSON package list without installing it')
    args = parser.parse_args()
    try:
        packages = registry.load_catalog(args.catalog) if args.catalog else registry.catalog_packages()
        registry.validate_catalog(packages)
        counts = {'problems': len(packages), 'specifications': 0, 'curated_cases': 0, 'transfer_cases': 0,
                  'generated_cases': 0, 'examples': sum(len(p['examples']) for p in packages),
                  'known_bug_fixtures': sum(len(p['known_bugs']) for p in packages),
                  'alternative_fixtures': sum(len(p['alternatives']) for p in packages), 'fixture_execution': 'NOT_RUN_DATA_ONLY'}
        # Imported packages are validated but never registered or executable.
        if args.catalog is None:
            for spec in registry.list_specs():
                ex, version = spec.exercise_id, spec.spec_version
                curriculum = registry.cases(ex, version, 'curriculum')
                holdout = registry.cases(ex, version, 'holdout')
                hashes = {registry.case_key(ex, version, c) for c in curriculum}
                if hashes & {registry.case_key(ex, version, c) for c in holdout}:
                    raise ValueError('Private case pools overlap')
                target = registry.bounded_generated_target(ex, version, 20, curriculum)
                batch = generate_property_batch(ex, version, count=target, seed=42, exclude_hashes=hashes)
                if len(batch.cases) != target:
                    raise ValueError(f'Generated catalog policy underfilled for {ex}/{version}: {len(batch.cases)}/{target}')
                for case in curriculum + holdout + list(batch.cases):
                    registry.validate_output(ex, version, registry.evaluate(ex, version, case))
                counts['specifications'] += 1
                counts['curated_cases'] += len(curriculum)
                counts['transfer_cases'] += len(holdout)
                counts['generated_cases'] += len(batch.cases)
        print(json.dumps({'status': 'VALID', **counts}, sort_keys=True))
        return 0
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({'status': 'INVALID', 'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
