"""API-key authentication for non-health HTTP routes."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from opspilot.api.dependencies import get_services
from opspilot.api.services import APIServices

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    supplied_key: Annotated[str | None, Security(_API_KEY_HEADER)],
    services: Annotated[APIServices, Depends(get_services)],
) -> None:
    """Reject protected requests when no server key is configured or it mismatches."""
    expected_key = services.settings.api_key
    if not expected_key:
        raise HTTPException(status_code=503, detail="API-key authentication is not configured")
    if not supplied_key or not secrets.compare_digest(supplied_key, expected_key):
        raise HTTPException(status_code=401, detail="A valid X-API-Key header is required")
