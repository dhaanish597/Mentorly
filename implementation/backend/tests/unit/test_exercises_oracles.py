"""Independent finite checks; never execute learner source."""
import importlib
import itertools
import json
from pathlib import Path
import unittest
from bisect import bisect_left
from collections import deque

from backend.app.exercises.ex1_shortest_subarray import shortest_subarray_ge_target
from backend.app.exercises.ex3_max_product import max_product_subarray


def load_api(test):
    try:
        return importlib.import_module('backend.app.exercises.registry')
    except ModuleNotFoundError:
        test.fail('Trusted exercise registry is not implemented')


def deque_shortest(nums, target):
    prefix = [0]
    for x in nums:
        prefix.append(prefix[-1] + x)
    candidates = deque()
    best = len(nums) + 1
    for i, value in enumerate(prefix):
        while candidates and value - prefix[candidates[0]] >= target:
            best = min(best, i - candidates.popleft())
        while candidates and prefix[candidates[-1]] >= value:
            candidates.pop()
        candidates.append(i)
    return 0 if best > len(nums) else best


def dp_product(nums):
    hi = lo = answer = nums[0]
    for x in nums[1:]:
        hi, lo = max(x, hi*x, lo*x), min(x, hi*x, lo*x)
        answer = max(answer, hi)
    return answer


