"""Payments API request and response models."""

from pydantic import BaseModel, Field


class ChargeRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(gt=0, le=10_000_000)


class ChargeResponse(BaseModel):
    order_id: str
    amount_cents: int
    status: str
    created_at: str


class FaultConfiguration(BaseModel):
    latency_ms: int = Field(default=0, ge=0, le=4_000)
    reject_charges: bool = False
