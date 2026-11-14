"""Serialization must not compare an untrusted metaclass to built-in types."""
from exec_worker.runner.safe_serializer import serialize_value, safe_repr


def test_untrusted_metaclass_equality_and_hash_are_never_called():
    calls = []
    class HostileMeta(type):
        def __eq__(cls, other):
            calls.append('eq')
            raise AssertionError('Untrusted metaclass equality invoked')
        def __hash__(cls):
            calls.append('hash')
            raise AssertionError('Untrusted metaclass hash invoked')
    class Hostile(metaclass=HostileMeta):
        pass
    instance = Hostile()
    result = serialize_value(instance)
    assert result.value == {'__vcc_untrusted_type__': 'untrusted_object'}
    assert safe_repr(instance) == '<untrusted_object object>'
    assert calls == []


def test_invalid_return_classification_never_reads_metaclass_name():
    from exec_worker.runner.protocol import classify_learner_return_value
    class NameHook(type):
        @property
        def __name__(cls):
            raise AssertionError('Metaclass name hook invoked')
    class Fixture(metaclass=NameHook):
        pass
    result = classify_learner_return_value(Fixture())
    assert result[0] == 'INVALID_RESULT'
    assert result[1] is None
    assert 'untrusted_object' in result[3]
