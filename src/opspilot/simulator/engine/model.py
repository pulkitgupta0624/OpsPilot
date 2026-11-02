"""Pure-Python engine that maps load and faults to metrics and structured logs."""

from datetime import datetime

import numpy as np

from opspilot.core.clock import Clock, VirtualClock
from opspilot.core.config import SimulationConfig
from opspilot.core.ids import trace_id
from opspilot.domain.enums import ActionType, DecoyType, FaultType
from opspilot.domain.models.telemetry import GroundTruthRecord, LogRecord, MetricPoint
from opspilot.simulator.chaos.base import Fault
from opspilot.simulator.chaos.decoys import DecoyEvent
from opspilot.simulator.chaos.scheduler import build_decoy_events, build_fault_schedule
from opspilot.simulator.engine.state import ServiceState
from opspilot.simulator.engine.topology import propagate_slow_dependency
from opspilot.simulator.loadgen.profiles import DailyLoadProfile


class SimulationEngine:
    """Stateful simulator with seeded randomness and an injectable clock."""

    def __init__(
        self,
        config: SimulationConfig,
        *,
        seed: int,
        run_id: str,
        clock: Clock | None = None,
        schedule_from: datetime | None = None,
    ) -> None:
        self.config = config
        self.seed = seed
        self.run_id = run_id
        self.rng = np.random.default_rng(seed)
        self.clock = clock or VirtualClock(config.start_at)
        self.states = {
            name: ServiceState(name=name, config=service_config)
            for name, service_config in config.services.items()
        }
        self.faults: list[Fault] = build_fault_schedule(config, schedule_from)
        self.decoys: list[DecoyEvent] = build_decoy_events(config, schedule_from)
        self.load_profile = DailyLoadProfile(config, self.rng)
        self.step_index = 0
        self.recent_logs: list[LogRecord] = []

    def tick(self) -> tuple[list[MetricPoint], list[LogRecord]]:
        """Advance the model by one configured interval and return its telemetry."""
        timestamp = self.clock.now()
        request_rates = self.load_profile.sample(timestamp)
        decoy_logs: list[tuple[DecoyEvent, str, str]] = []
        for decoy in self.decoys:
            event_log = decoy.prepare_tick(timestamp, self.states, request_rates)
            if event_log is not None:
                decoy_logs.append((decoy, event_log[0], event_log[1]))
        for service, state in self.states.items():
            state.begin_tick(request_rates[service], float(self.rng.normal(0.0, 2.2)))

        active_faults: list[Fault] = []
        logs: list[LogRecord] = [
            LogRecord(
                ts=timestamp,
                level="WARN" if decoy.decoy_type == DecoyType.TRANSIENT_BLIP else "INFO",
                service=service,
                trace_id=trace_id(self.rng),
                message=message,
                fields={"decoy_id": decoy.decoy_id, "decoy_type": decoy.decoy_type.value},
            )
            for decoy, service, message in decoy_logs
        ]
        log_interval_steps = max(1, 60 // self.config.step_seconds)
        for fault in self.faults:
            if not fault.active_at(timestamp):
                continue
            active_faults.append(fault)
            fault.apply(self.states[fault.service], self.config.step_seconds)
            if self.step_index % log_interval_steps == 0:
                logs.append(
                    LogRecord(
                        ts=timestamp,
                        level=fault.log_level,  # type: ignore[arg-type]
                        service=fault.service,
                        trace_id=trace_id(self.rng),
                        message=fault.log_message,
                        fields={
                            "fault_id": fault.fault_id,
                            "fault_type": fault.fault_type.value,
                            "intensity": fault.intensity,
                        },
                    )
                )

        for fault in active_faults:
            if fault.fault_type == FaultType.SLOW_DEPENDENCY:
                propagate_slow_dependency(self.states, fault.service)

        for decoy in self.decoys:
            decoy.apply_metrics(timestamp, self.states[decoy.service])

        for state in self.states.values():
            state.normalize()
            if state.error_rate >= 0.08:
                level = "ERROR"
                message = "request failed while processing simulated traffic"
                should_log = float(self.rng.random()) < 0.5
            else:
                level = "WARN" if float(self.rng.random()) < 0.012 else "INFO"
                message = "retrying a transient downstream request" if level == "WARN" else "request processed"
                should_log = float(self.rng.random()) < 0.015
            if should_log:
                logs.append(
                    LogRecord(
                        ts=timestamp,
                        level=level,  # type: ignore[arg-type]
                        service=state.name,
                        trace_id=trace_id(self.rng),
                        message=message,
                        fields={"request_rate_per_s": state.request_rate_per_s},
                    )
                )

        metrics = [self._metric_point(timestamp, state) for state in self.states.values()]
        self.recent_logs.extend(logs)
        self.recent_logs = self.recent_logs[-500:]
        self.step_index += 1
        return metrics, logs

    def apply_action(self, service: str, action: ActionType) -> bool:
        """Apply a permitted action only when it resolves an active fault."""
        if service not in self.states:
            return False
        state = self.states[service]
        for fault in self.faults:
            if fault.service == service and fault.active_at(self.clock.now()):
                if fault.on_action(action, state):
                    return True
        return False

    def inject_fault(
        self,
        fault_type: FaultType,
        service: str,
        *,
        duration_seconds: int,
        intensity: float,
    ) -> Fault:
        """Add a fault at the current clock time for the demo admin API."""
        from opspilot.simulator.chaos.faults import create_fault

        if service not in self.states:
            raise ValueError(f"Unknown service: {service}")
        fault = create_fault(
            fault_type,
            fault_id=f"f-live-{len(self.faults) + 1:04d}",
            service=service,
            start_at=self.clock.now(),
            duration_seconds=duration_seconds,
            intensity=intensity,
        )
        self.faults.append(fault)
        return fault

    def ground_truth(self, fault: Fault) -> GroundTruthRecord:
        """Convert an internal fault to its public ground-truth schema."""
        from opspilot.simulator.engine.topology import upstream_services

        return GroundTruthRecord(
            run_id=self.run_id,
            fault_id=fault.fault_id,
            fault_type=fault.fault_type,
            service=fault.service,
            start=fault.start_at,
            end=fault.end_at,
            intensity=fault.intensity,
            correct_actions=list(fault.correct_actions),
            acceptable_actions=list(fault.acceptable_actions),
            propagates_to=list(upstream_services(fault.service))
            if fault.fault_type == FaultType.SLOW_DEPENDENCY
            else [],
        )

    def _metric_point(self, timestamp: datetime, state: ServiceState) -> MetricPoint:
        return MetricPoint(
            run_id=self.run_id,
            ts=timestamp,
            service=state.name,
            request_rate_per_s=state.request_rate_per_s,
            error_rate=state.error_rate,
            latency_ms_p50=state.latency_ms_p50,
            latency_ms_p95=state.latency_ms_p95,
            latency_ms_p99=state.latency_ms_p99,
            cpu_pct=state.cpu_pct,
            memory_mb=state.memory_mb,
            db_pool_in_use=state.db_pool_in_use,
            db_pool_size=state.db_pool_size,
            queue_depth=state.queue_depth,
            disk_used_pct=state.disk_used_pct,
            restarts_total=state.restarts_total,
            app_version=state.app_version,
        )

