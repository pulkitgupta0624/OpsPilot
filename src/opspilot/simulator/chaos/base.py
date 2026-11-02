"""Shared fault contract for deterministic and live simulation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.engine.state import ServiceState


@dataclass
class Fault(ABC):
    """A scheduled fault and its known ground truth."""

    fault_id: str
    service: str
    start_at: datetime
    duration_seconds: int
    intensity: float
    resolved: bool = False

    fault_type: ClassVar[FaultType]
    correct_actions: ClassVar[tuple[ActionType, ...]]
    acceptable_actions: ClassVar[tuple[ActionType, ...]] = ()
    resolved_by: ClassVar[frozenset[ActionType]]
    log_message: ClassVar[str]
    log_level: ClassVar[str] = "ERROR"

    @property
    def end_at(self) -> datetime:
        return self.start_at + timedelta(seconds=self.duration_seconds)

    def active_at(self, timestamp: datetime) -> bool:
        return not self.resolved and self.start_at <= timestamp < self.end_at

    @abstractmethod
    def apply(self, state: ServiceState, tick_seconds: int) -> None:
        """Apply this fault's metrics signature to one service state."""

    def on_action(self, action: ActionType, state: ServiceState) -> bool:
        """Resolve only when the action catalog says the action is valid here."""
        if action not in self.resolved_by:
            return False
        state.apply_action(action)
        self.resolved = True
        return True

