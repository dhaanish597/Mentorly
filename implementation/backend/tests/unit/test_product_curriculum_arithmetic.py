"""Independent arithmetic/trace evidence for the authored objective answers.

Operands and assumptions below come from the stated problems, not answer keys,
options, rationales or the equality evaluator. Fractions avoid rounding artifacts.
The expected option is formatted only after calculating the independent result.
"""
from collections import deque
from fractions import Fraction
from heapq import heapify, heappop
from ipaddress import ip_address, ip_network
from itertools import combinations, product
from math import comb, gcd

import pytest

from backend.app.learning.catalog import curriculum


def integer(value):
    fraction = Fraction(value)
    assert fraction.denominator == 1, 'This question asks for an exact integer.'
    return str(fraction.numerator)


def percent(value):
    return integer(Fraction(value) * 100) + '%'


def round_robin_completion():
    # Both arrive at t=0, A first, quantum=2; no context-switch overhead.
    ready = deque((('A', 3), ('B', 2)))
    time = 0
    completion = {}
    while ready:
        name, remaining = ready.popleft()
        slice_time = min(2, remaining)
        time += slice_time
        if remaining > slice_time:
            ready.append((name, remaining - slice_time))
        else:
            completion[name] = time
    return completion['A']


def lru_faults():
    # Two empty frames, exact LRU, references are page identifiers.
    recency = ()
    faults = 0
    for page in ('A', 'B', 'A', 'C'):
        if page not in recency:
            faults += 1
        recency = tuple(item for item in recency if item != page) + (page,)
        recency = recency[-2:]
    return faults


def shortest_hops():
    # Unweighted undirected edges A-B,A-C,B-D,C-D.
    graph = {'A': ('B', 'C'), 'B': ('A', 'D'),
             'C': ('A', 'D'), 'D': ('B', 'C')}
    frontier = (('A', 0),)
    visited = frozenset(('A',))
    while frontier:
        node, distance = frontier[0]
        frontier = frontier[1:]
        if node == 'D':
            return distance
        unseen = tuple(neighbor for neighbor in graph[node] if neighbor not in visited)
        frontier += tuple((neighbor, distance + 1) for neighbor in unseen)
        visited = visited.union(unseen)
    raise AssertionError('The given graph should connect A to D.')


def triangle_mst():
    # Any two distinct edges of this three-vertex triangle form a spanning tree.
    edges = (('A', 'B', 1), ('B', 'C', 2), ('A', 'C', 5))
    spanning_pairs = [pair for pair in combinations(edges, 2)
                      if {endpoint for edge in pair for endpoint in edge[:2]} == {'A', 'B', 'C'}]
    return min(sum(edge[2] for edge in pair) for pair in spanning_pairs)


def first_heap_removals():
    heap = [7, 2, 5]
    heapify(heap)
    return ','.join(str(heappop(heap)) for _ in range(2))


def inorder(tree):
    if tree is None:
        return ()
    value, left, right = tree
    return inorder(left) + (value,) + inorder(right)


def longest_prefix_next_hop():
    destination = ip_address('10.2.3.4')
    routes = ((ip_network('10.0.0.0/8'), 'A'), (ip_network('10.2.0.0/16'), 'B'))
    network, hop = max((route for route in routes if destination in route[0]),
                       key=lambda route: route[0].prefixlen)
    return f'{hop} via /{network.prefixlen}'


def token_bucket_burst():
    # Full capacity=5, unit request cost, simultaneous requests: elapsed time=0.
    capacity, initial_tokens, refill_per_second, elapsed_seconds = 5, 5, 2, 0
    tokens = min(capacity, initial_tokens + refill_per_second * elapsed_seconds)
    return tokens // 1


def admissible_bitrate():
    # 20% throughput headroom; choose highest listed bitrate fitting the budget.
    throughput = Fraction(4)
    headroom = Fraction(20, 100)
    budget = throughput * (1 - headroom)
    return max(rate for rate in (1, 3, 6) if rate <= budget)


