"""Preserved original three exercise statements and starters (compatibility data)."""

LEGACY_METADATA = ({'exercise_id': 'ex1_shortest_subarray',
  'title': 'Shortest Qualifying Subarray',
  'function_name': 'shortest_subarray_ge_target',
  'difficulty': 'intermediate',
  'core_concepts': ['Sliding Window', 'Negative Domain Shift', 'Prefix Sums'],
  'description': 'Given an integer array nums and an integer target, return the length of the '
                 'shortest contiguous non-empty subarray whose sum is >= target, or 0 if none '
                 'exists.',
  'starter_code': 'def shortest_subarray_ge_target(nums: list[int], target: int) -> int:\n'
                  '    left = 0\n'
                  '    curr_sum = 0\n'
                  '    best = len(nums) + 1\n'
                  '    for right, val in enumerate(nums):\n'
                  '        curr_sum += val\n'
                  '        while curr_sum >= target:\n'
                  '            best = min(best, right - left + 1)\n'
                  '            curr_sum -= nums[left]\n'
                  '            left += 1\n'
                  '    return 0 if best > len(nums) else best\n',
  'default_spec_version': 'v1_positive_only'},
 {'exercise_id': 'ex2_binary_search',
  'title': 'Binary Search Lower Bound',
  'function_name': 'first_at_least',
  'difficulty': 'beginner',
  'core_concepts': ['Binary Search', 'Loop Invariants', 'Duplicate Boundaries'],
  'description': 'Given a non-decreasing sorted integer array nums and an integer target, return '
                 'the smallest index i such that nums[i] >= target, or -1 if no such index exists.',
  'starter_code': 'def first_at_least(nums: list[int], target: int) -> int:\n'
                  '    left, right = 0, len(nums) - 1\n'
                  '    ans = -1\n'
                  '    while left <= right:\n'
                  '        mid = (left + right) // 2\n'
                  '        if nums[mid] >= target:\n'
                  '            ans = mid\n'
                  '            right = mid - 1\n'
                  '        else:\n'
                  '            left = mid + 1\n'
                  '    return ans\n',
  'default_spec_version': 'v1_sorted_with_duplicates'},
 {'exercise_id': 'ex3_max_product',
  'title': 'Maximum Product Subarray',
  'function_name': 'max_product_subarray',
  'difficulty': 'intermediate',
  'core_concepts': ['Dynamic Programming', 'Sign-Flip State', 'Zero Reset'],
  'description': 'Given a non-empty integer array nums, find the contiguous non-empty subarray '
                 'with the largest product and return that product.',
  'starter_code': 'def max_product_subarray(nums: list[int]) -> int:\n'
                  '    hi = lo = ans = nums[0]\n'
                  '    for x in nums[1:]:\n'
                  '        hi, lo = max(x, hi * x, lo * x), min(x, hi * x, lo * x)\n'
                  '        ans = max(ans, hi)\n'
                  '    return ans\n',
  'default_spec_version': 'v1_bounded_ints'})
