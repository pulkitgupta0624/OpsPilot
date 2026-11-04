"""Public checkout API and minimal browser storefront."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from checkout import CheckoutError, CheckoutService
from common.observability import install_request_logging
from repository import get_order, initialize, list_orders
from schemas import CreateOrderRequest, OrderResponse

INVENTORY_BASE_URL = os.getenv("INVENTORY_BASE_URL", "http://inventory:8000")
PAYMENTS_BASE_URL = os.getenv("PAYMENTS_BASE_URL", "http://payments:8000")
CHECKOUT = CheckoutService(INVENTORY_BASE_URL, PAYMENTS_BASE_URL)
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Northstar Checkout", version="0.1.0", lifespan=lifespan)
install_request_logging(app, "orders")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "orders"}


@app.get("/ready", tags=["health"])
async def ready() -> dict[str, object]:
    dependencies = {
        "inventory": f"{INVENTORY_BASE_URL}/health",
        "payments": f"{PAYMENTS_BASE_URL}/health",
    }
    results: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0)) as client:
        for service, url in dependencies.items():
            try:
                response = await client.get(url)
                response.raise_for_status()
                results[service] = "ok"
            except (httpx.HTTPStatusError, httpx.RequestError):
                results[service] = "unavailable"
    is_ready = all(status == "ok" for status in results.values())
    if not is_ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "dependencies": results},
        )
    return {"status": "ready", "dependencies": results}


@app.get("/", include_in_schema=False)
def storefront() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/products", tags=["checkout"])
async def products() -> list[dict[str, object]]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{INVENTORY_BASE_URL}/api/products")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise HTTPException(status_code=503, detail="Inventory service is unavailable") from exc


@app.post("/api/orders", response_model=OrderResponse, status_code=201, tags=["checkout"])
async def create_order(
    payload: CreateOrderRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> dict[str, object]:
    try:
        return await CHECKOUT.place_order(
            sku=payload.sku,
            quantity=payload.quantity,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
    except CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/orders", response_model=list[OrderResponse], tags=["checkout"])
def orders() -> list[dict[str, object]]:
    return list_orders()


@app.get("/api/orders/{order_id}", response_model=OrderResponse, tags=["checkout"])
def order(order_id: str) -> dict[str, object]:
    result = get_order(order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return result
