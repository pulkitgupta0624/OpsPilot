"""Build fault objects from a validated, reproducible schedule."""

from datetime import datetime, timedelta

from opspilot.core.config import SimulationConfig
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.chaos.decoys import DecoyEvent, build_decoy_schedule
from opspilot.simulator.chaos.faults import create_fault


def build_fault_schedule(config: SimulationConfig, start_at: datetime | None = None) -> list[Fault]:
    """Create ordered fault instances, with offsets measured from ``start_at``."""
    simulation_start = start_at or config.start_at
    faults: list[Fault] = []
    for index, schedule in enumerate(config.faults, start=1):
        faults.append(
            create_fault(
                schedule.fault_type,
                fault_id=f"f-{index:04d}",
                service=schedule.service,
                start_at=simulation_start + timedelta(seconds=schedule.start_offset_seconds),
                duration_seconds=schedule.duration_seconds,
                intensity=schedule.intensity,
            )
        )
    return faults


def build_decoy_events(
    config: SimulationConfig, start_at: datetime | None = None
) -> list[DecoyEvent]:
    """Create configured benign events relative to ``start_at``."""
    simulation_start = start_at or config.start_at
    return [
        build_decoy_schedule(event, simulation_start, index)
        for index, event in enumerate(config.decoys, start=1)
    ]

