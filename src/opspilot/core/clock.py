"""Injectable clocks so simulations do not depend on direct wall-clock calls."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Small interface for code that needs the current timestamp."""

    def now(self) -> datetime: ...


class SystemClock:
    """UTC wall clock used by live service adapters."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class VirtualClock:
    """Deterministic clock advanced explicitly by the simulation runner."""

    current_time: datetime

    def __post_init__(self) -> None:
        if self.current_time.tzinfo is None:
            raise ValueError("VirtualClock requires a timezone-aware datetime")
        self.current_time = self.current_time.astimezone(UTC)

    def now(self) -> datetime:
        return self.current_time

    def advance(self, seconds: int | float) -> datetime:
        if seconds <= 0:
            raise ValueError("Clock advance must be positive")
        self.current_time += timedelta(seconds=seconds)
        return self.current_time