class ExerciseTests(unittest.TestCase):
    def test_hand_checked_examples(self):
        api = load_api(self)
        examples = [
            ('ex1_shortest_subarray', 'v1_positive_only', {'nums': [2,3,1,2,4,3], 'target': 7}, 2),
            ('ex1_shortest_subarray', 'v2_negatives_allowed', {'nums': [1,-1,5], 'target': 5}, 1),
            ('ex1_shortest_subarray', 'v2_negatives_allowed', {'nums': [-5,-2,7], 'target': 6}, 1),
            ('ex2_binary_search', 'v1_sorted_with_duplicates', {'nums': [], 'target': 5}, -1),
            ('ex2_binary_search', 'v1_sorted_with_duplicates', {'nums': [2,2,2], 'target': 2}, 0),
            ('ex3_max_product', 'v1_bounded_ints', {'nums': [-3,-3,-3]}, 9),
            ('ex3_max_product', 'v1_bounded_ints', {'nums': [-2,0,-1]}, 0),
            ('ex3_max_product', 'v1_bounded_ints', {'nums': [-5]}, -5),
        ]
        for exercise, spec, args, expected in examples:
            with self.subTest(args=args):
                self.assertEqual(api.evaluate(exercise, spec, args), expected)

    def test_exhaustive_tiny_domains_against_alternatives(self):
        api = load_api(self)
        for size in range(1, 5):
            for values in itertools.product(range(-2, 3), repeat=size):
                nums = list(values)
                for target in range(1, 6):
                    self.assertEqual(api.evaluate('ex1_shortest_subarray', 'v2_negatives_allowed', {'nums': nums, 'target': target}), deque_shortest(nums, target))
                self.assertEqual(api.evaluate('ex3_max_product', 'v1_bounded_ints', {'nums': nums}), dp_product(nums))
            for values in itertools.product(range(1,4), repeat=size):
                for target in range(1, 8):
                    nums = list(values)
                    self.assertEqual(api.evaluate('ex1_shortest_subarray','v1_positive_only', {'nums':nums,'target':target}), deque_shortest(nums,target))
        for size in range(5):
            for values in itertools.combinations_with_replacement(range(-2,3),size):
                for target in range(-3,4):
                    nums = list(values)
                    index = bisect_left(nums, target)
                    self.assertEqual(api.evaluate('ex2_binary_search','v1_sorted_with_duplicates',{'nums':nums,'target':target}), index if index < size else -1)

    def test_validation_rejects_illegal_domain(self):
        api = load_api(self)
        invalid = [
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[],'target':1}),
            ('ex1_shortest_subarray','v2_negatives_allowed',{'nums':[],'target':1}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[0],'target':1}),
            ('ex1_shortest_subarray','v2_negatives_allowed',{'nums':[-21],'target':1}),
            ('ex1_shortest_subarray','v2_negatives_allowed',{'nums':[51],'target':1}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[1]*16,'target':1}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[1],'target':0}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[1],'target':201}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[True],'target':1}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[1],'target':True}),
            ('ex1_shortest_subarray','v1_positive_only',{'nums':[1.0],'target':1}),
            ('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[2,1],'target':1}),
            ('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[51],'target':1}),
            ('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[-51],'target':1}),
            ('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[],'target':61}),
            ('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[1]*16,'target':1}),
            ('ex3_max_product','v1_bounded_ints',{'nums':[]}),
            ('ex3_max_product','v1_bounded_ints',{'nums':[11]}),
            ('ex3_max_product','v1_bounded_ints',{'nums':[-11]}),
            ('ex3_max_product','v1_bounded_ints',{'nums':[1]*13}),
            ('ex3_max_product','v1_bounded_ints',{'nums':[1],'target':1}),
            ('ex3_max_product','v1_bounded_ints',{'nums':(1,)}),
            ('ex3_max_product','v1_bounded_ints',{}),
            ('ex3_max_product','v1_bounded_ints',[]),
            ('ex3_max_product','v1_positive_only',{'nums':[1]}),
            ('unknown','v1_positive_only',{'nums':[1]}),
        ]
        for exercise, spec, args in invalid:
            with self.subTest(exercise=exercise, spec=spec, args=args):
                with self.assertRaises(ValueError):
                    api.evaluate(exercise,spec,args)

    def test_upper_bounds_and_nonmutation(self):
        api = load_api(self)
        self.assertEqual(api.evaluate('ex3_max_product','v1_bounded_ints',{'nums':[10]*12}),10**12)
        self.assertEqual(api.evaluate('ex1_shortest_subarray','v1_positive_only',{'nums':[50]*15,'target':200}),4)
        self.assertEqual(api.evaluate('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[-50,50],'target':-60}),0)
        self.assertEqual(api.evaluate('ex2_binary_search','v1_sorted_with_duplicates',{'nums':[-50,50],'target':60}),-1)
        args={'nums':[2,-1,5],'target':5}
        self.assertEqual(api.evaluate('ex1_shortest_subarray','v2_negatives_allowed',args),1)
        self.assertEqual(args,{'nums':[2,-1,5],'target':5})

    def test_comparison_rejects_bool_float_and_noninteger(self):
        api = load_api(self)
        self.assertTrue(api.compare_output(1,1))
        for value in [True,1.0,'1',None,[],{},2]:
            self.assertFalse(api.compare_output(value,1))
        self.assertFalse(api.compare_output(1,True))

    def test_manifest_is_valid_disjoint_and_not_mutable_through_caller(self):
        api = load_api(self)
        self.assertEqual(len(api.list_specs()),32)
        for spec in api.list_specs()[:4]:
            curriculum=api.cases(spec.exercise_id,spec.spec_version,'curriculum')
            holdout=api.cases(spec.exercise_id,spec.spec_version,'holdout')
            self.assertGreaterEqual(len(curriculum),5)
            self.assertGreaterEqual(len(holdout),2)
            left={api.case_key(spec.exercise_id,spec.spec_version,x) for x in curriculum}
            right={api.case_key(spec.exercise_id,spec.spec_version,x) for x in holdout}
            self.assertFalse(left & right)
            self.assertEqual(len(left),len(curriculum))
            self.assertEqual(len(right),len(holdout))
            for args in curriculum+holdout:
                api.evaluate(spec.exercise_id,spec.spec_version,args)
            original=api.cases(spec.exercise_id,spec.spec_version,'holdout')
            holdout[0]['nums'].append(999)
            self.assertEqual(api.cases(spec.exercise_id,spec.spec_version,'holdout'),original)
        with self.assertRaises(ValueError):
            api.cases('ex3_max_product','v1_bounded_ints','invalid')
        self.assertEqual(api.case_key('ex1_shortest_subarray','v2_negatives_allowed',{'nums':[1,-1,5],'target':5}),api.case_key('ex1_shortest_subarray','v2_negatives_allowed',{'target':5,'nums':[1,-1,5]}))

    def test_phase0_canonical_ids_and_spec_metadata(self):
        api = load_api(self)
        specs = api.list_specs()
        expected = {
            ('ex1_shortest_subarray', 'v1_positive_only'): ('shortest_subarray_ge_target', 1, 15, 1, 50, (1, 200), False),
            ('ex1_shortest_subarray', 'v2_negatives_allowed'): ('shortest_subarray_ge_target', 1, 15, -20, 50, (1, 200), False),
            ('ex2_binary_search', 'v1_sorted_with_duplicates'): ('first_at_least', 0, 15, -50, 50, (-60, 60), True),
            ('ex3_max_product', 'v1_bounded_ints'): ('max_product_subarray', 1, 12, -10, 10, None, False),
        }
        self.assertTrue(set(expected).issubset({(s.exercise_id, s.spec_version) for s in specs}))
        for (ex_id, spec_ver), meta in expected.items():
            spec = api.get_spec(ex_id, spec_ver)
            self.assertEqual(
                (spec.function_name, spec.min_length, spec.max_length, spec.min_value, spec.max_value, spec.target_bounds, spec.sorted_required),
                meta,
            )

        manifest_path = Path(api.__file__).with_name('case_manifest.json')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(manifest.get('schema_version'), 1)
        self.assertEqual(len(manifest.get('specifications', [])), 4)

        self.assertEqual(shortest_subarray_ge_target([], 5), 0)
        with self.assertRaises(ValueError):
            max_product_subarray([])


if __name__ == '__main__':
    unittest.main()
