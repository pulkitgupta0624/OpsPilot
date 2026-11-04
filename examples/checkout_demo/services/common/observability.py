"""Structured request logs and request-ID propagation for the demo services."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request


def emit_event(service: str, event: str, **fields: Any) -> None:
    """Write one JSON event to stdout for Docker log collection."""
    payload = {"service": service, "event": event, **fields}
    print(json.dumps(payload, separators=(",", ":"), default=str), flush=True)


def install_request_logging(app: FastAPI, service: str) -> None:
    """Add a request ID and a compact structured access log to an app."""

    @app.middleware("http")
    async def request_logging(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            emit_event(
                service,
                "http_request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        emit_event(
            service,
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response
