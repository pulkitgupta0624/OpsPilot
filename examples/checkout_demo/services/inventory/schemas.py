"""Inventory API request and response models."""

from pydantic import BaseModel, Field


class ReservationRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=20)


class ReservationResponse(BaseModel):
    order_id: str
    sku: str
    quantity: int
    status: str


class ProductResponse(BaseModel):
    sku: str
    name: str
    price_cents: int
    available: int
