"""Benign changes and short transients for false-positive evaluation."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from opspilot.core.config import DecoyScheduleConfig
from opspilot.domain.enums import DecoyType
from opspilot.simulator.engine.state import ServiceState


@dataclass
class DecoyEvent:
    """A known non-fault event that should not be treated as a lasting incident."""

    decoy_id: str
    decoy_type: DecoyType
    service: str
    start_at: datetime
    duration_seconds: int
    intensity: float
    logged: bool = False
    applied: bool = False

    @property
    def end_at(self) -> datetime:
        return self.start_at + timedelta(seconds=self.duration_seconds)

    def active_at(self, timestamp: datetime) -> bool:
        return self.start_at <= timestamp < self.end_at

    def prepare_tick(
        self,
        timestamp: datetime,
        states: dict[str, ServiceState],
        request_rates: dict[str, float],
    ) -> tuple[str, str] | None:
        """Apply load or deployment changes and return a one-time log message."""
        is_active = self.active_at(timestamp)
        if is_active and self.decoy_type == DecoyType.TRAFFIC_SPIKE:
            request_rates[self.service] *= self.intensity
        if (
            is_active
            and self.decoy_type == DecoyType.HARMLESS_DEPLOYMENT
            and not self.applied
        ):
            state = states[self.service]
            state.previous_version = state.app_version
            state.app_version = "1.1.0"
            self.applied = True
        if is_active and not self.logged:
            self.logged = True
            messages = {
                DecoyType.HARMLESS_DEPLOYMENT: "new version deployed without a behavior change",
                DecoyType.TRANSIENT_BLIP: "brief transient retry spike recovered without action",
                DecoyType.TRAFFIC_SPIKE: "normal short-lived traffic burst",
            }
            return self.service, messages[self.decoy_type]
        return None

    def apply_metrics(self, timestamp: datetime, state: ServiceState) -> None:
        """Apply the temporary signature for a short transient decoy."""
        if not self.active_at(timestamp) or self.decoy_type != DecoyType.TRANSIENT_BLIP:
            return
        state.error_rate = max(state.error_rate, 0.025 * self.intensity)
        state.latency_ms_p95 += 140.0 * self.intensity
        state.latency_ms_p99 += 240.0 * self.intensity


def build_decoy_schedule(
    config: DecoyScheduleConfig, start_at: datetime, index: int
) -> DecoyEvent:
    """Convert one relative YAML schedule into a runtime decoy event."""
    return DecoyEvent(
        decoy_id=f"d-{index:04d}",
        decoy_type=config.decoy_type,
        service=config.service,
        start_at=start_at + timedelta(seconds=config.start_offset_seconds),
        duration_seconds=config.duration_seconds,
        intensity=config.intensity,
    )

