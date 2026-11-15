"""Canonical additive contracts for semantic interpretation, never runtime proof."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewStatus = Literal[
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "CONTRADICTED_BY_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
    "NOT_EVALUATED",
    "MODEL_UNAVAILABLE",
]
ModelStatus = Literal[
    "MODEL_DISABLED",
    "MODEL_NOT_CONFIGURED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_INVALID_RESPONSE",
    "MODEL_UNAVAILABLE",
    "MODEL_ASSISTED",
    "MODEL_BUDGET_EXHAUSTED",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(Strict):
    source: Literal["question", "answer", "lesson_rationale"]
    start: int = Field(ge=0, strict=True)
    end: int = Field(ge=1, strict=True)
    excerpt: str = Field(min_length=1, max_length=1000)


class SemanticCriterion(Strict):
    id: Literal["relevance", "reasoning_coherence", "assumptions", "example_alignment"]
    status: Literal[
        "SUPPORTED",
        "PARTIALLY_SUPPORTED",
        "CONTRADICTED_BY_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
    ]
    explanation: str = Field(min_length=1, max_length=600)
    evidence_refs: list[EvidenceRef] = Field(max_length=4)


class ModelInterpretation(Strict):
    """Only quality signals; provider cannot set revision, provenance or credit."""

    status: Literal[
        "SUPPORTED",
        "PARTIALLY_SUPPORTED",
        "CONTRADICTED_BY_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
    ]
    criteria: list[SemanticCriterion] = Field(min_length=1, max_length=4)
    uncertainty: str = Field(min_length=1, max_length=600)
    explanation: str = Field(min_length=1, max_length=1000)
    followup: str = Field(min_length=1, max_length=500)


class ModelProvenance(Strict):
    provider: str | None
    model: str | None
    request_id: str | None
    status: ModelStatus


class SemanticReview(Strict):
    schema_version: Literal["1.0"] = "1.0"
    status: ReviewStatus
    criteria: list[SemanticCriterion] = Field(default_factory=list, max_length=4)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=16)
    uncertainty: str
    explanation: str
    followup: str
    reviewed_answer_revision: int = Field(ge=1, strict=True)
    answer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_version: Literal["semantic-quality-v1"] = "semantic-quality-v1"
    model_provenance: ModelProvenance
    correctness_assessed: Literal[False] = False


class ExplanationReview(Strict):
    status: Literal[
        "SUPPORTED", "NEEDS_CLARIFICATION", "INCORRECT_WITH_EVIDENCE", "UNASSESSED"
    ]
    review: SemanticReview
    changes_objective_credit: Literal[False] = False
