"""Data-only catalog import gate: validates metadata, never evaluates fixture code."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import re

from .values import validate_arguments, validate_rule, validate_value

MAX_CATALOG_BYTES = 2_000_000
REQUIRED_FIELDS = {
    'exercise_id', 'function_name', 'title', 'description', 'difficulty', 'core_concepts',
    'tags', 'collection', 'starter_code', 'default_spec_version', 'spec_versions',
    'input_schema', 'output_schema', 'comparator', 'catalog_status', 'provenance', 'examples',
    'curriculum', 'holdout', 'boundary', 'generated', 'known_bugs', 'alternatives', 'hints',
}


def _text(value: object, maximum: int = 8192) -> None:
    if type(value) is not str or not 1 <= len(value.strip()) <= maximum:
        raise ValueError('Required bounded catalog text missing')


def _schema(schema: object) -> None:
    if type(schema) is not dict or not 1 <= len(schema) <= 8:
        raise ValueError('Input schema needs bounded named arguments')
    for name, rule in schema.items():
        if type(name) is not str or not name.isidentifier() or name.startswith('_'):
            raise ValueError('Invalid function argument name')
        validate_rule(rule)


def _source(source: object, name: str, arguments: dict) -> None:
    _text(source, 65536)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError('Fixture source has invalid syntax') from exc
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(functions) != 1:
        raise ValueError('Fixture must define its declared entrypoint')
    params = functions[0].args
    if params.posonlyargs or params.vararg or params.kwarg or params.kwonlyargs or params.defaults:
        raise ValueError('Unsupported fixture signature')
    if [p.arg for p in params.args] != list(arguments):
        raise ValueError('Fixture arguments differ from input schema')


def _cases(pool: object, schema: dict, minimum: int) -> set[str]:
    if type(pool) is not list or not minimum <= len(pool) <= 128:
        raise ValueError('Case pool is missing or outside bounds')
    keys = [json.dumps(validate_arguments(case, schema), sort_keys=True) for case in pool]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate cases within catalog pool')
    return set(keys)


def _validate_package(package: object, supported_functions: set[str] | None) -> None:
    if type(package) is not dict or set(package) != REQUIRED_FIELDS:
        raise ValueError('Incomplete or unexpected problem package metadata')
    for field in ('title', 'description', 'collection', 'exercise_id', 'function_name', 'default_spec_version'):
        _text(package[field])
    if not re.fullmatch(r'ex\d+_[a-z][a-z0-9_]*', package['exercise_id']):
        raise ValueError('Invalid exercise identifier')
    if supported_functions is not None and package['function_name'] not in supported_functions:
        raise ValueError('No trusted server oracle registered for this function')
    if package['difficulty'] not in ('beginner', 'intermediate', 'advanced'):
        raise ValueError('Unsupported difficulty')
    for field in ('core_concepts', 'tags'):
        if type(package[field]) is not list or not 1 <= len(package[field]) <= 16:
            raise ValueError('Missing bounded topic metadata')
        for item in package[field]:
            _text(item, 128)
    if package['comparator'] != 'strict_structural' or package['catalog_status'] != 'READY':
        raise ValueError('Unsupported comparator or catalog status')
    if package['provenance'] != {'source': 'original', 'status': 'ORIGINAL_AUTHORED', 'license': None}:
        raise ValueError('Only original authored statements are accepted; unverified bank licenses are unsupported')
    _schema(package['input_schema'])
    validate_rule(package['output_schema'])
    _source(package['starter_code'], package['function_name'], package['input_schema'])
    _validate_specs(package)
    _validate_examples(package)
    _validate_pools(package)
    _validate_fixtures(package)


def _validate_specs(package: dict) -> None:
    specs = package['spec_versions']
    if type(specs) is not list or not 1 <= len(specs) <= 8:
        raise ValueError('Missing supported spec versions')
    seen = set()
    for spec in specs:
        if type(spec) is not dict or set(spec) != {'spec_version', 'label', 'input_schema', 'output_schema'}:
            raise ValueError('Incomplete specification metadata')
        _text(spec['spec_version'], 64)
        _text(spec['label'], 128)
        if spec['spec_version'] in seen:
            raise ValueError('Duplicate specification identifier')
        seen.add(spec['spec_version'])
        _schema(spec['input_schema'])
        validate_rule(spec['output_schema'])
    if package['default_spec_version'] not in seen:
        raise ValueError('Default specification is missing')


def _validate_examples(package: dict) -> None:
    if type(package['examples']) is not list or not 1 <= len(package['examples']) <= 8:
        raise ValueError('Missing authored examples')
    for example in package['examples']:
        if type(example) is not dict or set(example) != {'input_args', 'output', 'explanation'}:
            raise ValueError('Incomplete authored example')
        validate_arguments(example['input_args'], package['input_schema'])
        validate_value(example['output'], package['output_schema'])
        _text(example['explanation'])


def _validate_pools(package: dict) -> None:
    curriculum = _cases(package['curriculum'], package['input_schema'], 5)
    holdout = _cases(package['holdout'], package['input_schema'], 2)
    _cases(package['boundary'], package['input_schema'], 1)
    if curriculum & holdout:
        raise ValueError('Diagnostic and transfer cases must be disjoint')
    examples = {json.dumps(e['input_args'], sort_keys=True) for e in package['examples']}
    if examples & (curriculum | holdout):
        raise ValueError('Public examples must not reuse private diagnostic or transfer cases')
    generated = package['generated']
    if type(generated) is not dict or set(generated) != {'kind', 'seed', 'max_cases'} or generated['kind'] != 'schema_bounded':
        raise ValueError('Unsupported generated strategy declaration')
    if type(generated['seed']) is not int or type(generated['max_cases']) is not int or not 1 <= generated['max_cases'] <= 100:
        raise ValueError('Invalid generation limits')
    if type(package['hints']) is not dict or set(package['hints']) != {'1', '2', '3'}:
        raise ValueError('All three graduated hints are required')
    for hint in package['hints'].values():
        _text(hint)


def _validate_fixtures(package: dict) -> None:
    for field in ('known_bugs', 'alternatives'):
        fixtures = package[field]
        if type(fixtures) is not list or not 1 <= len(fixtures) <= 16:
            raise ValueError('Missing bounded code fixtures')
        for fixture in fixtures:
            expected = {'label', 'source_code', 'witness'} if field == 'known_bugs' else {'label', 'source_code'}
            if type(fixture) is not dict or set(fixture) != expected:
                raise ValueError('Incomplete fixture metadata')
            _text(fixture['label'], 128)
            _source(fixture['source_code'], package['function_name'], package['input_schema'])
            if field == 'known_bugs':
                validate_arguments(fixture['witness'], package['input_schema'])


def validate_catalog(packages: object, supported_functions: set[str] | None = None) -> list[dict]:
    if type(packages) is not list or not 1 <= len(packages) <= 200:
        raise ValueError('Catalog must be a bounded list of problem packages')
    seen_ids, seen_functions = set(), set()
    for package in packages:
        _validate_package(package, supported_functions)
        if package['exercise_id'] in seen_ids or package['function_name'] in seen_functions:
            raise ValueError('Duplicate problem identifier or function')
        seen_ids.add(package['exercise_id'])
        seen_functions.add(package['function_name'])
    return deepcopy(packages)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key in catalog import')
        result[key] = value
    return result


def load_catalog(path: str | Path, supported_functions: set[str] | None = None) -> list[dict]:
    """Read JSON data only. Imported Python/source fields are never executed."""
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError('Catalog import exceeds byte limit')
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Catalog import must be valid bounded JSON') from exc
    return validate_catalog(data, supported_functions)
