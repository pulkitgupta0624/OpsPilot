"""Bounded post-action checks against the simulator's live Prometheus endpoint."""

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from opspilot.agents.config import AgentSettings
from opspilot.agents.models import RemediationPlan, VerificationResult
from opspilot.ingestion.config import IngestionSettings


class SimulatorVerifier:
    """Require repeated healthy samples within a bounded verification window."""

    def __init__(self, ingestion: IngestionSettings, settings: AgentSettings) -> None:
        self._ingestion = ingestion
        self._settings = settings

    def verify(self, plan: RemediationPlan) -> VerificationResult:
        """Read each configured signal until all pass or the verification deadline expires."""
        service = plan.target_service
        base_url = self._ingestion.services.get(service)
        if base_url is None:
            return VerificationResult(
                recovered=False,
                checked_at=datetime.now(UTC),
                message="Verification target is not a configured simulator service.",
            )

        deadline = time.monotonic() + min(
            self._settings.verify_window_seconds,
            max(spec.window_s for spec in plan.verification),
        )
        observations: list[dict[str, str | float | bool]] = []
        consecutive_healthy = 0
        required_healthy_samples = 3
        while time.monotonic() <= deadline:
            try:
                with httpx.Client(timeout=self._settings.request_timeout_seconds) as client:
                    response = client.get(base_url.rstrip("/") + "/metrics")
                    response.raise_for_status()
                metrics = _parse_prometheus(response.text)
                sample_checks = [
                    _check_spec(metrics, spec.model_dump()) for spec in plan.verification
                ]
                observations.extend(sample_checks)
                if sample_checks and all(bool(item["passed"]) for item in sample_checks):
                    consecutive_healthy += 1
                    if consecutive_healthy >= required_healthy_samples:
                        return VerificationResult(
                            recovered=True,
                            observations=observations,
                            checked_at=datetime.now(UTC),
                            message="All recovery signals passed three consecutive live samples.",
                        )
                else:
                    consecutive_healthy = 0
            except (httpx.HTTPError, ValueError):
                consecutive_healthy = 0
                observations.append({"metric": "endpoint", "passed": False, "value": "unavailable"})

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(self._settings.poll_interval_seconds, remaining))

        return VerificationResult(
            recovered=False,
            observations=observations,
            checked_at=datetime.now(UTC),
            message="Recovery conditions did not pass three consecutive samples before timeout.",
        )


def _parse_prometheus(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        if not line.startswith("opspilot_") or " " not in line:
            continue
        name, raw = line.split(None, 1)
        try:
            metric_name = name.removeprefix("opspilot_").split("{", 1)[0]
            values[metric_name] = float(raw.strip())
        except ValueError:
            continue
    pool_size = values.get("db_pool_size", 0.0)
    values["db_pool_utilization"] = (
        values.get("db_pool_in_use", 0.0) / pool_size if pool_size > 0 else 1.0
    )
    return values


def _check_spec(
    metrics: dict[str, float], spec: dict[str, Any]
) -> dict[str, str | float | bool]:
    metric = str(spec["metric"])
    value = metrics.get(metric)
    threshold = float(spec["threshold"])
    comparator = str(spec["comparator"])
    passed = value is not None and (value < threshold if comparator == "lt" else value > threshold)
    return {
        "metric": metric,
        "value": float(value) if value is not None else "missing",
        "comparator": comparator,
        "threshold": threshold,
        "passed": passed,
    }
