"""Incident queries, agent state, approval, reruns, and event streaming."""

import asyncio
import json
import time
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select
from starlette.concurrency import run_in_threadpool

from opspilot.api.dependencies import get_services
from opspilot.api.schemas import (
    ApprovalRequest,
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentSummary,
)
from opspilot.api.security import require_api_key
from opspilot.api.services import APIServices
from opspilot.domain.models.incident import Alert, Incident
from opspilot.ingestion.schema import alerts, incidents
from opspilot.ingestion.stores.postgres_incidents import PostgresIncidentStore

router = APIRouter(
    prefix="/v1/incidents",
    tags=["incidents"],
    dependencies=[Depends(require_api_key)],
)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    services: APIServices = Depends(get_services),
    status: Literal["open", "resolved", "escalated"] | None = None,
    service: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> IncidentListResponse:
    """List incidents with service/date filters and offset pagination."""
    filters = []
    if status is not None:
        filters.append(incidents.c.status == status)
    if service is not None:
        filters.append(incidents.c.affected_services.any(service))
    if since is not None:
        filters.append(incidents.c.last_alert_at >= since)
    if until is not None:
        filters.append(incidents.c.last_alert_at <= until)
    with services.engine.connect() as connection:
        total = int(
            connection.execute(
                select(func.count()).select_from(incidents).where(*filters)
            ).scalar_one()
        )
        rows = (
            connection.execute(
                select(incidents)
                .where(*filters)
                .order_by(desc(incidents.c.last_alert_at))
                .limit(limit)
                .offset(offset)
            )
            .mappings()
            .all()
        )
    return IncidentListResponse(
        items=[_incident_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
def incident_detail(
    incident_id: str,
    services: APIServices = Depends(get_services),
) -> IncidentDetailResponse:
    """Return one incident, its alert timeline, and any persisted agent state."""
    with services.engine.connect() as connection:
        row = (
            connection.execute(select(incidents).where(incidents.c.id == incident_id))
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Incident was not found")
        alert_rows = (
            connection.execute(
                select(alerts)
                .where(alerts.c.incident_id == incident_id)
                .order_by(alerts.c.detected_at.asc())
            )
            .mappings()
            .all()
        )
    agent_state = _agent_state(services, incident_id)
    return IncidentDetailResponse(
        incident=_incident_summary(row),
        alerts=[Alert.model_validate(dict(item)).model_dump(mode="json") for item in alert_rows],
        agent=_agent_summary(agent_state),
    )


@router.get("/{incident_id}/trace")
def incident_trace(
    incident_id: str,
    services: APIServices = Depends(get_services),
) -> dict[str, Any]:
    """Return graph node events plus durable audit events for one incident."""
    if not _incident_exists(services, incident_id):
        raise HTTPException(status_code=404, detail="Incident was not found")
    state = _agent_state(services, incident_id)
    return {
        "incident_id": incident_id,
        "trace": state.get("trace", []),
        "audit_events": services.audit_events(incident_id),
    }


@router.post("/{incident_id}/approval")
def decide_approval(
    incident_id: str,
    body: ApprovalRequest,
    services: APIServices = Depends(get_services),
) -> dict[str, Any]:
    """Resume a paused graph after recording the authenticated human decision."""
    if not _incident_exists(services, incident_id):
        raise HTTPException(status_code=404, detail="Incident was not found")
    with services.open_agent_runtime() as runtime:
        result = runtime.approve(
            incident_id,
            approved=body.approved,
            reviewer=body.reviewer,
            comment=body.comment,
        )
    status = str(result.get("status", "waiting_approval"))
    if status in {"resolved", "escalated"}:
        PostgresIncidentStore(services.engine).set_status(incident_id, status)
    return _agent_command_result(result, incident_id)


@router.post("/{incident_id}/rerun")
def rerun_agent(
    incident_id: str,
    services: APIServices = Depends(get_services),
) -> dict[str, Any]:
    """Start the agent again for an open incident (local demo/operator action)."""
    record = PostgresIncidentStore(services.engine).load_open(incident_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No matching open incident was found")
    incident, incident_alerts = record
    with services.open_agent_runtime() as runtime:
        result = runtime.run(incident, incident_alerts)
    status = str(result.get("status", "waiting_approval"))
    if status in {"resolved", "escalated"}:
        PostgresIncidentStore(services.engine).set_status(incident_id, status)
    return _agent_command_result(result, incident_id)


@router.get("/{incident_id}/stream")
def stream_incident(
    incident_id: str,
    request: Request,
    services: APIServices = Depends(get_services),
    poll_seconds: Annotated[float, Query(gt=0, le=30)] | None = None,
) -> StreamingResponse:
    """Stream changed incident/agent snapshots until terminal state or timeout."""
    if not _incident_exists(services, incident_id):
        raise HTTPException(status_code=404, detail="Incident was not found")
    interval = poll_seconds or services.settings.stream_poll_seconds

    async def events():
        last_payload: str | None = None
        deadline = time.monotonic() + services.settings.stream_max_seconds
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                return
            incident_row = await run_in_threadpool(_load_incident_row, services, incident_id)
            if incident_row is None:
                return
            state = await run_in_threadpool(_agent_state, services, incident_id)
            update = {
                "incident": _incident_summary(incident_row).model_dump(mode="json"),
                "agent": _agent_summary(state),
            }
            payload = json.dumps(update, ensure_ascii=False, sort_keys=True, default=str)
            if payload != last_payload:
                yield f"event: incident_update\ndata: {payload}\n\n"
                last_payload = payload
            else:
                yield ": keep-alive\n\n"
            if update["incident"]["status"] in {"resolved", "escalated"}:
                return
            await asyncio.sleep(interval)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _incident_summary(row: Any) -> IncidentSummary:
    incident = Incident.model_validate(
        {key: row[key] for key in incidents.c.keys() if key in Incident.model_fields}
    )
    return IncidentSummary.model_validate(incident.model_dump())


def _incident_exists(services: APIServices, incident_id: str) -> bool:
    with services.engine.connect() as connection:
        return (
            connection.execute(
                select(incidents.c.id).where(incidents.c.id == incident_id)
            ).first()
            is not None
        )


def _load_incident_row(services: APIServices, incident_id: str) -> Any | None:
    with services.engine.connect() as connection:
        return (
            connection.execute(select(incidents).where(incidents.c.id == incident_id))
            .mappings()
            .first()
        )


def _agent_state(services: APIServices, incident_id: str) -> dict[str, Any]:
    with services.open_agent_runtime() as runtime:
        return runtime.state(incident_id)


def _agent_summary(state: dict[str, Any]) -> dict[str, Any] | None:
    if not state:
        return None
    fields = (
        "status",
        "severity",
        "plan",
        "policy",
        "approval",
        "execution",
        "verification",
        "report_path",
        "kb_indexed",
        "escalation_reason",
    )
    return {field: state[field] for field in fields if field in state}


def _agent_command_result(result: dict[str, Any], incident_id: str) -> dict[str, Any]:
    interrupts = result.get("__interrupt__", [])
    interrupt_value = None
    if interrupts:
        interrupt_value = getattr(interrupts[0], "value", interrupts[0])
    return {
        "incident_id": incident_id,
        "status": result.get("status", "waiting_approval" if interrupts else "unknown"),
        "interrupt": interrupt_value,
        "plan": result.get("plan"),
        "execution": result.get("execution"),
        "verification": result.get("verification"),
        "report_path": result.get("report_path"),
        "escalation_reason": result.get("escalation_reason"),
    }
