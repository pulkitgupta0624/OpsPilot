"""Drain3 template baseline and streaming new-template/frequency alerts."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from drain3.template_miner import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from opspilot.detection.config import LogDetectionSettings
from opspilot.domain.models.telemetry import LogRecord


@dataclass(frozen=True)
class LogTemplateAlert:
    """A newly seen template or a template whose rate exceeded its baseline."""

    service: str
    timestamp: datetime
    cluster_id: int
    template: str
    reason: str
    fingerprint: str


class Drain3LogDetector:
    """Learn normal templates once, then match live logs without changing the baseline."""

    def __init__(
        self,
        normal_logs: list[LogRecord],
        settings: LogDetectionSettings,
    ) -> None:
        if not normal_logs:
            raise ValueError("Drain3 needs normal-only log records to establish templates")
        self._settings = settings
        self._miners: dict[str, TemplateMiner] = {}
        self._baseline_counts: dict[tuple[str, int], int] = defaultdict(int)
        self._baseline_seconds: dict[str, float] = {}
        self._recent: dict[tuple[str, int], deque[datetime]] = defaultdict(deque)
        self._frequency_active: set[tuple[str, int]] = set()
        self._seen_records: set[str] = set()
        self._new_templates_reported: set[tuple[str, int]] = set()
        self._fit(normal_logs)

    def observe(self, records: list[LogRecord]) -> list[LogTemplateAlert]:
        """Return at most one signal per new record, suppressing duplicate polls."""
        alerts: list[LogTemplateAlert] = []
        window = self._settings.frequency_window_seconds
        for record in records:
            record_material = (
                f"{record.ts.isoformat()}:{record.service}:{record.trace_id}:"
                f"{record.message}"
            )
            key = sha256(record_material.encode("utf-8")).hexdigest()
            if key in self._seen_records:
                continue
            self._seen_records.add(key)
            miner = self._miners.get(record.service)
            if miner is None:
                miner = self._new_miner()
                self._miners[record.service] = miner
            cluster = miner.match(record.message)
            if cluster is None:
                result = miner.add_log_message(record.message)
                cluster_id = int(result["cluster_id"])
                template = str(result["template_mined"])
                template_key = (record.service, cluster_id)
                fingerprint = f"new:{record.service}:{cluster_id}:{template}"
                if template_key not in self._new_templates_reported:
                    self._new_templates_reported.add(template_key)
                    alerts.append(
                        LogTemplateAlert(
                            service=record.service,
                            timestamp=record.ts,
                            cluster_id=cluster_id,
                            template=template,
                            reason="new_template",
                            fingerprint=fingerprint,
                        )
                    )
                continue

            cluster_id = int(cluster.cluster_id)
            template_key = (record.service, cluster_id)
            recent = self._recent[template_key]
            recent.append(record.ts)
            cutoff = record.ts.timestamp() - window
            while recent and recent[0].timestamp() < cutoff:
                recent.popleft()
            baseline_per_window = (
                self._baseline_counts[template_key]
                * window
                / max(self._baseline_seconds.get(record.service, 1.0), 1.0)
            )
            threshold = max(
                self._settings.frequency_minimum_count,
                baseline_per_window * self._settings.frequency_multiplier,
            )
            if len(recent) >= threshold and template_key not in self._frequency_active:
                self._frequency_active.add(template_key)
                template = str(cluster.get_template())
                alerts.append(
                    LogTemplateAlert(
                        service=record.service,
                        timestamp=record.ts,
                        cluster_id=cluster_id,
                        template=template,
                        reason="frequency_spike",
                        fingerprint=f"frequency:{record.service}:{cluster_id}",
                    )
                )
            elif len(recent) < threshold:
                self._frequency_active.discard(template_key)
        if len(self._seen_records) > 50_000:
            # Bound memory for long-running monitors; this only suppresses recent duplicates.
            self._seen_records = set(list(self._seen_records)[-25_000:])
        return alerts

    def _fit(self, normal_logs: list[LogRecord]) -> None:
        by_service: dict[str, list[LogRecord]] = defaultdict(list)
        for record in normal_logs:
            by_service[record.service].append(record)
        for service, records in by_service.items():
            records.sort(key=lambda record: record.ts)
            miner = self._new_miner()
            for record in records:
                result = miner.add_log_message(record.message)
                cluster_id = int(result["cluster_id"])
                self._baseline_counts[(service, cluster_id)] += 1
            duration = (records[-1].ts - records[0].ts).total_seconds()
            self._miners[service] = miner
            self._baseline_seconds[service] = max(duration, 1.0)

    def _new_miner(self) -> TemplateMiner:
        config = TemplateMinerConfig()
        config.profiling_enabled = False
        config.drain_max_clusters = self._settings.max_clusters
        return TemplateMiner(config=config)


def load_normal_log_records(data_root: Path) -> list[LogRecord]:
    """Load only the JSONL logs whose companion ground-truth files contain no faults."""
    processed_dir = data_root / "processed"
    logs_dir = data_root / "raw"
    truth_dir = data_root / "ground_truth"
    records: list[LogRecord] = []
    for metrics_path in sorted(processed_dir.glob("simulation_*_metrics.parquet")):
        run_id = _run_id_from_path(metrics_path)
        truth_path = truth_dir / f"simulation_{run_id}_faults.jsonl"
        if truth_path.exists() and truth_path.stat().st_size:
            continue
        logs_path = logs_dir / f"simulation_{run_id}_logs.jsonl"
        if not logs_path.exists():
            continue
        with logs_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(LogRecord.model_validate_json(line))
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid normal log record in {logs_path} at line {line_number}: {exc}"
                    ) from exc
    if not records:
        raise FileNotFoundError(
            f"No normal-only log records found in {logs_dir}; generate a normal-only run first"
        )
    return records


def _run_id_from_path(path: Path) -> str:
    prefix = "simulation_"
    suffix = "_metrics.parquet"
    return path.name[len(prefix) : -len(suffix)]
