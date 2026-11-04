"""Environment-backed settings for the FastAPI adapter."""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class APISettings(BaseModel):
    """HTTP security, config paths, and bounded streaming defaults."""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None
    chaos_enabled: bool = False
    ingestion_config: Path = Path("configs/ingestion.yaml")
    detection_config: Path = Path("configs/detection.yaml")
    rag_config: Path = Path("configs/rag.yaml")
    agent_config: Path = Path("configs/agents.yaml")
    policy_config: Path = Path("configs/remediation_policy.yaml")
    rag_index_dir: Path | None = None
    eval_report_dir: Path = Path("evals/reports")
    stream_poll_seconds: float = Field(default=2.0, gt=0, le=30)
    stream_max_seconds: int = Field(default=300, ge=10, le=3_600)

    @classmethod
    def from_environment(cls) -> "APISettings":
        """Build settings from the documented OPSPILOT_* environment variables."""
        raw: dict[str, Any] = {
            "api_key": os.getenv("OPSPILOT_API_KEY"),
            "chaos_enabled": _environment_bool("OPSPILOT_ENABLE_CHAOS_API", False),
            "ingestion_config": os.getenv(
                "OPSPILOT_INGESTION_CONFIG", "configs/ingestion.yaml"
            ),
            "detection_config": os.getenv(
                "OPSPILOT_DETECTION_CONFIG", "configs/detection.yaml"
            ),
            "rag_config": os.getenv("OPSPILOT_RAG_CONFIG", "configs/rag.yaml"),
            "agent_config": os.getenv("OPSPILOT_AGENT_CONFIG", "configs/agents.yaml"),
            "policy_config": os.getenv(
                "OPSPILOT_POLICY_CONFIG", "configs/remediation_policy.yaml"
            ),
            "eval_report_dir": os.getenv("OPSPILOT_EVAL_REPORT_DIR", "evals/reports"),
            "stream_poll_seconds": os.getenv("OPSPILOT_STREAM_POLL_SECONDS", "2"),
            "stream_max_seconds": os.getenv("OPSPILOT_STREAM_MAX_SECONDS", "300"),
        }
        rag_index_dir = os.getenv("OPSPILOT_RAG_INDEX_DIR")
        if rag_index_dir:
            raw["rag_index_dir"] = rag_index_dir
        return cls.model_validate(raw)


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of true/false, 1/0, yes/no, or on/off")
