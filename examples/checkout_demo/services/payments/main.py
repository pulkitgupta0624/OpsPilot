"""HTTP API for idempotent demo charges and local fault controls."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from common.observability import install_request_logging
from repository import (
    create_charge,
    get_charge,
    get_fault_configuration,
    initialize,
    reset_fault_configuration,
    set_fault_configuration,
)
from schemas import ChargeRequest, ChargeResponse, FaultConfiguration


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Checkout Payments", version="0.1.0", lifespan=lifespan)
install_request_logging(app, "payments")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "payments"}


@app.post("/internal/charges", response_model=ChargeResponse, tags=["internal"])
async def charge(request: ChargeRequest) -> dict[str, object]:
    existing = get_charge(request.order_id)
    if existing:
        if existing["amount_cents"] != request.amount_cents:
            raise HTTPException(
                status_code=409,
                detail="Order was already charged for a different amount",
            )
        return existing

    fault = get_fault_configuration()
    latency_ms = int(fault["latency_ms"])
    if latency_ms:
        await asyncio.sleep(latency_ms / 1000)
    if fault["reject_charges"]:
        raise HTTPException(status_code=503, detail="Demo payment provider is rejecting charges")

    try:
        return create_charge(request.order_id, request.amount_cents)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/admin/faults", tags=["demo controls"])
def fault_status() -> dict[str, object]:
    return get_fault_configuration()


@app.put("/admin/faults", tags=["demo controls"])
def configure_fault(request: FaultConfiguration) -> dict[str, object]:
    return set_fault_configuration(request.latency_ms, request.reject_charges)


@app.delete("/admin/faults", tags=["demo controls"])
def clear_fault() -> dict[str, object]:
    return reset_fault_configuration()
