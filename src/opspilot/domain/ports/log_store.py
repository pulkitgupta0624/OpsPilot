"""Structured log persistence interface."""

from collections.abc import Sequence
from typing import Protocol

from opspilot.domain.models.telemetry import LogRecord, TimeRange


class LogStore(Protocol):
    """Read/write port for structured service logs."""

    def write(self, records: Sequence[LogRecord], *, run_id: str | None = None) -> int: ...

    def search(
        self,
        *,
        service: str | None,
        time_range: TimeRange,
        level: str | None = None,
        contains: str | None = None,
        limit: int = 200,
        run_id: str | None = None,
    ) -> list[LogRecord]: ...
