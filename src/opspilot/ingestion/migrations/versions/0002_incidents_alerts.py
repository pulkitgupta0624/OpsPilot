"""Persist correlated incidents and their metric/log alert evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_incidents_alerts"
down_revision: str | None = "0001_initial_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("affected_services", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index(
        "idx_incidents_status_last_alert",
        "incidents",
        ["status", "last_alert_at"],
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("incident_id", sa.Text(), nullable=False),
        sa.Column("detector", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "suspect_features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], name="fk_alerts_incident_id"),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
    )
    op.create_index("idx_alerts_incident_detected", "alerts", ["incident_id", "detected_at"])
    op.create_index("idx_alerts_service_detected", "alerts", ["service", "detected_at"])


def downgrade() -> None:
    op.drop_index("idx_alerts_service_detected", table_name="alerts")
    op.drop_index("idx_alerts_incident_detected", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("idx_incidents_status_last_alert", table_name="incidents")
    op.drop_table("incidents")
