"""Disk growth that eventually causes write failures."""

from typing import ClassVar

from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.engine.state import ServiceState


class DiskFull(Fault):
    fault_type: ClassVar[FaultType] = FaultType.DISK_FULL
    correct_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.CLEAR_DISK_SPACE,)
    acceptable_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.CLEAR_DISK,)
    resolved_by: ClassVar[frozenset[ActionType]] = frozenset(
        {ActionType.CLEAR_DISK_SPACE, ActionType.CLEAR_DISK}
    )
    log_message: ClassVar[str] = "No space left on device while writing request data"

    def apply(self, state: ServiceState, tick_seconds: int) -> None:
        growth = 0.20 * self.intensity * (tick_seconds / 5.0)
        state.disk_used_pct = min(100.0, state.disk_used_pct + growth)
        if state.disk_used_pct >= 95.0:
            state.error_rate = max(state.error_rate, 0.16 * self.intensity)
            state.latency_ms_p95 += 450.0
            state.latency_ms_p99 += 900.0

