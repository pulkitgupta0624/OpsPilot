"""SQLAlchemy engine construction for the Postgres ingestion adapter."""

import os

from sqlalchemy import Engine, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg://opspilot:opspilot@localhost:5432/opspilot"


def build_database_engine(database_url: str | None = None) -> Engine:
    """Build a pooled SQLAlchemy engine using explicit or environment configuration."""
    resolved_url = database_url or os.getenv("OPSPILOT_DATABASE_URL", DEFAULT_DATABASE_URL)
    return create_engine(
        resolved_url,
        pool_pre_ping=True,
        pool_recycle=1_800,
        future=True,
    )
