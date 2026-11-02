"""Idempotent Postgres implementation of the structured log store port."""

from collections.abc import Sequence
from hashlib import sha256

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert

from opspilot.domain.models.telemetry import LogRecord, TimeRange
from opspilot.domain.ports.log_store import LogStore
from opspilot.ingestion.schema import logs


class PostgresLogStore(LogStore):
    """Persist structured logs with deterministic deduplication keys."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def write(self, records: Sequence[LogRecord], *, run_id: str | None = None) -> int:
        resolved_run_id = run_id or "live"
        rows = []
        for record in records:
            payload = record.model_dump_json()
            record_key = sha256(f"{resolved_run_id}:{payload}".encode("utf-8")).hexdigest()
            rows.append(
                {
                    "record_key": record_key,
                    "run_id": resolved_run_id,
                    "ts": record.ts,
                    "service": record.service,
                    "level": record.level,
                    "trace_id": record.trace_id,
                    "message": record.message,
                    "fields": record.fields,
                }
            )
        if not rows:
            return 0
        statement = insert(logs).values(rows).on_conflict_do_nothing(
            index_elements=["record_key"]
        )
        with self._engine.begin() as connection:
            result = connection.execute(statement)
        return int(result.rowcount or 0)

    def search(
        self,
        *,
        service: str | None,
        time_range: TimeRange,
        level: str | None = None,
        contains: str | None = None,
        limit: int = 200,
        run_id: str | None = None,
    ) -> list[LogRecord]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        statement = select(logs).where(
            logs.c.ts >= time_range.start,
            logs.c.ts <= time_range.end,
        )
        if service is not None:
            statement = statement.where(logs.c.service == service)
        if run_id is not None:
            statement = statement.where(logs.c.run_id == run_id)
        if level is not None:
            statement = statement.where(logs.c.level == level.upper())
        if contains:
            statement = statement.where(logs.c.message.ilike(f"%{contains}%"))
        statement = statement.order_by(logs.c.ts.asc()).limit(limit)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            LogRecord(
                ts=row["ts"],
                level=row["level"],
                service=row["service"],
                trace_id=row["trace_id"],
                message=row["message"],
                fields=row["fields"] or {},
            )
            for row in rows
        ]

