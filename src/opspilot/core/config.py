"""Typed configuration loading for the simulator."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from opspilot.core.errors import ConfigurationError
from opspilot.domain.enums import DecoyType, FaultType


class ServiceConfig(BaseModel):
    """Modelled baseline for one simulated service."""

    model_config = ConfigDict(extra="forbid")

    role: str
    critical: bool
    base_request_rate_per_s: float = Field(gt=0)
    base_memory_mb: float = Field(gt=0)
    memory_limit_mb: float = Field(gt=0)
    db_pool_size: int = Field(gt=0)
    disk_baseline_pct: float = Field(ge=0, le=100)
    version: str


class FaultScheduleConfig(BaseModel):
    """A deterministic fault interval relative to the simulation start."""

    model_config = ConfigDict(extra="forbid")

    fault_type: FaultType
    service: str
    start_offset_seconds: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)
    intensity: float = Field(ge=0.3, le=1.5)


class DecoyScheduleConfig(BaseModel):
    """A benign or transient event used to exercise false-positive handling."""

    model_config = ConfigDict(extra="forbid")

    decoy_type: DecoyType
    service: str
    start_offset_seconds: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)
    intensity: float = Field(default=1.0, ge=0.3, le=3.0)


class SimulationConfig(BaseModel):
    """Validated settings needed by the simulator engine."""

    model_config = ConfigDict(extra="forbid")

    step_seconds: int = Field(default=5, ge=1, le=300)
    start_at: datetime
    services: dict[str, ServiceConfig]
    faults: list[FaultScheduleConfig] = Field(default_factory=list)
    decoys: list[DecoyScheduleConfig] = Field(default_factory=list)

    @field_validator("start_at")
    @classmethod
    def normalize_start_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("start_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("services")
    @classmethod
    def require_expected_services(
        cls, value: dict[str, ServiceConfig]
    ) -> dict[str, ServiceConfig]:
        expected = {"orders", "payments", "inventory"}
        if set(value) != expected:
            raise ValueError(f"services must contain exactly {sorted(expected)}")
        return value

def load_simulation_config(path: Path) -> SimulationConfig:
    """Load and validate YAML simulator configuration from ``path``."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("simulation"), dict):
            raise ConfigurationError("Configuration must contain a 'simulation' mapping")
        simulation = SimulationConfig.model_validate(
            {
                **raw["simulation"],
                "faults": raw.get("faults", []),
                "decoys": raw.get("decoys", []),
            }
        )
        unknown_services = sorted(
            {
                event.service
                for event in [*simulation.faults, *simulation.decoys]
            }
            - set(simulation.services)
        )
        if unknown_services:
            raise ConfigurationError(
                f"Fault schedules reference unknown services: {', '.join(unknown_services)}"
            )
        return simulation
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid simulator configuration at {path}: {exc}") from exc