# Each result is calculated without inspecting the authored key or options.
CALCULATIONS = (
    ('dsa-arrays', lambda: integer(len(range(2, 7)))),
    ('dsa-prefix', lambda: integer(sum((3, -2, 5, 1)[1:3]))),
    ('dsa-binary-search', lambda: integer(next(i for i, value in enumerate((1, 4, 4, 9)) if value >= 4))),
    ('dsa-tree', lambda: ','.join(map(str, inorder((5, (2, None, None), (8, None, None)))))),
    ('dsa-heap', first_heap_removals),
    ('dsa-graph', lambda: integer(shortest_hops())),
    ('dsa-strings', lambda: integer(len('café'.encode('utf-8')))),
    ('dsa-backtracking', lambda: integer(sum('11' not in ''.join(bits) for bits in product('01', repeat=2)))),
    ('dsa-dijkstra', lambda: integer(min(4, sum((1, 2))))),
    ('dsa-mst', lambda: integer(triangle_mst())),
    ('dsa-segment-tree', lambda: integer(sum((2, 5, 4, 3)))),
    ('dsa-bits', lambda: integer(12 & (12 - 1))),
    ('dsa-number-theory', lambda: integer(gcd(48, 18))),
    ('cs-scheduling', lambda: integer(round_robin_completion())),
    ('cs-virtual-memory', lambda: integer(divmod(8205, 4096)[1])),
    ('cs-routing', longest_prefix_next_hop),
    ('cs-page-replacement', lambda: integer(lru_faults())),
    ('cs-sql', lambda: integer(sum(order_id is not None for order_id in (None,)))),
    ('cs-isolation', lambda: integer(10 - sum((1, 1)))),
    ('cs-dns', lambda: integer(300 - 60) + ' seconds'),
    ('cs-congestion', lambda: integer(min(20, 8)) + ' KB'),
    ('cs-cpu', lambda: integer(Fraction(1000 * 2, 10**9) * 10**6) + ' microseconds'),
    ('apt-percent', lambda: integer(100 * Fraction(120, 100) * Fraction(80, 100))),
    ('apt-ratio', lambda: integer(Fraction(840, 3 + 4) * min(3, 4))),
    ('apt-rate', lambda: integer(1 / (Fraction(1, 6) + Fraction(1, 3))) + ' hours'),
    ('apt-speed', lambda: integer(Fraction(60 + 60) / (Fraction(60, 30) + Fraction(60, 60))) + ' km/h'),
    ('apt-probability', lambda: str(Fraction(3, 5) * Fraction(2, 4))),
    ('apt-counting', lambda: integer(comb(5, 2))),
    ('apt-series', lambda: integer(17 + (7 + 2))),
    ('apt-di', lambda: percent(Fraction(8 + 18, 10 + 30))),
    ('apt-profit', lambda: percent((250 * Fraction(88, 100) - 200) / 200)),
    ('apt-interest', lambda: integer(1000 * Fraction(110, 100)**2)),
    ('apt-mixtures', lambda: percent((2 * Fraction(10, 100) + 3 * Fraction(20, 100)) / (2 + 3))),
    ('apt-divisibility', lambda: integer(527 % 9)),
    ('apt-algebra', lambda: integer(Fraction(55 - 2 * 5, 1 + 2))),
    ('apt-geometry', lambda: integer(Fraction((4 * 2) * (3 * 2), 4 * 3))),
    ('apt-logical-puzzle', lambda: integer(next(n for n in (3, 6, 8, 12) if (n % 2 == 0) + (n % 4 == 0) == 1))),
    ('apt-di-table', lambda: percent(Fraction(80, 120 + 80 + 200))),
    ('apt-di-growth', lambda: percent(Fraction(100 - 80, 80))),
    ('apt-di-pie', lambda: integer(Fraction(90, 360) * 800)),
    ('sd-capacity', lambda: integer(Fraction(8_640_000, 24 * 60 * 60)) + ' requests/s'),
    ('sd-notification', lambda: integer(Fraction(1000, 50)) + ' seconds'),
    ('sd-rate-limiter', lambda: integer(token_bucket_burst())),
    ('sd-video-streaming', lambda: integer(admissible_bitrate()) + ' Mbps'),
)


@pytest.mark.parametrize('lesson_id,calculate', CALCULATIONS,
                         ids=[case[0] for case in CALCULATIONS])
def test_authored_key_matches_independent_arithmetic_or_trace(lesson_id, calculate):
    # Arrange: obtain the authored key only as the actual value under test.
    lessons = {lesson['id']: lesson for track in curriculum()['tracks'] for lesson in track['lessons']}
    question = lessons[lesson_id]['question']

    # Act: compute expected from the independent problem model above.
    independently_calculated_option = calculate()

    # Assert: exact option spelling and mathematical/trace correctness both hold.
    assert independently_calculated_option in question['options']
    assert question['correct_answer'] == independently_calculated_option


def test_every_plain_numerical_question_has_an_independent_model():
    """A new all-numeric question cannot silently inherit equality-only tests."""
    covered = {lesson_id for lesson_id, _ in CALCULATIONS}
    numeric_ids = set()
    for track in curriculum()['tracks']:
        for lesson in track['lessons']:
            options = lesson['question']['options']
            try:
                tuple(Fraction(option.rstrip('%')) for option in options)
            except ValueError:
                continue
            numeric_ids.add(lesson['id'])
    assert numeric_ids <= covered
