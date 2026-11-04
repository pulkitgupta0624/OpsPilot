"""Live metric series and detector-health queries."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select

from opspilot.api.dependencies import get_services
from opspilot.api.schemas import DetectionStatusResponse, MetricSeriesPoint, MetricSeriesResponse
from opspilot.api.security import require_api_key
from opspilot.api.services import APIServices
from opspilot.ingestion.schema import alerts, incidents, metrics

router = APIRouter(prefix="/v1", tags=["telemetry"], dependencies=[Depends(require_api_key)])


@router.get("/detection/status", response_model=DetectionStatusResponse)
def detection_status(services: APIServices = Depends(get_services)) -> DetectionStatusResponse:
    """Summarize the latest persisted detector output and ingestion freshness."""
    with services.engine.connect() as connection:
        last_alert = (
            connection.execute(select(alerts).order_by(desc(alerts.c.detected_at)).limit(1))
            .mappings()
            .first()
        )
        last_metric_at = connection.execute(select(func.max(metrics.c.ts))).scalar_one()
        open_count = int(
            connection.execute(
                select(func.count()).select_from(incidents).where(incidents.c.status == "open")
            ).scalar_one()
        )
    return DetectionStatusResponse(
        database="ok",
        detector=str(last_alert["detector"]) if last_alert else None,
        last_score=float(last_alert["score"]) if last_alert else None,
        last_threshold=float(last_alert["threshold"]) if last_alert else None,
        last_alert_at=last_alert["detected_at"] if last_alert else None,
        last_metric_at=last_metric_at,
        open_incidents=open_count,
    )


@router.get("/metrics/{service}", response_model=MetricSeriesResponse)
def metric_series(
    service: str,
    services: APIServices = Depends(get_services),
    minutes: Annotated[int, Query(ge=1, le=1_440)] = 60,
    points: Annotated[int, Query(ge=1, le=5_000)] = 500,
) -> MetricSeriesResponse:
    """Return recent normalized metrics grouped by timestamp for dashboard charts."""
    if service not in services.ingestion.services:
        raise HTTPException(status_code=404, detail="Service was not found")
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    statement = (
        select(metrics.c.ts, metrics.c.name, metrics.c.value)
        .where(metrics.c.service == service, metrics.c.ts >= cutoff)
        .order_by(desc(metrics.c.ts))
        .limit(points * 20)
    )
    with services.engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()
    grouped: dict[datetime, dict[str, float]] = {}
    for row in rows:
        grouped.setdefault(row["ts"], {})[str(row["name"])] = float(row["value"])
    ordered = sorted(grouped.items(), key=lambda item: item[0])[-points:]
    return MetricSeriesResponse(
        service=service,
        items=[MetricSeriesPoint(ts=timestamp, values=values) for timestamp, values in ordered],
    )
