"""Trusted catalog, typed contracts and server-only oracles; never learner execution."""
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import inspect
import json
from pathlib import Path

from . import oracles
from .catalog_data import expanded_packages
from .catalog_validator import load_catalog as _load_catalog, validate_catalog as _validate_catalog
from .ex1_shortest_subarray import shortest_subarray_ge_target
from .ex2_binary_search import first_at_least
from .ex3_max_product import max_product_subarray
from .legacy_data import LEGACY_METADATA
from .values import MAX_INTEGER, strict_equal, validate_arguments, validate_value


@dataclass(frozen=True)
class ExerciseSpec:
    exercise_id: str
    spec_version: str
    function_name: str
    min_length: int = 0
    max_length: int = 16
    min_value: int = -50
    max_value: int = 50
    target_bounds: tuple[int, int] | None = None
    sorted_required: bool = False
    input_schema: dict | None = None
    output_schema: dict | None = None


_LEGACY_SPECS = (
    ExerciseSpec('ex1_shortest_subarray', 'v1_positive_only', 'shortest_subarray_ge_target', 1, 15, 1, 50, (1, 200)),
    ExerciseSpec('ex1_shortest_subarray', 'v2_negatives_allowed', 'shortest_subarray_ge_target', 1, 15, -20, 50, (1, 200)),
    ExerciseSpec('ex2_binary_search', 'v1_sorted_with_duplicates', 'first_at_least', 0, 15, -50, 50, (-60, 60), True),
    ExerciseSpec('ex3_max_product', 'v1_bounded_ints', 'max_product_subarray', 1, 12, -10, 10),
)
_ORACLES = {
    'shortest_subarray_ge_target': shortest_subarray_ge_target,
    'first_at_least': first_at_least,
    'max_product_subarray': max_product_subarray,
    **{row['function_name']: getattr(oracles, row['function_name']) for row in expanded_packages()},
}


def _legacy_rules(spec: ExerciseSpec) -> tuple[dict, dict]:
    inputs = {'nums': {'kind': 'list', 'min_length': spec.min_length, 'max_length': spec.max_length,
        'items': {'kind': 'integer', 'minimum': spec.min_value, 'maximum': spec.max_value}, 'sorted_required': spec.sorted_required}}
    if spec.target_bounds:
        inputs['target'] = {'kind': 'integer', 'minimum': spec.target_bounds[0], 'maximum': spec.target_bounds[1]}
    return inputs, {'kind': 'integer', 'minimum': -MAX_INTEGER, 'maximum': MAX_INTEGER}


