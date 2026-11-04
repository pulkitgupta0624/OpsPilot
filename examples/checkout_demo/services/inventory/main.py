"""HTTP API for product availability and stock reservations."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from common.observability import install_request_logging
from repository import InsufficientInventory, get_product, initialize, list_products, release, reserve
from schemas import ProductResponse, ReservationRequest, ReservationResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Checkout Inventory", version="0.1.0", lifespan=lifespan)
install_request_logging(app, "inventory")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "inventory"}


@app.get("/api/products", response_model=list[ProductResponse], tags=["catalog"])
def products() -> list[dict[str, object]]:
    return list_products()


@app.get("/api/products/{sku}", response_model=ProductResponse, tags=["catalog"])
def product(sku: str) -> dict[str, object]:
    result = get_product(sku)
    if result is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return result


@app.post("/internal/reservations", response_model=ReservationResponse, tags=["internal"])
def create_reservation(request: ReservationRequest) -> dict[str, object]:
    try:
        return reserve(request.order_id, request.sku, request.quantity)
    except InsufficientInventory as exc:
        raise HTTPException(status_code=409, detail="Insufficient inventory") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete(
    "/internal/reservations/{order_id}", response_model=ReservationResponse, tags=["internal"]
)
def release_reservation(order_id: str) -> dict[str, object]:
    result = release(order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return result
