"""HTTP contract for persisted practice and its separate optional interpretation."""

from typing import Any, Literal

from backend.app.assessments.schemas import ExplanationReview
from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LearningQuestion(Contract):
    id: str
    prompt: str
    options: list[str] | None = None
    option_ids: list[str] | None = None
    response_kind: Literal["multiple_choice", "numeric", "boolean", "enumeration"]


class CoachMessage(Contract):
    id: str
    role: str
    kind: str
    text: str


class LearningFeedback(Contract):
    correct: bool
    message: str
    answer_key_revealed: bool
    explanation_review: ExplanationReview | None = None


class LearningReport(Contract):
    lesson_completed: bool
    mastery_awarded: Literal[False]
    summary: str
    explanation_rubric: dict[str, Any]
    explanation_review: ExplanationReview | None = None


class LearningSessionView(Contract):
    id: str
    lesson_id: str
    epoch: int
    mode: Literal["practice"]
    state: Literal["active", "completed", "exhausted"]
    language_mode: str
    catalog_version: str
    content_hash: str
    question: LearningQuestion
    coach_messages: list[CoachMessage]
    answer_count: int
    hint_count: int
    deadline: None
    feedback: LearningFeedback | None
    report: LearningReport | None
    hint: str | None = None
