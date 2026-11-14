"""Original trusted finite-domain reference functions. Never accept imported code."""


def sum_even(nums: list[int]) -> int:
    return sum(x for x in nums if x % 2 == 0)


def count_negative(nums: list[int]) -> int:
    return sum(1 for x in nums if x < 0)


def running_totals(nums: list[int]) -> list[int]:
    return [sum(nums[:i + 1]) for i in range(len(nums))]


def stable_unique(nums: list[int]) -> list[int]:
    return [x for i, x in enumerate(nums) if x not in nums[:i]]


def rotate_right(nums: list[int], steps: int) -> list[int]:
    if not nums:
        return []
    offset = steps % len(nums)
    return nums[-offset:] + nums[:-offset] if offset else list(nums)


def first_peak(nums: list[int]) -> int:
    for i in range(1, len(nums) - 1):
        if nums[i] > nums[i - 1] and nums[i] > nums[i + 1]:
            return i
    return -1


def second_largest_distinct(nums: list[int]) -> int:
    distinct = sorted(set(nums))
    return distinct[-2] if len(distinct) > 1 else 0


def pair_sum_exists(nums: list[int], target: int) -> bool:
    return any(nums[i] + nums[j] == target for i in range(len(nums)) for j in range(i + 1, len(nums)))


def merge_sorted(left: list[int], right: list[int]) -> list[int]:
    return sorted(left + right)


def longest_increasing_run(nums: list[int]) -> int:
    best = 0
    for start in range(len(nums)):
        end = start + 1
        while end < len(nums) and nums[end] > nums[end - 1]:
            end += 1
        best = max(best, end - start)
    return best


def balance_point(nums: list[int]) -> int:
    for i in range(len(nums)):
        if sum(nums[:i]) == sum(nums[i + 1:]):
            return i
    return -1


def reverse_words(text: str) -> str:
    return ' '.join(reversed(text.split()))


def normalize_spaces(text: str) -> str:
    return ' '.join(text.split())


def is_palindrome(text: str) -> bool:
    return text == text[::-1]


def count_vowels(text: str) -> int:
    return sum(1 for char in text if char.lower() in 'aeiou')


def first_unique_char(text: str) -> str:
    for char in text:
        if text.count(char) == 1:
            return char
    return ''


def run_lengths(text: str) -> list[int]:
    lengths = []
    start = 0
    while start < len(text):
        end = start + 1
        while end < len(text) and text[end] == text[start]:
            end += 1
        lengths = lengths + [end - start]
        start = end
    return lengths


def common_prefix(words: list[str]) -> str:
    if not words:
        return ''
    prefix = words[0]
    while prefix and not all(word.startswith(prefix) for word in words):
        prefix = prefix[:-1]
    return prefix


def digit_sum(number: int) -> int:
    return sum(int(char) for char in str(abs(number)))


def greatest_common_divisor(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def factorial(number: int) -> int:
    product = 1
    for value in range(2, number + 1):
        product *= value
    return product


def is_prime(number: int) -> bool:
    return number >= 2 and all(number % divisor for divisor in range(2, number))


def count_bits(number: int) -> int:
    return bin(number).count('1')


def fizz_labels(limit: int) -> list[str]:
    return ['FizzBuzz' if n % 15 == 0 else 'Fizz' if n % 3 == 0 else 'Buzz' if n % 5 == 0 else str(n) for n in range(1, limit + 1)]


def toggle(flag: bool, steps: int) -> bool:
    return not flag if steps % 2 else flag


def all_true(flags: list[bool]) -> bool:
    return all(flags)


def invert_flags(flags: list[bool]) -> list[bool]:
    return [not flag for flag in flags]


def balanced_brackets(text: str) -> bool:
    stack = ()
    matches = {')': '(', ']': '[', '}': '{'}
    for char in text:
        if char in '([{':
            stack = (*stack, char)
        elif char in matches:
            if not stack or stack[-1] != matches[char]:
                return False
            stack = stack[:-1]
    return not stack
