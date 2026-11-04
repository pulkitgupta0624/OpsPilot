"""Typed YAML configuration and budgets for Phase 5 agent runs."""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opspilot.core.errors import ConfigurationError


class AgentSettings(BaseModel):
    """Runtime policy, persistence, provider, and hard-stop limits."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["fake", "openai", "anthropic", "google", "ollama"] = "fake"
    model: str = "deterministic-fake"
    base_url: str | None = None
    request_timeout_seconds: float = Field(default=30, gt=0, le=180)
    max_tool_calls: int = Field(default=10, ge=1, le=100)
    max_investigation_rounds: int = Field(default=3, ge=1, le=10)
    max_remediation_attempts: int = Field(default=2, ge=1, le=5)
    max_tokens_per_incident: int = Field(default=60_000, ge=100, le=1_000_000)
    max_cost_usd_per_incident: float = Field(default=0.50, ge=0, le=100)
    max_wall_clock_seconds: int = Field(default=300, ge=10, le=3_600)
    approval_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    critic_accept_confidence: float = Field(default=0.6, ge=0, le=1)
    verify_window_seconds: int = Field(default=30, ge=1, le=300)
    poll_interval_seconds: float = Field(default=3, gt=0, le=30)
    dry_run: bool = False
    state_db: Path = Path("data/agents/checkpoints.sqlite")
    audit_log: Path = Path("data/agents/audit.jsonl")
    record_file: Path | None = None
    replay_file: Path | None = None
    input_cost_per_1k_tokens: float = Field(default=0, ge=0)
    output_cost_per_1k_tokens: float = Field(default=0, ge=0)


class RemediationDefaults(BaseModel):
    """Cross-action rules used by the deterministic policy gate."""

    model_config = ConfigDict(extra="forbid")

    auto_execute_max_risk: Literal["low", "medium", "high"] = "low"
    require_approval_for_services: list[str] = Field(default_factory=lambda: ["payments"])
    max_actions_per_incident: int = Field(default=2, ge=1, le=10)
    cooldown_seconds_per_service_action: int = Field(default=300, ge=0, le=86_400)


class RemediationPolicy(BaseModel):
    """Explicit supported-action declarations; missing entries fail closed."""

    model_config = ConfigDict(extra="forbid")

    defaults: RemediationDefaults = Field(default_factory=RemediationDefaults)
    actions: dict[str, Literal["low", "medium", "high"]]


def load_agent_settings(path: Path) -> AgentSettings:
    """Read validated agent settings, allowing provider/model environment overrides."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("Agent configuration must be a YAML mapping")
        if os.environ.get("OPSPILOT_LLM_PROVIDER"):
            raw["provider"] = os.environ["OPSPILOT_LLM_PROVIDER"]
        if os.environ.get("OPSPILOT_LLM_MODEL"):
            raw["model"] = os.environ["OPSPILOT_LLM_MODEL"]
        return AgentSettings.model_validate(raw)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Agent configuration file not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid agent configuration at {path}: {exc}") from exc


def load_remediation_policy(path: Path) -> RemediationPolicy:
    """Read and validate deterministic action risk policy."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return RemediationPolicy.model_validate(raw)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Remediation policy file not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid remediation policy at {path}: {exc}") from exc
