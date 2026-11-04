"""Public liveness and readiness endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from opspilot.api.dependencies import get_services
from opspilot.api.services import APIServices

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Report process liveness without touching external dependencies."""
    return {"status": "ok", "service": "opspilot-api"}


@router.get("/ready")
def ready(services: APIServices = Depends(get_services)) -> dict[str, str]:
    """Report readiness only when Postgres accepts a lightweight query."""
    try:
        with services.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is not ready") from exc
    return {"status": "ready", "database": "ok"}
