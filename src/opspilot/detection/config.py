"""Typed loading for window and detector settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from opspilot.core.errors import ConfigurationError


class IsolationForestSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_estimators: int = Field(default=200, ge=10, le=2_000)
    contamination: str | float = "auto"
    random_state: int = 42


class LSTMAutoencoderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_length: int = Field(default=6, ge=2, le=120)
    hidden_size: int = Field(default=32, ge=4, le=512)
    latent_size: int = Field(default=8, ge=2, le=256)
    epochs: int = Field(default=20, ge=1, le=500)
    batch_size: int = Field(default=256, ge=8, le=4_096)
    learning_rate: float = Field(default=0.001, gt=0, le=1)
    patience: int = Field(default=4, ge=1, le=100)
    seed: int = 42


class LogDetectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_clusters: int = Field(default=2_000, ge=10, le=100_000)
    frequency_window_seconds: int = Field(default=60, ge=1, le=3_600)
    frequency_multiplier: float = Field(default=5.0, gt=1, le=100)
    frequency_minimum_count: int = Field(default=5, ge=2, le=100_000)


class CorrelationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merge_window_seconds: int = Field(default=120, ge=1, le=86_400)
    cooldown_seconds: int = Field(default=300, ge=1, le=86_400)
    service_neighbors: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "orders": ["payments", "inventory"],
            "payments": ["orders"],
            "inventory": ["orders"],
        }
    )


class DetectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_seconds: int = Field(default=60, ge=10, le=3_600)
    stride_seconds: int = Field(default=10, ge=1, le=3_600)
    baseline_seconds: int = Field(default=1_800, ge=60, le=86_400)
    threshold_quantile: float = Field(default=0.995, gt=0.5, lt=1.0)
    consecutive_windows: int = Field(default=3, ge=1, le=100)
    online_consecutive_windows: int = Field(default=1, ge=1, le=100)
    fault_grace_seconds: int = Field(default=30, ge=0, le=3_600)
    isolation_forest: IsolationForestSettings = Field(
        default_factory=IsolationForestSettings
    )
    lstm_autoencoder: LSTMAutoencoderSettings = Field(
        default_factory=LSTMAutoencoderSettings
    )
    logs: LogDetectionSettings = Field(default_factory=LogDetectionSettings)
    correlation: CorrelationSettings = Field(default_factory=CorrelationSettings)

    @model_validator(mode="after")
    def validate_window_stride(self) -> "DetectionSettings":
        if self.stride_seconds > self.window_seconds:
            raise ValueError("stride_seconds cannot exceed window_seconds")
        return self


def load_detection_settings(path: Path) -> DetectionSettings:
    """Read and validate detector tuning values from YAML."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return DetectionSettings.model_validate(raw)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Detection config not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid detection config at {path}: {exc}") from exc

