"""Service dependency topology and symptom propagation rules."""

from opspilot.simulator.engine.state import ServiceState

SERVICE_CALLS: dict[str, tuple[str, ...]] = {
    "orders": ("payments", "inventory"),
    "payments": (),
    "inventory": (),
}


def upstream_services(service: str) -> tuple[str, ...]:
    """Return services that call ``service`` in the simulated topology."""
    return tuple(
        caller for caller, dependencies in SERVICE_CALLS.items() if service in dependencies
    )


def propagate_slow_dependency(states: dict[str, ServiceState], dependency: str) -> None:
    """Make downstream latency faults visible at the orders front door."""
    for caller in upstream_services(dependency):
        state = states[caller]
        state.latency_ms_p50 += 90.0
        state.latency_ms_p95 += 650.0
        state.latency_ms_p99 += 1_100.0
        state.queue_depth += max(2, round(state.request_rate_per_s * 0.12))
        state.error_rate = max(state.error_rate, 0.025)

