"""Typed settings for service scraping and back-pressure behavior."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opspilot.core.errors import ConfigurationError


class IngestionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str
    scrape_interval_seconds: int = Field(default=5, ge=1, le=3_600)
    request_timeout_seconds: float = Field(default=3.0, gt=0, le=120)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    batch_capacity: int = Field(default=20, ge=1, le=10_000)
    services: dict[str, str]


def load_ingestion_settings(path: Path) -> IngestionSettings:
    """Read HTTP collector settings, with the database URL overridable by environment."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "OPSPILOT_DATABASE_URL" in os.environ:
            raw["database_url"] = os.environ["OPSPILOT_DATABASE_URL"]
        return IngestionSettings.model_validate(raw)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Ingestion config not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid ingestion config at {path}: {exc}") from exc

