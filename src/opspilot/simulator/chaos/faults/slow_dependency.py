"""Slow downstream service that blocks its caller's request path."""

from typing import ClassVar

from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.engine.state import ServiceState


class SlowDependency(Fault):
    fault_type: ClassVar[FaultType] = FaultType.SLOW_DEPENDENCY
    correct_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.ENABLE_CIRCUIT_BREAKER,)
    acceptable_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.SCALE_OUT,)
    resolved_by: ClassVar[frozenset[ActionType]] = frozenset(
        {ActionType.ENABLE_CIRCUIT_BREAKER, ActionType.SCALE_OUT}
    )
    log_message: ClassVar[str] = "upstream dependency timeout; request retried"

    def apply(self, state: ServiceState, tick_seconds: int) -> None:
        multiplier = 1.0 + 2.2 * self.intensity
        state.latency_ms_p50 *= multiplier
        state.latency_ms_p95 *= multiplier
        state.latency_ms_p99 *= multiplier
        state.queue_depth += max(3, round(state.request_rate_per_s * 0.35))
        state.error_rate = max(state.error_rate, 0.04 * self.intensity)
        if state.circuit_breaker_enabled:
            state.error_rate *= 0.5
            state.queue_depth = max(0, state.queue_depth // 2)

