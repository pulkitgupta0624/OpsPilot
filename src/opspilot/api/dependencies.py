"""FastAPI request dependencies."""

from fastapi import Request

from opspilot.api.services import APIServices


def get_services(request: Request) -> APIServices:
    """Return the application-scoped adapter bundle."""
    return request.app.state.services
