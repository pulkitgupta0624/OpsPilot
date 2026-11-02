"""Shared SQLAlchemy table metadata for Postgres stores and Alembic."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

metrics = Table(
    "metrics",
    metadata,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("run_id", Text, nullable=False),
    Column("service", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("value", Float, nullable=False),
    PrimaryKeyConstraint("run_id", "service", "name", "ts", name="pk_metrics"),
)
Index("idx_metrics_service_name_ts", metrics.c.service, metrics.c.name, metrics.c.ts)
Index("idx_metrics_run_service_ts", metrics.c.run_id, metrics.c.service, metrics.c.ts)

logs = Table(
    "logs",
    metadata,
    Column("record_key", String(64), primary_key=True),
    Column("run_id", Text, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("service", Text, nullable=False),
    Column("level", String(10), nullable=False),
    Column("trace_id", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("fields", JSON().with_variant(JSONB(), "postgresql"), nullable=False),
)
Index("idx_logs_service_ts", logs.c.service, logs.c.ts)
Index("idx_logs_run_service_ts", logs.c.run_id, logs.c.service, logs.c.ts)

ground_truth_faults = Table(
    "ground_truth_faults",
    metadata,
    Column("run_id", Text, nullable=False),
    Column("fault_id", Text, nullable=False),
    Column("fault_type", Text, nullable=False),
    Column("service", Text, nullable=False),
    Column("start_ts", DateTime(timezone=True), nullable=False),
    Column("end_ts", DateTime(timezone=True), nullable=False),
    Column("intensity", Float, nullable=False),
    Column("correct_actions", ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False),
    Column("acceptable_actions", ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False),
    PrimaryKeyConstraint("run_id", "fault_id", name="pk_ground_truth_faults"),
)
Index(
    "idx_ground_truth_run_service_start",
    ground_truth_faults.c.run_id,
    ground_truth_faults.c.service,
    ground_truth_faults.c.start_ts,
)

incidents = Table(
    "incidents",
    metadata,
    Column("id", Text, primary_key=True),
    Column("status", String(20), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("affected_services", ARRAY(Text), nullable=False),
    Column("detected_at", DateTime(timezone=True), nullable=False),
    Column("last_alert_at", DateTime(timezone=True), nullable=False),
    Column("summary", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)
Index("idx_incidents_status_last_alert", incidents.c.status, incidents.c.last_alert_at)

alerts = Table(
    "alerts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("incident_id", Text, ForeignKey("incidents.id"), nullable=False),
    Column("detector", Text, nullable=False),
    Column("source", String(20), nullable=False),
    Column("service", Text, nullable=False),
    Column("score", Float, nullable=False),
    Column("threshold", Float, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("detected_at", DateTime(timezone=True), nullable=False),
    Column("suspect_features", JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    Column("details", JSON().with_variant(JSONB(), "postgresql"), nullable=False),
)
Index("idx_alerts_incident_detected", alerts.c.incident_id, alerts.c.detected_at)
Index("idx_alerts_service_detected", alerts.c.service, alerts.c.detected_at)

