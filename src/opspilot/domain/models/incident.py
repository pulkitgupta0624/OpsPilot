"""Persistable detector alerts and correlated incident aggregates."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from opspilot.domain.models.alert import SuspectFeature


class Alert(BaseModel):
    """One metric or log anomaly that contributed to an incident."""

    model_config = ConfigDict(extra="forbid")

    id: str
    incident_id: str | None = None
    detector: str
    source: Literal["metrics", "logs"] = "metrics"
    service: str
    score: float
    threshold: float
    started_at: datetime
    detected_at: datetime
    suspect_features: list[SuspectFeature] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    """Open incident created by merging related alert events."""

    model_config = ConfigDict(extra="forbid")

    id: str
    status: Literal["open", "resolved", "escalated"] = "open"
    severity: str = "unknown"
    affected_services: list[str]
    detected_at: datetime
    last_alert_at: datetime
    summary: str
