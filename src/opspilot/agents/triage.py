"""Deterministic service attribution guards for correlated incident alerts."""

import json
from collections import defaultdict
from typing import Any

_FAULT_FEATURES: dict[str, tuple[str, ...]] = {
    "db_pool_exhaustion": ("db_pool", "connection_pool", "acquire_timeout"),
    "memory_leak": ("memory_mb", "heap", "oom", "gc_pause"),
    "slow_dependency": (
        "dependency_latency",
        "upstream_latency",
        "latency_ms_p95",
        "dependency",
        "upstream",
    ),
    "bad_deployment": ("deployment", "version", "restarts_total"),
    "disk_full": ("disk_used_pct", "disk_free", "filesystem"),
}


def directly_alerted_services(alerts: list[dict[str, Any]]) -> list[str]:
    """Return unique alerting services in first-seen order."""
    return list(dict.fromkeys(str(alert["service"]) for alert in alerts if alert.get("service")))


def fault_signal_services(fault_type: str, alerts: list[dict[str, Any]]) -> list[str]:
    """Prefer explicit fault logs, then rank matching metric features."""
    terms = _FAULT_FEATURES.get(fault_type, ())
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, int] = {}
    log_matches: dict[str, int] = defaultdict(int)

    for position, alert in enumerate(alerts):
        service = str(alert.get("service", ""))
        if not service:
            continue
        features = alert.get("suspect_features", [])
        feature_matches = [
            item
            for item in features
            if isinstance(item, dict)
            and any(term in str(item.get("name", "")).lower() for term in terms)
        ]
        details = (
            json.dumps(alert.get("details", {}), sort_keys=True, default=str)
            .lower()
            .replace(" ", "_")
        )
        details_match = any(term in details for term in terms)
        if not feature_matches and not details_match:
            continue

        first_seen.setdefault(service, position)
        if str(alert.get("source", "")).lower() == "logs" and details_match:
            log_matches[service] += 1
        if feature_matches:
            contribution = sum(
                max(0.0, float(item.get("contribution", 0.0))) for item in feature_matches
            )
            scores[service] += contribution if contribution > 0 else float(len(feature_matches))
        else:
            scores[service] += 0.5

    if log_matches:
        strongest_log_count = max(log_matches.values())
        return [
            service
            for service in sorted(log_matches, key=lambda item: first_seen[item])
            if log_matches[service] == strongest_log_count
        ]
    if not scores:
        return []
    strongest_score = max(scores.values())
    return [
        service
        for service in sorted(scores, key=lambda item: first_seen[item])
        if scores[service] == strongest_score
    ]


def root_cause_service_is_supported(
    service: str, fault_type: str, alerts: list[dict[str, Any]]
) -> bool:
    """Require direct alert support, and honor fault-specific signals when present."""
    if service not in directly_alerted_services(alerts):
        return False
    matching_services = fault_signal_services(fault_type, alerts)
    return not matching_services or service in matching_services


def has_observed_fault_signal(fault_type: str, evidence: list[dict[str, Any]]) -> bool:
    """Require incident-specific live metrics, logs, or deployment evidence."""
    metric_values: dict[str, float] = {}
    log_text: list[str] = []
    deployment_text: list[str] = []

    for item in evidence:
        source = item.get("source")
        summary = str(item.get("summary", "")).lower()
        if source == "metrics":
            _, separator, payload = summary.partition(": ")
            if not separator:
                continue
            try:
                values = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(values, dict):
                for name, value in values.items():
                    try:
                        metric_values[str(name).split("{", 1)[0]] = float(value)
                    except (TypeError, ValueError):
                        continue
        elif source == "logs":
            log_text.append(summary)
        elif source == "deployments":
            deployment_text.append(summary)

    logs = " ".join(log_text)
    deployments = " ".join(deployment_text)
    if fault_type == "db_pool_exhaustion":
        pool_use = metric_values.get("db_pool_in_use")
        pool_size = metric_values.get("db_pool_size", 0.0)
        return bool(
            (pool_use is not None and pool_size > 0 and pool_use / pool_size >= 0.8)
            or any(
                term in logs for term in ("acquire timeout", "connection pool", "pool saturated")
            )
        )
    if fault_type == "memory_leak":
        return bool(
            metric_values.get("memory_mb", 0.0) >= 900
            or any(term in logs for term in ("memory leak", "out of memory", "oom", "gc pause"))
        )
    if fault_type == "slow_dependency":
        return bool(
            metric_values.get("latency_ms_p95", 0.0) >= 800
            or any(
                term in logs
                for term in ("upstream timeout", "dependency timeout", "slow dependency")
            )
        )
    if fault_type == "bad_deployment":
        return bool(
            "version changed by simulated fault" in deployments
            or any(term in logs for term in ("bad deployment", "deployment error"))
        )
    if fault_type == "disk_full":
        return bool(
            metric_values.get("disk_used_pct", 0.0) >= 80
            or any(term in logs for term in ("disk full", "filesystem full", "no space left"))
        )
    return False
