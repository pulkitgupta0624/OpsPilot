"""FastAPI application factory for the OpsPilot product interface."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from opspilot.api.errors import install_error_handling
from opspilot.api.routers import evaluations, health, incidents, knowledge, metrics, simulator
from opspilot.api.services import APIServices
from opspilot.api.settings import APISettings


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Create the API with application-scoped adapters and OpenAPI metadata."""
    resolved_settings = settings or APISettings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = APIServices.create(resolved_settings)
        app.state.services = services
        try:
            yield
        finally:
            services.close()

    app = FastAPI(
        title="OpsPilot API",
        summary="Incident detection, investigation, approval, and recovery API.",
        description=(
            "The dashboard is a thin API client. Protected routes require `X-API-Key`; "
            "liveness and readiness are available at `/health` and `/ready`."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    install_error_handling(app)
    app.include_router(health.router)
    app.include_router(incidents.router)
    app.include_router(metrics.router)
    app.include_router(knowledge.router)
    app.include_router(simulator.router)
    app.include_router(evaluations.router)
    return app


app = create_app()
