"""Idempotent Postgres implementation of the metrics store port."""

from collections.abc import Sequence

import pandas as pd
from sqlalchemy import Engine, desc, extract, func, select
from sqlalchemy.dialects.postgresql import insert

from opspilot.domain.models.telemetry import MetricPoint, MetricSample, TimeRange
from opspilot.domain.ports.metrics_store import MetricsStore
from opspilot.ingestion.schema import metrics

METRIC_FIELDS: tuple[str, ...] = (
    "request_rate_per_s",
    "error_rate",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_ms_p99",
    "cpu_pct",
    "memory_mb",
    "db_pool_in_use",
    "db_pool_size",
    "queue_depth",
    "disk_used_pct",
    "restarts_total",
)


class PostgresMetricsStore(MetricsStore):
    """Normalize wide simulator points into idempotent metric rows."""

    def __init__(self, engine: Engine, *, points_per_batch: int = 1_000) -> None:
        if points_per_batch < 1:
            raise ValueError("points_per_batch must be positive")
        self._engine = engine
        self._points_per_batch = points_per_batch

    def write(self, points: Sequence[MetricPoint | MetricSample]) -> int:
        if not points:
            return 0
        inserted = 0
        with self._engine.begin() as connection:
            for start in range(0, len(points), self._points_per_batch):
                chunk = points[start : start + self._points_per_batch]
                rows: list[dict[str, object]] = []
                for point in chunk:
                    if isinstance(point, MetricSample):
                        rows.append(
                            {
                                "ts": point.ts,
                                "run_id": point.run_id or "live",
                                "service": point.service,
                                "name": point.name,
                                "value": point.value,
                            }
                        )
                        continue
                    rows.extend(
                        {
                            "ts": point.ts,
                            "run_id": point.run_id,
                            "service": point.service,
                            "name": field,
                            "value": float(getattr(point, field)),
                        }
                        for field in METRIC_FIELDS
                    )
                statement = insert(metrics).values(rows).on_conflict_do_nothing(
                    index_elements=["run_id", "service", "name", "ts"]
                )
                result = connection.execute(statement)
                inserted += int(result.rowcount or 0)
        return inserted

    def query(
        self,
        service: str,
        metric: str,
        time_range: TimeRange,
        *,
        step_s: int | None = None,
        run_id: str | None = None,
    ) -> pd.DataFrame:
        statement = select(
            metrics.c.ts,
            metrics.c.service,
            metrics.c.run_id,
            metrics.c.name,
            metrics.c.value,
        ).where(
            metrics.c.service == service,
            metrics.c.name == metric,
            metrics.c.ts >= time_range.start,
            metrics.c.ts <= time_range.end,
        )
        if run_id is not None:
            statement = statement.where(metrics.c.run_id == run_id)

        if step_s is not None:
            if step_s <= 0:
                raise ValueError("step_s must be positive")
            bucket = func.to_timestamp(
                func.floor(extract("epoch", metrics.c.ts) / step_s) * step_s
            ).label("ts")
            statement = (
                select(
                    bucket,
                    metrics.c.service,
                    metrics.c.run_id,
                    metrics.c.name,
                    func.avg(metrics.c.value).label("value"),
                )
                .where(
                    metrics.c.service == service,
                    metrics.c.name == metric,
                    metrics.c.ts >= time_range.start,
                    metrics.c.ts <= time_range.end,
                )
                .group_by(bucket, metrics.c.service, metrics.c.run_id, metrics.c.name)
                .order_by(bucket.asc())
            )
            if run_id is not None:
                statement = statement.where(metrics.c.run_id == run_id)
        else:
            statement = statement.order_by(metrics.c.ts.asc())

        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return pd.DataFrame.from_records(rows, columns=["ts", "service", "run_id", "name", "value"])

    def latest(
        self, service: str, metric: str, *, run_id: str | None = None
    ) -> MetricSample | None:
        statement = (
            select(metrics)
            .where(metrics.c.service == service, metrics.c.name == metric)
            .order_by(desc(metrics.c.ts))
            .limit(1)
        )
        if run_id is not None:
            statement = statement.where(metrics.c.run_id == run_id)
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return MetricSample.model_validate(dict(row)) if row is not None else None

    def query_all(
        self,
        time_range: TimeRange,
        *,
        service: str | None = None,
        run_id: str | None = None,
    ) -> pd.DataFrame:
        """Read normalized metric rows for a range, optionally filtered by run/service."""
        statement = select(
            metrics.c.ts,
            metrics.c.run_id,
            metrics.c.service,
            metrics.c.name,
            metrics.c.value,
        ).where(metrics.c.ts >= time_range.start, metrics.c.ts <= time_range.end)
        if service is not None:
            statement = statement.where(metrics.c.service == service)
        if run_id is not None:
            statement = statement.where(metrics.c.run_id == run_id)
        statement = statement.order_by(
            metrics.c.run_id.asc(), metrics.c.service.asc(), metrics.c.ts.asc()
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return pd.DataFrame.from_records(
            rows, columns=["ts", "run_id", "service", "name", "value"]
        )

