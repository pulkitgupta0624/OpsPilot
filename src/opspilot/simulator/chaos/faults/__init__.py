"""Fault implementations and their typed factory."""

from datetime import datetime

from opspilot.domain.enums import FaultType
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.chaos.faults.bad_deployment import BadDeployment
from opspilot.simulator.chaos.faults.db_pool_exhaustion import DbPoolExhaustion
from opspilot.simulator.chaos.faults.disk_full import DiskFull
from opspilot.simulator.chaos.faults.memory_leak import MemoryLeak
from opspilot.simulator.chaos.faults.slow_dependency import SlowDependency

FAULT_TYPES: dict[FaultType, type[Fault]] = {
    FaultType.MEMORY_LEAK: MemoryLeak,
    FaultType.DB_POOL_EXHAUSTION: DbPoolExhaustion,
    FaultType.SLOW_DEPENDENCY: SlowDependency,
    FaultType.BAD_DEPLOYMENT: BadDeployment,
    FaultType.DISK_FULL: DiskFull,
}


def create_fault(
    fault_type: FaultType,
    *,
    fault_id: str,
    service: str,
    start_at: datetime,
    duration_seconds: int,
    intensity: float,
) -> Fault:
    """Instantiate a catalogued fault without importing fault modules at call sites."""
    fault_class = FAULT_TYPES[fault_type]
    return fault_class(
        fault_id=fault_id,
        service=service,
        start_at=start_at,
        duration_seconds=duration_seconds,
        intensity=intensity,
    )


__all__ = ["FAULT_TYPES", "Fault", "create_fault"]

