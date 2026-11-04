"""Idempotent Postgres persistence for incidents and linked alert evidence."""

from sqlalchemy import Engine, desc, select, update
from sqlalchemy.dialects.postgresql import insert

from opspilot.domain.models.incident import Alert, Incident
from opspilot.domain.ports.incident_store import IncidentStore
from opspilot.ingestion.schema import alerts, incidents


class PostgresIncidentStore(IncidentStore):
    """Write incidents and alerts in one transaction with duplicate-safe alert IDs."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def persist(self, incident: Incident, alert: Alert) -> bool:
        """Insert or update the incident and add its alert once; return whether alert was new."""
        if alert.incident_id != incident.id:
            raise ValueError("Alert incident_id must match the supplied Incident")
        incident_statement = insert(incidents).values(
            id=incident.id,
            status=incident.status,
            severity=incident.severity,
            affected_services=incident.affected_services,
            detected_at=incident.detected_at,
            last_alert_at=incident.last_alert_at,
            summary=incident.summary,
        ).on_conflict_do_nothing(index_elements=["id"])
        alert_statement = insert(alerts).values(
            id=alert.id,
            incident_id=incident.id,
            detector=alert.detector,
            source=alert.source,
            service=alert.service,
            score=alert.score,
            threshold=alert.threshold,
            started_at=alert.started_at,
            detected_at=alert.detected_at,
            suspect_features=[item.model_dump(mode="json") for item in alert.suspect_features],
            details=alert.details,
        ).on_conflict_do_nothing(index_elements=["id"])

        with self._engine.begin() as connection:
            connection.execute(incident_statement)
            current = connection.execute(
                select(incidents.c.affected_services, incidents.c.last_alert_at)
                .where(incidents.c.id == incident.id)
                .with_for_update()
            ).one()
            services = sorted(set(current.affected_services) | set(incident.affected_services))
            last_alert = max(current.last_alert_at, incident.last_alert_at)
            connection.execute(
                update(incidents)
                .where(incidents.c.id == incident.id)
                .values(affected_services=services, last_alert_at=last_alert)
            )
            result = connection.execute(alert_statement)
        return bool(result.rowcount)

    def load_open(
        self, incident_id: str | None = None
    ) -> tuple[Incident, list[Alert]] | None:
        """Load one open incident and its alerts, defaulting to the most recently active."""
        statement = select(incidents).where(incidents.c.status == "open")
        if incident_id is not None:
            statement = statement.where(incidents.c.id == incident_id)
        statement = statement.order_by(desc(incidents.c.last_alert_at)).limit(1)
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
            if row is None:
                return None
            alert_rows = (
                connection.execute(
                    select(alerts)
                    .where(alerts.c.incident_id == row["id"])
                    .order_by(alerts.c.detected_at.asc())
                )
                .mappings()
                .all()
            )
        incident = Incident.model_validate(
            {key: row[key] for key in incidents.c.keys() if key in Incident.model_fields}
        )
        incident_alerts = [Alert.model_validate(dict(alert_row)) for alert_row in alert_rows]
        return incident, incident_alerts

    def set_status(self, incident_id: str, status: str) -> None:
        """Record the final agent outcome using the incident status constraint."""
        if status not in {"open", "resolved", "escalated"}:
            raise ValueError(f"Unsupported incident status: {status}")
        with self._engine.begin() as connection:
            result = connection.execute(
                update(incidents).where(incidents.c.id == incident_id).values(status=status)
            )
        if not result.rowcount:
            raise ValueError(f"Incident '{incident_id}' does not exist")
