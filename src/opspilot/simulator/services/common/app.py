"""FastAPI app factory shared by the orders, payments, and inventory simulators."""

from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from opspilot.core.clock import SystemClock
from opspilot.core.config import load_simulation_config
from opspilot.core.ids import simulation_run_id
from opspilot.domain.enums import ActionType, FaultType
from opspilot.simulator.engine.model import SimulationEngine


class FaultRequest(BaseModel):
    """Validated payload for the demo-only fault injection endpoint."""

    model_config = ConfigDict(extra="forbid")

    fault_type: FaultType
    duration_seconds: int = Field(default=900, gt=0)
    intensity: float = Field(default=1.0, ge=0.3, le=1.5)


def create_service_app(service_name: str) -> FastAPI:
    """Create one service adapter around a private in-memory simulator engine."""
    config_path = Path("configs/simulator.yaml")
    config = load_simulation_config(config_path)
    if service_name not in config.services:
        raise ValueError(f"Unknown service configured for app: {service_name}")

    clock = SystemClock()
    started_at = clock.now().astimezone(UTC)
    engine = SimulationEngine(
        config,
        seed=1,
        run_id=simulation_run_id(1, started_at),
        clock=clock,
        schedule_from=started_at,
    )
    app = FastAPI(
        title=f"OpsPilot {service_name.title()} Simulator",
        version="0.1.0",
        description="A deterministic, modelled microservice for OpsPilot demonstrations.",
    )
    app.state.engine = engine
    app.state.service_name = service_name
    app.state.latest_metrics = {}
    app.state.deployments = [
        {
            "version": config.services[service_name].version,
            "timestamp": started_at.isoformat(),
            "change_note": "initial simulated deployment",
        }
    ]
    app.state.last_seen_version = config.services[service_name].version

    def refresh_sample() -> dict[str, Any]:
        metrics, _ = engine.tick()
        point = next(metric for metric in metrics if metric.service == service_name)
        app.state.latest_metrics = point.model_dump(mode="json")
        current_version = engine.states[service_name].app_version
        if current_version != app.state.last_seen_version:
            app.state.deployments.append(
                {
                    "version": current_version,
                    "timestamp": clock.now().isoformat(),
                    "change_note": "version changed by simulated fault or admin action",
                }
            )
            app.state.last_seen_version = current_version
        return app.state.latest_metrics

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    @app.get("/metrics", tags=["telemetry"])
    def metrics() -> Response:
        sample = refresh_sample()
        prometheus = _format_prometheus(sample)
        return Response(content=prometheus, media_type="text/plain; version=0.0.4")

    @app.get("/admin/logs", tags=["admin"])
    def logs(limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        return [
            record.model_dump(mode="json")
            for record in engine.recent_logs
            if record.service == service_name
        ][-limit:]

    @app.post("/admin/fault", tags=["admin"])
    def inject_fault(request: FaultRequest) -> dict[str, Any]:
        fault = engine.inject_fault(
            request.fault_type,
            service_name,
            duration_seconds=request.duration_seconds,
            intensity=request.intensity,
        )
        return {
            "fault": engine.ground_truth(fault).model_dump(mode="json"),
            "status": "scheduled",
        }

    @app.post("/admin/action/{name}", tags=["admin"])
    def apply_action(name: str) -> dict[str, str | bool]:
        aliases = {
            "restart": ActionType.RESTART_SERVICE,
            "rollback": ActionType.ROLLBACK_DEPLOYMENT,
        }
        try:
            action = aliases[name] if name in aliases else ActionType(name)
        except ValueError as exc:
            supported = ", ".join(item.value for item in ActionType)
            raise HTTPException(
                status_code=404,
                detail=f"Unknown action '{name}'. Supported actions: {supported}",
            ) from exc
        accepted = engine.apply_action(service_name, action)
        if not accepted:
            raise HTTPException(
                status_code=409,
                detail="No active fault on this service accepts that action",
            )
        return {"service": service_name, "action": action.value, "accepted": True}

    @app.get("/admin/deployments", tags=["admin"])
    def deployments() -> list[dict[str, str]]:
        return list(app.state.deployments)

    return app


def _format_prometheus(sample: dict[str, Any]) -> str:
    """Format one service metric point in the Prometheus text exposition format."""
    service = str(sample["service"])
    lines = [
        f'opspilot_request_rate_per_s{{service="{service}"}} {sample["request_rate_per_s"]}',
        f'opspilot_error_rate{{service="{service}"}} {sample["error_rate"]}',
        f'opspilot_latency_ms_p50{{service="{service}"}} {sample["latency_ms_p50"]}',
        f'opspilot_latency_ms_p95{{service="{service}"}} {sample["latency_ms_p95"]}',
        f'opspilot_latency_ms_p99{{service="{service}"}} {sample["latency_ms_p99"]}',
        f'opspilot_cpu_pct{{service="{service}"}} {sample["cpu_pct"]}',
        f'opspilot_memory_mb{{service="{service}"}} {sample["memory_mb"]}',
        f'opspilot_db_pool_in_use{{service="{service}"}} {sample["db_pool_in_use"]}',
        f'opspilot_db_pool_size{{service="{service}"}} {sample["db_pool_size"]}',
        f'opspilot_queue_depth{{service="{service}"}} {sample["queue_depth"]}',
        f'opspilot_disk_used_pct{{service="{service}"}} {sample["disk_used_pct"]}',
        f'opspilot_restarts_total{{service="{service}"}} {sample["restarts_total"]}',
        f'opspilot_app_version_info{{service="{service}",version="{sample["app_version"]}"}} 1',
    ]
    return "\n".join(lines) + "\n"

