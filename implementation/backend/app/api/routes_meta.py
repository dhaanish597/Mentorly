"""Public-safe metadata routes (health, branding, exercises, demo presets)."""

from dataclasses import dataclass

from fastapi import APIRouter

from backend.app.core.branding import get_branding
from backend.app.core.config import get_request_settings as get_settings
from backend.app.models.api_schemas import (
    BrandingResponse,
    DemoPresetMetadata,
    ExerciseMetadata,
    ExerciseSpecMetadata,
    HealthResponse,
)

router = APIRouter(prefix="/meta", tags=["meta"])


@dataclass(frozen=True)
class _SpecBounds:
    exercise_id: str
    spec_version: str
    function_name: str
    min_length: int
    max_length: int
    min_value: int
    max_value: int
    target_bounds: tuple[int, int] | None = None
    sorted_required: bool = False


def _load_spec_bounds() -> tuple[_SpecBounds, ...]:
    """Read canonical domain bounds from exercises.registry without exposing oracles."""
    from backend.app.exercises.registry import list_specs

    return tuple(
        _SpecBounds(
            exercise_id=spec.exercise_id,
            spec_version=spec.spec_version,
            function_name=spec.function_name,
            min_length=spec.min_length,
            max_length=spec.max_length,
            min_value=spec.min_value,
            max_value=spec.max_value,
            target_bounds=spec.target_bounds,
            sorted_required=spec.sorted_required,
        )
        for spec in list_specs()
    )


_SPEC_LABELS: dict[tuple[str, str], str] = {
    ("ex1_shortest_subarray", "v1_positive_only"): "Positive Integers Only (v1)",
    ("ex1_shortest_subarray", "v2_negatives_allowed"): "Negatives Allowed (v2)",
    ("ex2_binary_search", "v1_sorted_with_duplicates"): "Sorted Array with Duplicates (v1)",
    ("ex3_max_product", "v1_bounded_ints"): "Bounded Integers (v1)",
}


def _format_constraints_summary(spec: _SpecBounds) -> list[str]:
    summary = [
        f"{spec.min_length} <= len(nums) <= {spec.max_length}",
        f"{spec.min_value} <= nums[i] <= {spec.max_value} (strict int)",
    ]
    if spec.sorted_required:
        summary.append("nums must be sorted in non-decreasing order")
    if spec.target_bounds is not None:
        summary.append(
            f"{spec.target_bounds[0]} <= target <= {spec.target_bounds[1]} (strict int)"
        )
    return summary


_EXERCISE_CATALOG: tuple[dict[str, object], ...] = (
    {
        "exercise_id": "ex1_shortest_subarray",
        "title": "Shortest Qualifying Subarray",
        "function_name": "shortest_subarray_ge_target",
        "difficulty": "intermediate",
        "core_concepts": ["Sliding Window", "Negative Domain Shift", "Prefix Sums"],
        "description": (
            "Given an integer array nums and an integer target, return the length of the "
            "shortest contiguous non-empty subarray whose sum is >= target, or 0 if none exists."
        ),
        "starter_code": (
            "def shortest_subarray_ge_target(nums: list[int], target: int) -> int:\n"
            "    left = 0\n"
            "    curr_sum = 0\n"
            "    best = len(nums) + 1\n"
            "    for right, val in enumerate(nums):\n"
            "        curr_sum += val\n"
            "        while curr_sum >= target:\n"
            "            best = min(best, right - left + 1)\n"
            "            curr_sum -= nums[left]\n"
            "            left += 1\n"
            "    return 0 if best > len(nums) else best\n"
        ),
        "default_spec_version": "v1_positive_only",
    },
    {
        "exercise_id": "ex2_binary_search",
        "title": "Binary Search Lower Bound",
        "function_name": "first_at_least",
        "difficulty": "beginner",
        "core_concepts": ["Binary Search", "Loop Invariants", "Duplicate Boundaries"],
        "description": (
            "Given a non-decreasing sorted integer array nums and an integer target, return the "
            "smallest index i such that nums[i] >= target, or -1 if no such index exists."
        ),
        "starter_code": (
            "def first_at_least(nums: list[int], target: int) -> int:\n"
            "    left, right = 0, len(nums) - 1\n"
            "    ans = -1\n"
            "    while left <= right:\n"
            "        mid = (left + right) // 2\n"
            "        if nums[mid] >= target:\n"
            "            ans = mid\n"
            "            right = mid - 1\n"
            "        else:\n"
            "            left = mid + 1\n"
            "    return ans\n"
        ),
        "default_spec_version": "v1_sorted_with_duplicates",
    },
    {
        "exercise_id": "ex3_max_product",
        "title": "Maximum Product Subarray",
        "function_name": "max_product_subarray",
        "difficulty": "intermediate",
        "core_concepts": ["Dynamic Programming", "Sign-Flip State", "Zero Reset"],
        "description": (
            "Given a non-empty integer array nums, find the contiguous non-empty subarray "
            "with the largest product and return that product."
        ),
        "starter_code": (
            "def max_product_subarray(nums: list[int]) -> int:\n"
            "    hi = lo = ans = nums[0]\n"
            "    for x in nums[1:]:\n"
            "        hi, lo = max(x, hi * x, lo * x), min(x, hi * x, lo * x)\n"
            "        ans = max(ans, hi)\n"
            "    return ans\n"
        ),
        "default_spec_version": "v1_bounded_ints",
    },
)

