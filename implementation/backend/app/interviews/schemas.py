"""Interview-specific schemas; no caller-selected owner or execution verdict."""

from typing import Literal

from backend.app.assessments.schemas import SemanticReview
from backend.app.models.enums import LanguageMode
from pydantic import BaseModel, ConfigDict, Field, field_validator

InterviewType = Literal["dsa", "cs", "system_design", "codebase_defense"]
Difficulty = Literal["beginner", "intermediate", "advanced"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewSession(Strict):
    type: InterviewType
    difficulty: Difficulty
    topics: list[str] = Field(default_factory=list, max_length=8)
    duration_minutes: int = Field(ge=5, le=60, strict=True)
    language_mode: LanguageMode

    @field_validator("topics")
    @classmethod
    def valid_topics(cls, value: list[str]) -> list[str]:
        if any(not 1 <= len(t) <= 80 for t in value) or len(set(value)) != len(value):
            raise ValueError("Topics must be unique bounded catalog identifiers")
        return value


class Finish(Strict):
    expected_epoch: int = Field(ge=0, le=1000, strict=True)


class Answer(Finish):
    answer: str = Field(min_length=1, max_length=12000)
    code: str | None = Field(default=None, max_length=24000)
    allow_external: bool = False

    @field_validator("answer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer cannot be blank")
        return value  # Preserve exact offsets for report excerpts.


class SourceRef(Strict):
    source: str
    exercise_id: str | None = None
    spec_version: str | None = None
    policy_id: str | None = None


class Message(Strict):
    text: str
    source_refs: list[SourceRef]


class Question(Message):
    id: str
    kind: Literal["primary", "followup"]
    parent_id: str | None


class Excerpt(Strict):
    start: int
    end: int
    text: str


class Indicator(Strict):
    id: str
    label: str
    value: int = Field(ge=0, le=1)
    maximum: Literal[1]
    status: str
    semantic_validity: Literal["unassessed"]
    excerpts: list[Excerpt]


class AnswerReport(Strict):
    question_id: str
    question: str
    answer: str
    code: str | None
    indicators: list[Indicator]
    semantic_review: SemanticReview | None = None


class Assessment(Strict):
    status: str
    reason: str


class Recommendation(Strict):
    exercise_id: str
    spec_version: str
    lesson_id: str | None = None
    reason: str
    missing_indicators: list[str]


class PracticeTopic(Strict):
    type: InterviewType
    topic: str
    reason: str
    missing_indicators: list[str]


class Report(Strict):
    session_id: str
    completion_reason: Literal["finished", "timeout", "questions_exhausted"]
    completed_at: str
    answered_count: int
    semantic_validity: Assessment
    technical_correctness: Assessment
    psychology: Assessment
    answers: list[AnswerReport]
    recommendations: list[Recommendation]
    practice_topics: list[PracticeTopic] = Field(default_factory=list)
    limitations: list[str]


class SessionView(Strict):
    id: str
    type: InterviewType
    difficulty: Difficulty
    topics: list[str]
    duration_minutes: int
    language_mode: LanguageMode
    epoch: int
    state: Literal["active", "completed"]
    started_at: str
    deadline_at: str
    introduction: Message
    acknowledgement: Message | None
    question: Question | None
    report: Report | None


class Duration(Strict):
    minimum: int
    maximum: int
    default: int


class Config(Strict):
    types: list[InterviewType]
    difficulties: list[Difficulty]
    duration_minutes: Duration
    language_modes: list[LanguageMode]
    camera_default: bool
    camera_policy: str
    assessment_policy: str
    language_policy: str


class Exercise(Strict):
    exercise_id: str
    title: str
    description: str
    difficulty: str
    spec_version: str
    topics: list[str]
    constraints_summary: list[str]


class Catalog(Strict):
    topics: dict[str, list[str]]
    dsa_exercises: list[Exercise]
