"""Metrics persistence interface used by ingestion and detection."""

from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from opspilot.domain.models.telemetry import MetricPoint, MetricSample, TimeRange


class MetricsStore(Protocol):
    """Read/write port for normalized time-series metrics."""

    def write(self, points: Sequence[MetricPoint | MetricSample]) -> int: ...

    def query(
        self,
        service: str,
        metric: str,
        time_range: TimeRange,
        *,
        step_s: int | None = None,
        run_id: str | None = None,
    ) -> pd.DataFrame: ...

    def query_all(
        self,
        time_range: TimeRange,
        *,
        service: str | None = None,
        run_id: str | None = None,
    ) -> pd.DataFrame: ...

    def latest(
        self, service: str, metric: str, *, run_id: str | None = None
    ) -> MetricSample | None: ...
