"""Persistence port for alerts and correlated incidents."""

from typing import Protocol

from opspilot.domain.models.incident import Alert, Incident


class IncidentStore(Protocol):
    """Write incident aggregates and their alert evidence idempotently."""

    def persist(self, incident: Incident, alert: Alert) -> bool: ...
