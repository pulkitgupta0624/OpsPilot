"""Import simulator Parquet and JSONL artifacts into configured stores."""

from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel

from opspilot.domain.models.telemetry import GroundTruthRecord, LogRecord, MetricPoint
from opspilot.domain.ports.log_store import LogStore
from opspilot.domain.ports.metrics_store import MetricsStore
from opspilot.ingestion.stores.postgres_ground_truth import PostgresGroundTruthStore

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class IngestionCounts:
    """Inserted-row counts for one source simulation run."""

    metric_rows: int
    log_rows: int
    fault_rows: int


def import_simulation_artifacts(
    *,
    metrics_path: Path,
    logs_path: Path,
    ground_truth_path: Path,
    metrics_store: MetricsStore,
    log_store: LogStore,
    ground_truth_store: PostgresGroundTruthStore,
) -> IngestionCounts:
    """Load one generated run; store writes are idempotent for safe retries."""
    metric_frame = pd.read_parquet(metrics_path)
    metric_points = [MetricPoint.model_validate(row) for row in metric_frame.to_dict(orient="records")]
    run_id = metric_points[0].run_id if metric_points else _run_id_from_path(metrics_path)
    log_records = _read_jsonl(logs_path, LogRecord)
    fault_records = _read_jsonl(ground_truth_path, GroundTruthRecord)
    return IngestionCounts(
        metric_rows=metrics_store.write(metric_points),
        log_rows=log_store.write(log_records, run_id=run_id),
        fault_rows=ground_truth_store.write(fault_records),
    )


def _read_jsonl(path: Path, model: type[T]) -> list[T]:
    """Parse JSONL through the target Pydantic model; blank files mean no records."""
    if not path.exists():
        return []
    records: list[T] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(model.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"Invalid JSONL record in {path} at line {line_number}: {exc}") from exc
    return records


def _run_id_from_path(path: Path) -> str:
    """Recover run identity from the standard Phase 1 artifact filename."""
    prefix = "simulation_"
    suffix = "_metrics.parquet"
    if path.name.startswith(prefix) and path.name.endswith(suffix):
        return path.name[len(prefix) : -len(suffix)]
    return "unknown"

