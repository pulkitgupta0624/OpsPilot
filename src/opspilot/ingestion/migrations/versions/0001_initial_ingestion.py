"""Create idempotent metrics, logs, and fault ground-truth tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_ingestion"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metrics",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "service", "name", "ts", name="pk_metrics"),
    )
    op.create_index("idx_metrics_service_name_ts", "metrics", ["service", "name", "ts"])
    op.create_index("idx_metrics_run_service_ts", "metrics", ["run_id", "service", "ts"])

    op.create_table(
        "logs",
        sa.Column("record_key", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("record_key", name="pk_logs"),
    )
    op.create_index("idx_logs_service_ts", "logs", ["service", "ts"])
    op.create_index("idx_logs_run_service_ts", "logs", ["run_id", "service", "ts"])

    op.create_table(
        "ground_truth_faults",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("fault_id", sa.Text(), nullable=False),
        sa.Column("fault_type", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("correct_actions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("acceptable_actions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "fault_id", name="pk_ground_truth_faults"),
    )
    op.create_index(
        "idx_ground_truth_run_service_start",
        "ground_truth_faults",
        ["run_id", "service", "start_ts"],
    )


def downgrade() -> None:
    op.drop_index("idx_ground_truth_run_service_start", table_name="ground_truth_faults")
    op.drop_table("ground_truth_faults")
    op.drop_index("idx_logs_run_service_ts", table_name="logs")
    op.drop_index("idx_logs_service_ts", table_name="logs")
    op.drop_table("logs")
    op.drop_index("idx_metrics_run_service_ts", table_name="metrics")
    op.drop_index("idx_metrics_service_name_ts", table_name="metrics")
    op.drop_table("metrics")