def _manifest_cases(exercise_id: str, spec_version: str, pool: str) -> list[dict]:
    manifest = json.loads(Path(__file__).with_name('case_manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['specifications']:
        if (entry['exercise_id'], entry['spec_version']) == (exercise_id, spec_version):
            return deepcopy(entry[pool])
    raise ValueError('Missing legacy manifest entry')


def _legacy_packages() -> list[dict]:
    examples = [({'nums': [2, 5, 1], 'target': 6}, 2), ({'nums': [0, 4, 8], 'target': 3}, 1), ({'nums': [2, -1, -3]}, 6)]
    result = []
    for index, meta in enumerate(LEGACY_METADATA):
        ex, version = meta['exercise_id'], meta['default_spec_version']
        specs = []
        for spec in _LEGACY_SPECS:
            if spec.exercise_id == ex:
                inputs, output = _legacy_rules(spec)
                specs.append({'spec_version': spec.spec_version, 'label': spec.spec_version.replace('_', ' ').title(), 'input_schema': inputs, 'output_schema': output})
        inputs, output = next((s['input_schema'], s['output_schema']) for s in specs if s['spec_version'] == version)
        curriculum, holdout = _manifest_cases(ex, version, 'curriculum'), _manifest_cases(ex, version, 'holdout')
        function = _ORACLES[meta['function_name']]
        alt = inspect.getsource(function)
        bug = alt.replace('end - start + 1', 'end - start') if index == 0 else alt.replace('value >= target', 'value > target') if index == 1 else alt.replace('best = nums[0]', 'best = 0')
        witness = {'nums': [5], 'target': 5} if index == 0 else {'nums': [4], 'target': 4} if index == 1 else {'nums': [-5]}
        result.append({**deepcopy(meta), 'spec_versions': specs, 'input_schema': inputs, 'output_schema': output,
            'tags': [c.lower().replace(' ', '-') for c in meta['core_concepts']], 'collection': 'Original Coaching Collection',
            'comparator': 'strict_structural', 'catalog_status': 'READY',
            'provenance': {'source': 'original', 'status': 'ORIGINAL_AUTHORED', 'license': None},
            'examples': [{'input_args': examples[index][0], 'output': examples[index][1], 'explanation': 'Apply the stated boundary and contiguous/index rules exactly.'}],
            'curriculum': curriculum, 'holdout': holdout, 'boundary': curriculum[:4],
            'generated': {'kind': 'schema_bounded', 'seed': index+1, 'max_cases': 100},
            'known_bugs': [{'label': 'Boundary regression', 'source_code': bug, 'witness': witness}],
            'alternatives': [{'label': 'Direct reference scan alternative', 'source_code': alt}],
            'hints': {'1': 'Which contract boundary matters on this input?', '2': 'Inspect an attributed step near the return.', '3': 'Preserve the boundary invariant while updating state.'},
        })
    return result


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict, ...]:
    packages = _validate_catalog(_legacy_packages() + expanded_packages(), set(_ORACLES))
    for package in packages:
        for example in package['examples']:
            actual = _ORACLES[package['function_name']](**deepcopy(example['input_args']))
            if not strict_equal(actual, example['output']):
                raise ValueError(f"Incorrect authored example: {package['exercise_id']}")
    return tuple(packages)


def catalog_packages() -> list[dict]:
    return deepcopy(list(_catalog()))


def validate_catalog(packages: object) -> list[dict]:
    validated = _validate_catalog(packages, set(_ORACLES))
    authoritative = {p['exercise_id']: p for p in _catalog()}
    for package in validated:
        canonical = authoritative.get(package['exercise_id'])
        if canonical is None:
            raise ValueError('Imported exercise has no pinned trusted oracle contract')
        for field in ('function_name', 'default_spec_version', 'input_schema', 'output_schema', 'spec_versions'):
            if package[field] != canonical[field]:
                raise ValueError('Imported metadata cannot change the pinned server value domain or specification')
        for example in package['examples']:
            actual = evaluate(package['exercise_id'], package['default_spec_version'], example['input_args'])
            if not strict_equal(actual, example['output']):
                raise ValueError('Imported example disagrees with the trusted server oracle')
    return validated


def load_catalog(path: str | Path) -> list[dict]:
    return validate_catalog(_load_catalog(path, set(_ORACLES)))


def list_specs() -> tuple[ExerciseSpec, ...]:
    result = []
    for package in _catalog():
        for entry in package['spec_versions']:
            legacy = next((s for s in _LEGACY_SPECS if (s.exercise_id, s.spec_version) == (package['exercise_id'], entry['spec_version'])), None)
            kwargs = vars(legacy).copy() if legacy else {'exercise_id': package['exercise_id'], 'spec_version': entry['spec_version'], 'function_name': package['function_name']}
            result.append(ExerciseSpec(**{**kwargs, 'input_schema': deepcopy(entry['input_schema']), 'output_schema': deepcopy(entry['output_schema'])}))
    return tuple(result)


@lru_cache(maxsize=1)
def _trusted_specs() -> tuple[ExerciseSpec, ...]:
    return list_specs()


def get_spec(exercise_id: str, spec_version: str) -> ExerciseSpec:
    for spec in _trusted_specs():
        if (spec.exercise_id, spec.spec_version) == (exercise_id, spec_version):
            return deepcopy(spec)
    raise ValueError('Unsupported exercise/specification combination')


def generated_case_capacity(exercise_id: str, spec_version: str, exclude_hashes: set[str] | None = None) -> int:
    """Exact small scalar-domain capacity, otherwise the 200-case engine ceiling."""
    schema = get_spec(exercise_id, spec_version).input_schema
    cardinality = 1
    for rule in schema.values():
        if rule['kind'] == 'integer':
            cardinality *= rule['maximum'] - rule['minimum'] + 1
        elif rule['kind'] == 'boolean':
            cardinality *= 2
        else:
            return 200
    reserved = {case_key(exercise_id, spec_version, c) for c in cases(exercise_id, spec_version, 'holdout')}
    reserved |= set(exclude_hashes or ())
    return max(0, min(200, cardinality - len(reserved)))


def bounded_generated_target(exercise_id: str, spec_version: str, count: int, inputs: list[dict]) -> int:
    excluded = {case_key(exercise_id, spec_version, c) for c in inputs}
    return min(count, generated_case_capacity(exercise_id, spec_version, excluded))


def validate_input(exercise_id: str, spec_version: str, input_args: object) -> dict:
    return validate_arguments(input_args, get_spec(exercise_id, spec_version).input_schema)


def validate_output(exercise_id: str, spec_version: str, output: object) -> object:
    return validate_value(output, get_spec(exercise_id, spec_version).output_schema)


def validate_prediction(exercise_id: str, spec_version: str, prediction: object) -> object:
    rule = get_spec(exercise_id, spec_version).output_schema
    shape = {'kind': rule['kind']}
    if rule['kind'] == 'list':
        shape['items'] = {'kind': rule['items']['kind']}
    return validate_value(prediction, shape)


def evaluate(exercise_id: str, spec_version: str, input_args: object) -> object:
    arguments = validate_input(exercise_id, spec_version, input_args)
    result = _ORACLES[get_spec(exercise_id, spec_version).function_name](**arguments)
    return validate_output(exercise_id, spec_version, result)


def compare_output(student_output: object, reference_output: object) -> bool:
    return strict_equal(student_output, reference_output)


def case_key(exercise_id: str, spec_version: str, input_args: object) -> str:
    args = validate_input(exercise_id, spec_version, input_args)
    canonical = json.dumps([exercise_id, spec_version, args], sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def cases(exercise_id: str, spec_version: str, pool: str) -> list[dict]:
    get_spec(exercise_id, spec_version)
    if pool not in ('curriculum', 'holdout', 'boundary'):
        raise ValueError('Unknown case pool')
    if any(s.exercise_id == exercise_id for s in _LEGACY_SPECS):
        return _manifest_cases(exercise_id, spec_version, 'curriculum' if pool == 'boundary' else pool)
    return deepcopy(next(p[pool] for p in _catalog() if p['exercise_id'] == exercise_id))


def hints(exercise_id: str) -> dict[str, str]:
    return deepcopy(next(p['hints'] for p in _catalog() if p['exercise_id'] == exercise_id))


def public_catalog() -> list[dict]:
    """Explicit allowlist: never serialize source fixtures or private test pools."""
    fields = ('exercise_id', 'title', 'function_name', 'difficulty', 'core_concepts', 'description', 'starter_code',
        'default_spec_version', 'input_schema', 'output_schema', 'examples', 'tags', 'collection', 'comparator', 'catalog_status', 'provenance')
    result = []
    for package in _catalog():
        specs = []
        for entry in package['spec_versions']:
            spec = get_spec(package['exercise_id'], entry['spec_version'])
            summary = [f'{name}: {json.dumps(rule, sort_keys=True)}' for name, rule in entry['input_schema'].items()]
            specs.append({**deepcopy(entry), 'min_length': spec.min_length, 'max_length': spec.max_length,
                'min_value': spec.min_value, 'max_value': spec.max_value, 'target_bounds': spec.target_bounds,
                'sorted_required': spec.sorted_required, 'constraints_summary': summary,
                'recommended_generated_cases': bounded_generated_target(spec.exercise_id, spec.spec_version, 20, cases(spec.exercise_id, spec.spec_version, 'curriculum')),
                'available_fresh_cases': len(cases(spec.exercise_id, spec.spec_version, 'holdout'))})
        result.append({**{field: deepcopy(package[field]) for field in fields}, 'spec_versions': specs})
    return result
