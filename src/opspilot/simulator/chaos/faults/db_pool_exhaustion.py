"""Connection leak that saturates a service's database pool."""

from typing import ClassVar

from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.engine.state import ServiceState


class DbPoolExhaustion(Fault):
    fault_type: ClassVar[FaultType] = FaultType.DB_POOL_EXHAUSTION
    correct_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.INCREASE_DB_POOL,)
    acceptable_actions: ClassVar[tuple[ActionType, ...]] = (ActionType.RESTART_SERVICE,)
    resolved_by: ClassVar[frozenset[ActionType]] = frozenset(
        {ActionType.INCREASE_DB_POOL, ActionType.RESTART_SERVICE}
    )
    log_message: ClassVar[str] = "database connection acquire timeout"

    def apply(self, state: ServiceState, tick_seconds: int) -> None:
        state.db_pool_in_use = state.db_pool_size
        state.error_rate = max(state.error_rate, min(0.75, 0.12 * self.intensity))
        state.latency_ms_p50 += 120.0 * self.intensity
        state.latency_ms_p95 += 1_100.0 * self.intensity
        state.latency_ms_p99 += 1_800.0 * self.intensity
        state.queue_depth += max(4, round(state.request_rate_per_s * 0.3))

