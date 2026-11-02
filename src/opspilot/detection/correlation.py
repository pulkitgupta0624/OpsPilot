"""Time-window and topology-aware alert grouping with dedupe/cooldown."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from opspilot.detection.config import CorrelationSettings
from opspilot.domain.models.incident import Alert, Incident

@dataclass
class _IncidentWindow:
    incident: Incident
    dedupe_keys: set[str]


class AlertCorrelator:
    """Merge related alerts and suppress duplicate alerts during a cooldown window."""

    def __init__(self, settings: CorrelationSettings) -> None:
        self._settings = settings
        self._incidents: list[_IncidentWindow] = []
        self._last_seen: dict[str, datetime] = {}

    def correlate(self, alert: Alert) -> tuple[Incident, Alert] | None:
        """Return an incident and linked alert, or ``None`` when cooldown suppresses it."""
        dedupe_key = _dedupe_key(alert)
        previous = self._last_seen.get(dedupe_key)
        if previous is not None:
            elapsed = alert.detected_at - previous
            if timedelta(0) <= elapsed <= timedelta(seconds=self._settings.cooldown_seconds):
                return None
        self._last_seen[dedupe_key] = alert.detected_at

        window = timedelta(seconds=self._settings.merge_window_seconds)
        candidates = [
            state
            for state in self._incidents
            if timedelta(0) <= alert.detected_at - state.incident.last_alert_at <= window
            and _services_related(
                alert.service,
                state.incident.affected_services,
                self._settings.service_neighbors,
            )
        ]
        if candidates:
            state = max(candidates, key=lambda item: item.incident.last_alert_at)
            services = sorted(set(state.incident.affected_services) | {alert.service})
            incident = state.incident.model_copy(
                update={"affected_services": services, "last_alert_at": alert.detected_at}
            )
            state.incident = incident
            state.dedupe_keys.add(dedupe_key)
        else:
            incident = Incident(
                id=f"inc-{uuid4().hex}",
                affected_services=[alert.service],
                detected_at=alert.detected_at,
                last_alert_at=alert.detected_at,
                summary=f"{alert.source.title()} anomaly for {alert.service} ({alert.detector})",
            )
            self._incidents.append(_IncidentWindow(incident, {dedupe_key}))

        cutoff = alert.detected_at - timedelta(
            seconds=max(self._settings.cooldown_seconds, self._settings.merge_window_seconds)
        )
        self._last_seen = {
            key: timestamp for key, timestamp in self._last_seen.items() if timestamp >= cutoff
        }
        if len(self._incidents) > 5_000:
            self._incidents = self._incidents[-2_500:]
        linked_alert = alert.model_copy(update={"incident_id": incident.id})
        return incident, linked_alert


def _dedupe_key(alert: Alert) -> str:
    fingerprint = alert.details.get("fingerprint", alert.detector)
    return f"{alert.source}:{alert.service}:{alert.detector}:{fingerprint}"


def _services_related(
    service: str,
    affected: list[str],
    neighbors: dict[str, list[str]],
) -> bool:
    if service in affected:
        return True
    service_neighbors = set(neighbors.get(service, []))
    return any(item in service_neighbors for item in affected)
