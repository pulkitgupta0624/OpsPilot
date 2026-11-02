"""Mutable internal service state for a single simulator tick."""

from dataclasses import dataclass, field

from opspilot.core.config import ServiceConfig
from opspilot.domain.enums import ActionType


@dataclass
class ServiceState:
    """Modelled state; resource values represent the service, not the host."""

    name: str
    config: ServiceConfig
    memory_mb: float = field(init=False)
    db_pool_size: int = field(init=False)
    db_pool_in_use: int = field(init=False, default=0)
    disk_used_pct: float = field(init=False)
    app_version: str = field(init=False)
    previous_version: str = field(init=False)
    restarts_total: int = field(init=False, default=0)
    request_rate_per_s: float = field(init=False, default=0.0)
    error_rate: float = field(init=False, default=0.002)
    latency_ms_p50: float = field(init=False, default=80.0)
    latency_ms_p95: float = field(init=False, default=180.0)
    latency_ms_p99: float = field(init=False, default=300.0)
    cpu_pct: float = field(init=False, default=10.0)
    queue_depth: int = field(init=False, default=0)
    oom_this_tick: bool = field(init=False, default=False)
    replicas: int = field(init=False, default=1)
    circuit_breaker_enabled: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.memory_mb = self.config.base_memory_mb
        self.db_pool_size = self.config.db_pool_size
        self.disk_used_pct = self.config.disk_baseline_pct
        self.app_version = self.config.version
        self.previous_version = self.config.version

    def begin_tick(self, request_rate_per_s: float, cpu_noise: float) -> None:
        """Reset transient values and establish this tick's healthy baseline."""
        self.request_rate_per_s = max(0.0, request_rate_per_s)
        self.error_rate = 0.002
        self.latency_ms_p50 = 72.0 + self.request_rate_per_s * 0.18
        self.latency_ms_p95 = 145.0 + self.request_rate_per_s * 0.55
        self.latency_ms_p99 = 230.0 + self.request_rate_per_s * 0.9
        self.cpu_pct = min(95.0, max(1.0, 7.0 + self.request_rate_per_s * 0.62 + cpu_noise))
        self.db_pool_in_use = min(
            self.db_pool_size,
            max(0, round(self.request_rate_per_s * 0.18)),
        )
        self.queue_depth = max(0, round(self.request_rate_per_s * 0.08 - 2.0))
        self.oom_this_tick = False

    def oom_restart(self) -> None:
        """Model a process restart after memory exceeds its configured limit."""
        self.restarts_total += 1
        self.memory_mb = self.config.base_memory_mb * 0.78
        self.error_rate = max(self.error_rate, 0.22)
        self.latency_ms_p95 *= 1.8
        self.latency_ms_p99 *= 2.0
        self.oom_this_tick = True

    def apply_action(self, action: ActionType) -> None:
        """Apply the deterministic state change for a whitelisted simulator action."""
        if action == ActionType.RESTART_SERVICE:
            self.restarts_total += 1
            self.memory_mb = self.config.base_memory_mb
        elif action == ActionType.ROLLBACK_DEPLOYMENT:
            self.app_version = self.previous_version
        elif action == ActionType.SCALE_OUT:
            self.replicas += 1
        elif action in {ActionType.CLEAR_DISK, ActionType.CLEAR_DISK_SPACE}:
            self.disk_used_pct = min(self.disk_used_pct, 55.0)
        elif action == ActionType.INCREASE_DB_POOL:
            self.db_pool_size = min(self.db_pool_size * 2, 256)
        elif action == ActionType.ENABLE_CIRCUIT_BREAKER:
            self.circuit_breaker_enabled = True

    def normalize(self) -> None:
        """Keep the final tick values within their domain bounds."""
        self.error_rate = min(1.0, max(0.0, self.error_rate))
        self.cpu_pct = min(100.0, max(0.0, self.cpu_pct))
        self.memory_mb = max(0.0, self.memory_mb)
        self.db_pool_in_use = min(self.db_pool_size, max(0, self.db_pool_in_use))
        self.disk_used_pct = min(100.0, max(0.0, self.disk_used_pct))
        self.queue_depth = max(0, self.queue_depth)
        self.latency_ms_p50 = max(0.0, self.latency_ms_p50)
        self.latency_ms_p95 = max(self.latency_ms_p50, self.latency_ms_p95)
        self.latency_ms_p99 = max(self.latency_ms_p95, self.latency_ms_p99)

