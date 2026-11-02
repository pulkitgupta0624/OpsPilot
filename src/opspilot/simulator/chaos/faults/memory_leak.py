"""Gradual memory growth ending in modelled OOM restarts."""

from typing import ClassVar

from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.engine.state import ServiceState


class MemoryLeak(Fault):
    fault_type: ClassVar[FaultType] = FaultType.MEMORY_LEAK
    correct_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.RESTART_SERVICE,)
    acceptable_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.SCALE_OUT,)
    resolved_by: ClassVar[frozenset[ActionType]] = frozenset(
        {ActionType.RESTART_SERVICE, ActionType.SCALE_OUT}
    )
    log_message: ClassVar[str] = "GC pause warning; memory pressure is increasing"
    log_level: ClassVar[str] = "WARN"

    def apply(self, state: ServiceState, tick_seconds: int) -> None:
        growth_mb = 0.55 * self.intensity * (tick_seconds / 5.0)
        state.memory_mb += growth_mb
        if state.memory_mb >= state.config.memory_limit_mb and not state.oom_this_tick:
            state.oom_restart()

