"""Trusted bounded oracle. Input validation is enforced by registry.evaluate."""

def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
    """Direct scan; empty defensive result is 0, but not a legal registry input."""
    best = len(nums) + 1
    for start in range(len(nums)):
        running = 0
        for end in range(start, len(nums)):
            running += nums[end]
            if running >= target:
                best = min(best, end - start + 1)
                break
    return 0 if best > len(nums) else best


ref_shortest_subarray_ge_target = shortest_subarray_ge_target
