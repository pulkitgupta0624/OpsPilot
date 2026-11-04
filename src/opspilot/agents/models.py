"""Validated agent inputs, evidence, decisions, and outcome records."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opspilot.domain.enums import ActionType, FaultType
from opspilot.domain.models.knowledge import Citation


class Evidence(BaseModel):
    """Compact, attributable evidence collected through read-only tools."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: Literal["alert", "metrics", "logs", "deployments", "topology", "runbook"]
    summary: str = Field(min_length=1, max_length=4_000)
    data_ref: str | None = None
    collected_at: datetime
    citations: list[Citation] = Field(default_factory=list)
    untrusted: bool = False


class Hypothesis(BaseModel):
    """Root-cause candidate grounded in known evidence IDs."""

    model_config = ConfigDict(extra="forbid")

    root_cause_service: str = Field(min_length=1)
    fault_type: FaultType | Literal["unknown"]
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(min_length=1)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=2_000)


class CriticVerdict(BaseModel):
    """Evidence review result that controls investigation routing."""

    model_config = ConfigDict(extra="forbid")

    accept: bool
    top_hypothesis: Hypothesis | None = None
    confidence: float = Field(ge=0, le=1)
    missing_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class VerificationSpec(BaseModel):
    """One measurable recovery condition for the live simulator."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    service: str
    comparator: Literal["lt", "gt"]
    threshold: float
    window_s: int = Field(default=15, ge=1, le=300)


class RemediationPlan(BaseModel):
    """Whitelisted simulator action plus evidence and recovery expectations."""

    model_config = ConfigDict(extra="forbid")

    action: ActionType
    target_service: str = Field(min_length=1)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    expected_outcome: str = Field(min_length=1, max_length=1_000)
    verification: list[VerificationSpec] = Field(min_length=1)
    rollback: ActionType | None = None
    citations: list[Citation] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)


class PolicyDecision(BaseModel):
    """Deterministic safety gate result; never supplied by a language model."""

    model_config = ConfigDict(extra="forbid")

    risk: Literal["low", "medium", "high"]
    approval_required: bool
    violations: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    """Human decision attached to a paused remediation plan."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str = Field(default="", max_length=2_000)
    decided_at: datetime

    @field_validator("reviewer")
    @classmethod
    def validate_reviewer(cls, value: str) -> str:
        reviewer = value.strip()
        if not reviewer:
            raise ValueError("reviewer must contain a name")
        return reviewer

    @field_validator("decided_at")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decided_at must include a timezone")
        return value


class ActionResult(BaseModel):
    """Result returned by the dry-run or simulator-only executor."""

    model_config = ConfigDict(extra="forbid")

    action: ActionType
    service: str
    accepted: bool
    dry_run: bool
    message: str
    completed_at: datetime


class VerificationResult(BaseModel):
    """Bounded metric checks performed after a simulator action."""

    model_config = ConfigDict(extra="forbid")

    recovered: bool
    observations: list[dict[str, str | float | bool]] = Field(default_factory=list)
    checked_at: datetime
    message: str


class PostMortem(BaseModel):
    """Structured incident report saved as an unverified KB document."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2_000)
    root_cause: str = Field(min_length=1, max_length=2_000)
    impact: str = Field(min_length=1, max_length=2_000)
    resolution: str = Field(min_length=1, max_length=2_000)
    lessons: list[str] = Field(min_length=1, max_length=10)
    citations: list[Citation] = Field(default_factory=list)
