"""Bounded polling ingestion pipeline with retry-safe writes and back-pressure."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.exc import SQLAlchemyError

from opspilot.domain.models.telemetry import LogRecord, MetricSample
from opspilot.domain.ports.log_store import LogStore
from opspilot.domain.ports.metrics_store import MetricsStore
from opspilot.ingestion.collectors.log_collector import LogCollector
from opspilot.ingestion.collectors.metrics_scraper import MetricsScraper

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionBatch:
    """One collection interval of normalized metrics and structured logs."""

    run_id: str
    metrics: tuple[MetricSample, ...]
    logs: tuple[LogRecord, ...]


class IngestionPipeline:
    """Collect service data, buffer failed writes, and drop the oldest batch at capacity."""

    def __init__(
        self,
        scraper: MetricsScraper,
        log_collector: LogCollector,
        metrics_store: MetricsStore,
        log_store: LogStore,
        *,
        batch_capacity: int = 20,
        on_persist: Callable[[tuple[MetricSample, ...], tuple[LogRecord, ...]], None]
        | None = None,
    ) -> None:
        if batch_capacity < 1:
            raise ValueError("batch_capacity must be positive")
        self._scraper = scraper
        self._log_collector = log_collector
        self._metrics_store = metrics_store
        self._log_store = log_store
        self._pending: deque[IngestionBatch] = deque()
        self._batch_capacity = batch_capacity
        self._on_persist = on_persist

    @property
    def pending_batches(self) -> int:
        return len(self._pending)

    def run_once(self) -> bool:
        """Collect one batch and attempt to flush the oldest queued data."""
        metrics: list[MetricSample] = []
        logs: list[LogRecord] = []
        try:
            metrics = self._scraper.scrape_all()
        except httpx.HTTPError as exc:
            logger.warning("metrics scrape failed after retries", extra={"error": str(exc)})
        try:
            logs = self._log_collector.collect_all()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("structured log collection failed after retries", extra={"error": str(exc)})

        if metrics or logs:
            self._enqueue(IngestionBatch("live", tuple(metrics), tuple(logs)))
        return self.flush_pending()

    def flush_pending(self) -> bool:
        """Write queued batches in order; idempotent keys make partial retries safe."""
        while self._pending:
            batch = self._pending[0]
            try:
                self._metrics_store.write(batch.metrics)
                self._log_store.write(batch.logs, run_id=batch.run_id)
                if self._on_persist is not None:
                    self._on_persist(batch.metrics, batch.logs)
            except SQLAlchemyError as exc:
                logger.warning(
                    "database write failed; keeping batch for retry",
                    extra={"error": str(exc), "pending_batches": len(self._pending)},
                )
                return False
            self._pending.popleft()
        return True

    def run_forever(
        self,
        *,
        interval_seconds: float = 5.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Poll until a supplied stop event is set, maintaining the target cadence."""
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        stopper = stop_event or threading.Event()
        while not stopper.is_set():
            started = time.monotonic()
            self.run_once()
            remaining = max(0.0, interval_seconds - (time.monotonic() - started))
            stopper.wait(remaining)

    def close(self) -> None:
        self._scraper.close()
        self._log_collector.close()

    def _enqueue(self, batch: IngestionBatch) -> None:
        if len(self._pending) >= self._batch_capacity:
            dropped = self._pending.popleft()
            logger.warning(
                "ingestion queue full; dropped oldest batch",
                extra={
                    "dropped_run_id": dropped.run_id,
                    "dropped_metric_count": len(dropped.metrics),
                    "dropped_log_count": len(dropped.logs),
                },
            )
        self._pending.append(batch)

