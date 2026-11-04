"""Orders API request and response models."""

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=20)


class OrderResponse(BaseModel):
    order_id: str
    idempotency_key: str
    sku: str
    product_name: str
    quantity: int
    unit_price_cents: int
    amount_cents: int
    status: str
    failure_reason: str | None
    created_at: str
