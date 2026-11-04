"""Guarded demo-only simulator fault injection."""

import httpx
from fastapi import APIRouter, Depends, HTTPException

from opspilot.api.dependencies import get_services
from opspilot.api.schemas import FaultInjectionRequest
from opspilot.api.security import require_api_key
from opspilot.api.services import APIServices

router = APIRouter(
    prefix="/v1/simulator",
    tags=["simulator"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/faults")
def inject_fault(
    body: FaultInjectionRequest,
    services: APIServices = Depends(get_services),
) -> dict[str, object]:
    """Inject a validated fault only when the explicit demo feature flag is enabled."""
    if not services.settings.chaos_enabled:
        raise HTTPException(status_code=403, detail="Demo fault injection is disabled")
    service_url = services.ingestion.services.get(body.service)
    if service_url is None:
        raise HTTPException(status_code=404, detail="Service was not found")
    try:
        with httpx.Client(timeout=services.ingestion.request_timeout_seconds) as client:
            response = client.post(
                f"{service_url.rstrip('/')}/admin/fault",
                json={
                    "fault_type": body.fault_type.value,
                    "duration_seconds": body.duration_seconds,
                    "intensity": body.intensity,
                },
            )
            response.raise_for_status()
        return {
            "service": body.service,
            "fault_type": body.fault_type.value,
            "simulator": response.json(),
        }
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The simulator did not accept the fault request",
        ) from exc
