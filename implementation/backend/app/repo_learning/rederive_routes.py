"""Exported independently: mount router without an additional /api/v1 prefix."""

from __future__ import annotations
from backend.app.db.migrations import database_target

from typing import Annotated, Literal

from backend.app.studio.security import authenticate_workspace
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import rederive

router = APIRouter(prefix="/api/v1/repos", tags=["repository-beginner-learning"])


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=512)
    symbol: str = Field(max_length=256)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    chunk_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Fact(BaseModel):
    kind: Literal["source_path", "identifier"]
    expected: str


class LearningStep(BaseModel):
    step_id: str
    phase: Literal[
        "fundamentals", "entrypoint", "components", "flows", "testing_tradeoffs"
    ]
    concept: str
    title: str
    explanation: str
    question: str
    prerequisites: list[str]
    citations: list[Citation]
    facts: list[Fact]
    mastery: Literal["not_established"]


class Attempt(BaseModel):
    sequence: int
    step_id: str
    answer: str
    created_at: str


class EvidenceEvent(BaseModel):
    sequence: int
    step_id: str
    assessment: Literal[
        "supported_observation",
        "unsupported_claim",
        "contradicted_by_source",
        "needs_support",
    ]
    feedback: str
    question: str
    citations: list[Citation]
    facts: list[Fact]
    mastery: Literal["not_established"]
    basis: str
    created_at: str


class Checkpoint(BaseModel):
    cursor: int
    completed_step_ids: list[str]


class LearningPlan(BaseModel):
    plan_id: str
    snapshot_id: str
    snapshot_hash: str
    epoch: int
    status: Literal["learning", "review", "complete"]
    current_step: LearningStep | None
    steps: list[LearningStep]
    checkpoint: Checkpoint
    revisit_step_ids: list[str]
    attempts: list[Attempt]
    evidence_events: list[EvidenceEvent]
    limitations: list[str]


class LearningAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_epoch: int = Field(strict=True, ge=1)
    answer: str = Field(strict=True, min_length=1, max_length=4000)

    @field_validator("answer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value


def _scope(
    request: Request,
    workspace: str = Header(..., alias="X-Workspace-Id"),
    token: str = Header(..., alias="X-Workspace-Token"),
) -> tuple[str, str]:
    authenticate_workspace(request, workspace, token)
    return database_target(request.app.state.settings), workspace


Scope = Annotated[tuple[str, str], Depends(_scope)]


def _call(function, *args) -> dict:
    try:
        return function(*args)
    except LookupError as exc:
        raise HTTPException(404, "learning plan or snapshot not found") from exc
    except rederive.LearningLimit as exc:
        raise HTTPException(
            429, "learning attempt storage or rate limit reached"
        ) from exc
    except rederive.EpochConflict as exc:
        raise HTTPException(
            409, "learning epoch or source conflict; reload your checkpoint"
        ) from exc
    except rederive.UnavailableSource as exc:
        raise HTTPException(422, "no grounded indexed code concepts available") from exc
    except ValueError as exc:
        raise HTTPException(422, "invalid learning answer") from exc


@router.post("/{snapshot_id}/learning-plan", response_model=LearningPlan)
def create_learning_plan(snapshot_id: str, scope: Scope) -> dict:
    return _call(rederive.create_plan, *scope, snapshot_id)


@router.get("/{snapshot_id}/learning-plan", response_model=LearningPlan)
def get_snapshot_learning_plan(snapshot_id: str, scope: Scope) -> dict:
    return _call(rederive.snapshot_plan, *scope, snapshot_id)


@router.get("/learning-plans/{plan_id}", response_model=LearningPlan)
def get_learning_plan(plan_id: str, scope: Scope) -> dict:
    return _call(rederive.get_plan, *scope, plan_id)


@router.post("/learning-plans/{plan_id}/answers", response_model=LearningPlan)
def answer_learning_plan(plan_id: str, payload: LearningAnswer, scope: Scope) -> dict:
    return _call(
        rederive.answer_plan, *scope, plan_id, payload.expected_epoch, payload.answer
    )
