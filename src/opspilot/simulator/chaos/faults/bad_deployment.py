"""Deployment that introduces a step change in errors and latency."""

from typing import ClassVar

from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.engine.state import ServiceState


class BadDeployment(Fault):
    fault_type: ClassVar[FaultType] = FaultType.BAD_DEPLOYMENT
    correct_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.ROLLBACK_DEPLOYMENT,)
    acceptable_actions: ClassVar[tuple[ActionType, ...]] = ()
    resolved_by: ClassVar[frozenset[ActionType]] = frozenset(
        {ActionType.ROLLBACK_DEPLOYMENT}
    )
    log_message: ClassVar[str] = "new release raised an unexpected application exception"

    def apply(self, state: ServiceState, tick_seconds: int) -> None:
        if state.app_version != "2.0.0":
            state.previous_version = state.app_version
            state.app_version = "2.0.0"
        state.error_rate = max(state.error_rate, 0.08 * self.intensity)
        state.latency_ms_p95 *= 1.0 + 1.1 * self.intensity
        state.latency_ms_p99 *= 1.0 + 1.35 * self.intensity

