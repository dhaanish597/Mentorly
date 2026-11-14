"""Bounded JSON value rules shared by trusted catalog validation and API models."""
from copy import deepcopy

MAX_INTEGER = 2**53 - 1
MAX_STRING = 256
MAX_LIST = 128
KINDS = {'integer', 'boolean', 'string', 'list'}


def _immutable(*args: object, **kwargs: object) -> None:
    raise TypeError('Typed output lists are immutable')


class FrozenValueList(list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = sort = reverse = _immutable
    __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo: dict) -> 'FrozenValueList':
        return FrozenValueList(self)


def validate_value(value: object, rule: dict | None = None) -> object:
    """Reject coercion, subclasses, nesting and values outside explicit limits."""
    if type(value) is FrozenValueList:
        value = list(value)
    kind = {int: 'integer', bool: 'boolean', str: 'string', list: 'list'}.get(type(value))
    if kind is None or (rule is not None and kind != rule['kind']):
        raise ValueError('Expected a strict bounded integer, boolean, string or scalar list')
    limits = rule or {}
    if kind == 'integer':
        if not limits.get('minimum', -MAX_INTEGER) <= value <= limits.get('maximum', MAX_INTEGER):
            raise ValueError('Integer outside bounded value schema')
    elif kind in ('string', 'list'):
        cap = MAX_STRING if kind == 'string' else MAX_LIST
        if not limits.get('min_length', 0) <= len(value) <= limits.get('max_length', cap):
            raise ValueError('Value length outside bounded schema')
        if kind == 'list':
            for item in value:
                if type(item) is list:
                    raise ValueError('Nested lists are not supported')
                validate_value(item, limits.get('items'))
            if limits.get('sorted_required') and any(a > b for a, b in zip(value, value[1:])):
                raise ValueError('List must be sorted in nondecreasing order')
    return deepcopy(value)


def validate_rule(rule: object, *, scalar: bool = False) -> dict:
    if type(rule) is not dict or rule.get('kind') not in KINDS:
        raise ValueError('Unsupported or missing value schema kind')
    kind = rule['kind']
    keys = {'kind'}
    if kind == 'integer':
        keys |= {'minimum', 'maximum'}
        lo, hi = rule.get('minimum'), rule.get('maximum')
        if type(lo) is not int or type(hi) is not int or not -MAX_INTEGER <= lo <= hi <= MAX_INTEGER:
            raise ValueError('Integer schema needs explicit safe bounds')
    elif kind in ('string', 'list'):
        keys |= {'min_length', 'max_length'}
        lo, hi = rule.get('min_length'), rule.get('max_length')
        cap = MAX_STRING if kind == 'string' else MAX_LIST
        if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= cap:
            raise ValueError('Length schema needs explicit bounded lengths')
        if kind == 'list':
            if scalar:
                raise ValueError('Nested list schemas are unsupported')
            keys |= {'items', 'sorted_required'}
            items = validate_rule(rule.get('items'), scalar=True)
            if 'sorted_required' in rule and type(rule['sorted_required']) is not bool:
                raise ValueError('Sorted requirement must be boolean')
            if rule.get('sorted_required') and items['kind'] != 'integer':
                raise ValueError('Sorted requirement only supports integer lists')
    if set(rule) - keys:
        raise ValueError('Unexpected value schema metadata')
    return deepcopy(rule)


def validate_arguments(arguments: object, schema: dict) -> dict:
    if type(arguments) is not dict or set(arguments) != set(schema):
        raise ValueError('Input must contain exactly the function arguments')
    return {name: validate_value(arguments[name], rule) for name, rule in schema.items()}


def strict_equal(left: object, right: object) -> bool:
    try:
        left = validate_value(left)
        right = validate_value(right)
    except ValueError:
        return False
    if type(left) is not type(right):
        return False
    if type(left) is list:
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    return left == right