_DEMO_PRESETS: tuple[DemoPresetMetadata, ...] = (
    DemoPresetMetadata(
        preset_id="preset_ex1_negative_shift",
        title="Shortest Subarray: Negative Domain Shift (Tanglish)",
        exercise_id="ex1_shortest_subarray",
        spec_version="v2_negatives_allowed",
        language_mode="ta-IN,en-IN",
        provenance_label="RECORDED_DEMO",
        description=(
            "Demonstrates how a positive-only two-pointer sliding window breaks when negative "
            "numbers are introduced under v2_negatives_allowed."
        ),
        starter_code=str(_EXERCISE_CATALOG[0]["starter_code"]),
    ),
    DemoPresetMetadata(
        preset_id="preset_ex2_duplicate_bound",
        title="Binary Search: Duplicate Lower-Bound Check (English)",
        exercise_id="ex2_binary_search",
        spec_version="v1_sorted_with_duplicates",
        language_mode="en-IN",
        provenance_label="RECORDED_DEMO",
        description=(
            "Demonstrates binary search boundary reasoning on sorted arrays containing "
            "duplicate values and empty inputs."
        ),
        starter_code=str(_EXERCISE_CATALOG[1]["starter_code"]),
    ),
    DemoPresetMetadata(
        preset_id="preset_ex3_sign_flip",
        title="Max Product Subarray: Sign-Flip State Update (English)",
        exercise_id="ex3_max_product",
        spec_version="v1_bounded_ints",
        language_mode="en-IN",
        provenance_label="RECORDED_DEMO",
        description=(
            "Demonstrates tracking both running maximum and running minimum across negative "
            "multipliers without overwriting prior state."
        ),
        starter_code=str(_EXERCISE_CATALOG[2]["starter_code"]),
    ),
)


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Public liveness and fail-closed readiness without runtime identity details."""
    from backend.app.core.execution_readiness import probe_execution_readiness
    settings = get_settings()
    branding = get_branding(settings.branding_config_path)
    readiness = await probe_execution_readiness(settings)
    return HealthResponse(
        status="ok",
        service="vcc-coordinator",
        phase="P0-P9",
        version=settings.api_version,
        custom_code_execution_enabled=readiness == "READY",
        execution_status=readiness,
        product_name=branding.productName,
        product_name_status=branding.productNameStatus,
    )


@router.get("/branding", response_model=BrandingResponse)
def get_branding_metadata() -> BrandingResponse:
    """Return user-facing branding from config/branding.json."""
    branding = get_branding()
    return BrandingResponse(
        productName=branding.productName,
        productNameStatus=branding.productNameStatus,
        shortName=branding.shortName,
        tagline=branding.tagline,
    )


@router.get("/exercises", response_model=list[ExerciseMetadata])
def get_exercises_metadata() -> list[ExerciseMetadata]:
    """Publish validated learner metadata, never private verification packages."""
    from backend.app.exercises.registry import public_catalog

    return [ExerciseMetadata.model_validate(item) for item in public_catalog()]


@router.get("/demo-presets", response_model=list[DemoPresetMetadata])
def get_demo_presets() -> list[DemoPresetMetadata]:
    """Return public-safe demo presets with explicit provenance labels."""
    return list(_DEMO_PRESETS)
