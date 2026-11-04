"""Validated request and response contracts for the HTTP API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from opspilot.domain.enums import FaultType


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str = Field(default="", max_length=2_000)


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    service: str | None = Field(default=None, max_length=80)
    fault_type: FaultType | None = None
    k: int = Field(default=5, ge=1, le=20)


class FaultInjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=80)
    fault_type: FaultType
    duration_seconds: int = Field(default=300, ge=30, le=3_600)
    intensity: float = Field(default=1.0, ge=0.3, le=1.5)


class IncidentSummary(BaseModel):
    id: str
    status: str
    severity: str
    affected_services: list[str]
    detected_at: datetime
    last_alert_at: datetime
    summary: str


class IncidentListResponse(BaseModel):
    items: list[IncidentSummary]
    total: int
    limit: int
    offset: int


class IncidentDetailResponse(BaseModel):
    incident: IncidentSummary
    alerts: list[dict[str, Any]]
    agent: dict[str, Any] | None = None


class MetricSeriesPoint(BaseModel):
    ts: datetime
    values: dict[str, float]


class MetricSeriesResponse(BaseModel):
    service: str
    items: list[MetricSeriesPoint]


class DetectionStatusResponse(BaseModel):
    database: Literal["ok"]
    detector: str | None
    last_score: float | None
    last_threshold: float | None
    last_alert_at: datetime | None
    last_metric_at: datetime | None
    open_incidents: int
