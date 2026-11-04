"""Stable JSON error envelopes and request-correlation middleware."""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def install_error_handling(app: FastAPI) -> None:
    """Install the shared error envelope and X-Request-ID behavior."""

    @app.middleware("http")
    async def correlate_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID", "").strip()
        if not request_id or len(request_id) > 128 or any(ord(char) < 32 for char in request_id):
            request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code_by_status = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            502: "upstream_failure",
            503: "service_unavailable",
        }
        message = (
            exc.detail
            if isinstance(exc.detail, str)
            else "The request could not be completed."
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code_by_status.get(exc.status_code, "request_error"),
                    "message": message,
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", str(uuid4()))},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "One or more request fields are invalid.",
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", str(uuid4()))},
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, _exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("API database request failed")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "The database request could not be completed.",
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", str(uuid4()))},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API request error")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                }
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", str(uuid4()))},
        )
