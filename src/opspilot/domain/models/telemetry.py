"""Typed telemetry and ground-truth records used by simulation outputs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from opspilot.domain.enums import ActionType, FaultType


class MetricPoint(BaseModel):
    """A single modelled metrics sample for one service."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ts: datetime
    service: str
    request_rate_per_s: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    latency_ms_p99: float = Field(ge=0)
    cpu_pct: float = Field(ge=0, le=100)
    memory_mb: float = Field(ge=0)
    db_pool_in_use: int = Field(ge=0)
    db_pool_size: int = Field(gt=0)
    queue_depth: int = Field(ge=0)
    disk_used_pct: float = Field(ge=0, le=100)
    restarts_total: int = Field(ge=0)
    app_version: str


class LogRecord(BaseModel):
    """Structured JSON log entry in the README's required shape."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    service: str
    trace_id: str
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)


class GroundTruthRecord(BaseModel):
    """Known fault interval used to evaluate detection and recovery."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    fault_id: str
    fault_type: FaultType
    service: str
    start: datetime
    end: datetime
    intensity: float = Field(ge=0.3, le=1.5)
    correct_actions: list[ActionType]
    acceptable_actions: list[ActionType] = Field(default_factory=list)
    propagates_to: list[str] = Field(default_factory=list)

