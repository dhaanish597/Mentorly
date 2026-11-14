"""Trusted direct-enumeration maximum-product oracle."""

def max_product_subarray(nums: list[int]) -> int:
    if not nums:
        raise ValueError('max_product_subarray requires a nonempty array')
    best = nums[0]
    for start in range(len(nums)):
        product = 1
        for end in range(start, len(nums)):
            product *= nums[end]
            best = max(best, product)
    return best


ref_max_product_subarray = max_product_subarray
