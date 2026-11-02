"""Curate normalized metrics into a wide Parquet training dataset."""

from pathlib import Path

import pandas as pd

from opspilot.domain.models.telemetry import TimeRange
from opspilot.ingestion.stores.postgres_metrics import METRIC_FIELDS, PostgresMetricsStore


def export_metrics_parquet(
    store: PostgresMetricsStore,
    *,
    time_range: TimeRange,
    output_path: Path,
    service: str | None = None,
    run_id: str | None = None,
) -> int:
    """Pivot normalized store rows into the simulator's wide metric schema."""
    normalized = store.query_all(time_range, service=service, run_id=run_id)
    if normalized.empty:
        raise ValueError("No metric rows matched the requested time range")
    wide = normalized.pivot_table(
        index=["run_id", "ts", "service"],
        columns="name",
        values="value",
        aggfunc="last",
    ).reset_index()
    wide.columns.name = None
    for metric in METRIC_FIELDS:
        if metric not in wide:
            wide[metric] = pd.NA
    wide["app_version"] = "unknown"
    ordered = ["run_id", "ts", "service", *METRIC_FIELDS, "app_version"]
    wide = wide[ordered].sort_values(["run_id", "service", "ts"], kind="stable")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(output_path, index=False, compression="zstd")
    return len(wide)

