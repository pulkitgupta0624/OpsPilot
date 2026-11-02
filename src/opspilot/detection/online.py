"""Streaming metric/log detector wired to incident persistence."""

import logging
from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import datetime, timedelta
from hashlib import sha256

import numpy as np
import pandas as pd

from opspilot.core.clock import SystemClock
from opspilot.detection.config import DetectionSettings
from opspilot.detection.correlation import AlertCorrelator
from opspilot.detection.features.windowing import (
    METRIC_COLUMNS,
    WindowConfig,
    build_feature_windows,
)
from opspilot.detection.logs.drain3_detector import Drain3LogDetector
from opspilot.detection.models.base import BaseDetector
from opspilot.domain.models.incident import Alert, Incident
from opspilot.domain.models.telemetry import LogRecord, MetricSample
from opspilot.domain.ports.incident_store import IncidentStore

logger = logging.getLogger(__name__)


class OnlineDetectionService:
    """Score newly persisted samples, apply consecutive-window policy, and write incidents."""

    def __init__(
        self,
        *,
        detector: BaseDetector,
        settings: DetectionSettings,
        log_detector: Drain3LogDetector,
        incident_store: IncidentStore,
        history_capacity_per_service: int = 10_000,
    ) -> None:
        if detector.threshold_ is None:
            raise ValueError(f"Detector '{detector.name}' must have a calibrated threshold")
        if history_capacity_per_service < 2:
            raise ValueError("history_capacity_per_service must be at least two")
        self._detector = detector
        self._settings = settings
        self._log_detector = log_detector
        self._incident_store = incident_store
        self._correlator = AlertCorrelator(settings.correlation)
        self._history: dict[str, deque[dict[str, object]]] = defaultdict(
            lambda: deque(maxlen=history_capacity_per_service)
        )
        self._seen_metric_keys: set[tuple[str, str, str]] = set()
        self._last_feature_at: dict[str, datetime] = {}
        self._streaks: dict[str, tuple[int, datetime | None, bool]] = {}
        self._pending_incidents: deque[tuple[Incident, Alert]] = deque()

    def prime_baseline(self, normal_metrics: pd.DataFrame) -> None:
        """Warm rolling features from one normal-only run, shifted to just before now."""
        required = {"ts", "service", *METRIC_COLUMNS}
        missing = sorted(required - set(normal_metrics.columns))
        if missing:
            raise ValueError(
                f"Normal baseline is missing required metric columns: {', '.join(missing)}"
            )
        if normal_metrics.empty:
            raise ValueError("Cannot warm the online detector with an empty normal baseline")

        data = normal_metrics.copy()
        data["ts"] = pd.to_datetime(data["ts"], utc=True)
        warmup_seconds = (
            self._settings.baseline_seconds
            + self._settings.window_seconds
            + self._settings.stride_seconds
        )
        end_at = SystemClock().now() - timedelta(seconds=self._settings.stride_seconds)
        for service, group in data.groupby("service", sort=True):
            group = group.sort_values("ts", kind="stable")
            cadence = group["ts"].diff().dt.total_seconds().dropna().median()
            sample_seconds = float(cadence) if pd.notna(cadence) and cadence > 0 else 5.0
            required_samples = int(np.ceil(warmup_seconds / sample_seconds)) + 1
            tail = group.tail(required_samples).copy()
            if len(tail) < 2:
                raise ValueError(f"Normal baseline for {service} has too few metric samples")
            offset = end_at - pd.Timestamp(tail["ts"].iloc[-1]).to_pydatetime()
            tail["ts"] = tail["ts"] + offset
            tail["run_id"] = "live"
            rows = tail[["run_id", "service", "ts", *METRIC_COLUMNS]].to_dict(
                orient="records"
            )
            for row in rows:
                row["service"] = str(service)
                timestamp = pd.Timestamp(row["ts"]).to_pydatetime()
                self._history[str(service)].append(row)
                self._seen_metric_keys.add(("live", str(service), timestamp.isoformat()))

        warm_features = build_feature_windows(
            pd.DataFrame.from_records(
                [row for service_rows in self._history.values() for row in service_rows]
            ),
            WindowConfig(
                window_seconds=self._settings.window_seconds,
                stride_seconds=self._settings.stride_seconds,
                baseline_seconds=self._settings.baseline_seconds,
            ),
        )
        for service, group in warm_features.groupby("service", sort=False):
            self._last_feature_at[str(service)] = pd.Timestamp(group["ts"].max()).to_pydatetime()

    def process_batch(
        self,
        metrics: Sequence[MetricSample],
        logs: Sequence[LogRecord],
    ) -> None:
        """Process one already-persisted metrics/log batch from the ingestion pipeline."""
        self._flush_pending_incidents()
        if metrics:
            self._append_metric_samples(metrics)
            self._score_latest_features()
        for event in self._log_detector.observe(list(logs)):
            alert = Alert(
                id=_stable_alert_id(
                    "logs", event.service, event.timestamp, event.fingerprint
                ),
                detector="drain3",
                source="logs",
                service=event.service,
                score=1.0,
                threshold=1.0,
                started_at=event.timestamp,
                detected_at=event.timestamp,
                details={
                    "reason": event.reason,
                    "template_id": event.cluster_id,
                    "template": event.template,
                    "fingerprint": event.fingerprint,
                },
            )
            self._queue_incident(alert)
        self._flush_pending_incidents()

    def _append_metric_samples(self, samples: Sequence[MetricSample]) -> None:
        grouped: dict[tuple[str, str, datetime], dict[str, object]] = {}
        for sample in samples:
            run_id = sample.run_id or "live"
            key = (run_id, sample.service, sample.ts)
            row = grouped.setdefault(
                key,
                {"run_id": run_id, "service": sample.service, "ts": sample.ts},
            )
            if sample.name in METRIC_COLUMNS:
                row[sample.name] = sample.value

        for (run_id, service, timestamp), row in grouped.items():
            key = (run_id, service, timestamp.isoformat())
            if key in self._seen_metric_keys:
                continue
            missing = set(METRIC_COLUMNS) - set(row)
            if missing:
                logger.warning(
                    "incomplete metrics sample; skipping detector row",
                    extra={"service": service, "missing_metrics": sorted(missing)},
                )
                continue
            self._seen_metric_keys.add(key)
            self._history[service].append(row)

        if len(self._seen_metric_keys) > 100_000:
            # The history itself is bounded; reset duplicate tracking after long runs.
            self._seen_metric_keys.clear()

    def _score_latest_features(self) -> None:
        rows = [row for service_rows in self._history.values() for row in service_rows]
        if not rows:
            return
        metrics = pd.DataFrame.from_records(rows)
        features = build_feature_windows(
            metrics,
            WindowConfig(
                window_seconds=self._settings.window_seconds,
                stride_seconds=self._settings.stride_seconds,
                baseline_seconds=self._settings.baseline_seconds,
            ),
        )
        if features.empty:
            return
        features = features.sort_values(["service", "ts"], kind="stable").reset_index(drop=True)
        scores = self._detector.score(features)
        threshold = self._detector.threshold_
        if threshold is None:
            raise RuntimeError(f"Detector '{self._detector.name}' lost its threshold")

        for position, row in features.iterrows():
            service = str(row["service"])
            timestamp = pd.Timestamp(row["ts"]).to_pydatetime()
            last_processed = self._last_feature_at.get(service)
            if last_processed is not None and timestamp <= last_processed:
                continue
            self._last_feature_at[service] = timestamp
            score = float(scores[position])
            if not np.isfinite(score):
                continue
            streak, started_at, active = self._streaks.get(service, (0, None, False))
            if (
                started_at is not None
                and timestamp - started_at
                > timedelta(seconds=self._settings.stride_seconds * (streak + 1.5))
            ):
                streak, started_at, active = 0, None, False
            if score < threshold:
                self._streaks[service] = (0, None, False)
                continue
            if active:
                continue
            if streak == 0:
                started_at = timestamp
            streak += 1
            required_streak = self._settings.online_consecutive_windows
            if streak >= required_streak:
                explanations = self._detector.explain(features)
                alert = Alert(
                    id=_stable_alert_id(
                        "metrics", service, timestamp, f"{self._detector.name}:{started_at}"
                    ),
                    detector=self._detector.name,
                    service=service,
                    score=score,
                    threshold=threshold,
                    started_at=started_at or timestamp,
                    detected_at=timestamp,
                    suspect_features=explanations[position],
                    details={"consecutive_windows": required_streak},
                )
                self._queue_incident(alert)
                self._streaks[service] = (streak, started_at, True)
                logger.warning(
                    "metric anomaly confirmed",
                    extra={
                        "service": service,
                        "detector": self._detector.name,
                        "score": score,
                        "threshold": threshold,
                        "detected_at": timestamp.isoformat(),
                    },
                )
            else:
                self._streaks[service] = (streak, started_at, False)

    def _queue_incident(self, alert: Alert) -> None:
        correlated = self._correlator.correlate(alert)
        if correlated is not None:
            self._pending_incidents.append(correlated)

    def _flush_pending_incidents(self) -> None:
        while self._pending_incidents:
            incident, alert = self._pending_incidents[0]
            self._incident_store.persist(incident, alert)
            self._pending_incidents.popleft()


def _stable_alert_id(
    source: str,
    service: str,
    detected_at: datetime,
    fingerprint: str,
) -> str:
    material = f"{source}:{service}:{detected_at.isoformat()}:{fingerprint}"
    return f"al-{sha256(material.encode('utf-8')).hexdigest()[:24]}"
