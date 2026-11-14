"""Trusted linear oracle, independent of the learner's binary-search strategy."""

def first_at_least(nums: list[int], target: int) -> int:
    for index, value in enumerate(nums):
        if value >= target:
            return index
    return -1


ref_first_at_least = first_at_least
