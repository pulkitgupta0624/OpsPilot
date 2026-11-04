"""Checkout saga coordinating inventory reservation and payment."""

from __future__ import annotations

import httpx

from common.observability import emit_event
from repository import (
    IdempotencyConflict,
    get_or_create_pending,
    get_order,
    update_status,
)


class CheckoutError(Exception):
    """A checkout request cannot be completed from the current service state."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class CheckoutService:
    def __init__(self, inventory_base_url: str, payments_base_url: str) -> None:
        self.inventory_base_url = inventory_base_url.rstrip("/")
        self.payments_base_url = payments_base_url.rstrip("/")

    async def place_order(
        self,
        *,
        sku: str,
        quantity: int,
        idempotency_key: str,
        request_id: str,
    ) -> dict[str, object]:
        headers = {"X-Request-ID": request_id}
        timeout = httpx.Timeout(5.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                product_response = await client.get(
                    f"{self.inventory_base_url}/api/products/{sku}", headers=headers
                )
                product_response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise CheckoutError("Product not found", status_code=404) from exc
                raise CheckoutError("Inventory service could not provide product details") from exc
            except httpx.RequestError as exc:
                raise CheckoutError("Inventory service is unavailable") from exc

            product = product_response.json()
            try:
                order = get_or_create_pending(
                    idempotency_key=idempotency_key,
                    sku=sku,
                    product_name=str(product["name"]),
                    quantity=quantity,
                    unit_price_cents=int(product["price_cents"]),
                )
            except IdempotencyConflict as exc:
                raise CheckoutError(str(exc), status_code=409) from exc

            if order["status"] != "pending":
                return order

            order_id = str(order["order_id"])
            reservation_created = False
            try:
                reservation_response = await client.post(
                    f"{self.inventory_base_url}/internal/reservations",
                    json={"order_id": order_id, "sku": sku, "quantity": quantity},
                    headers=headers,
                )
                reservation_response.raise_for_status()
                reservation_created = True

                charge_response = await client.post(
                    f"{self.payments_base_url}/internal/charges",
                    json={"order_id": order_id, "amount_cents": order["amount_cents"]},
                    headers=headers,
                )
                charge_response.raise_for_status()
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                reason = self._safe_failure_reason(exc)
                compensation_error = None
                if reservation_created:
                    try:
                        release_response = await client.delete(
                            f"{self.inventory_base_url}/internal/reservations/{order_id}",
                            headers=headers,
                        )
                        release_response.raise_for_status()
                    except (httpx.HTTPStatusError, httpx.RequestError):
                        compensation_error = "inventory reservation release failed"

                if compensation_error:
                    reason = f"{reason}; {compensation_error}"
                update_status(order_id, "failed", reason)
                emit_event(
                    "orders",
                    "checkout_failed",
                    request_id=request_id,
                    order_id=order_id,
                    failure_reason=reason,
                )
                failed_order = get_order(order_id)
                assert failed_order is not None
                return failed_order

        update_status(order_id, "confirmed")
        emit_event(
            "orders",
            "checkout_confirmed",
            request_id=request_id,
            order_id=order_id,
            amount_cents=order["amount_cents"],
        )
        confirmed_order = get_order(order_id)
        assert confirmed_order is not None
        return confirmed_order

    @staticmethod
    def _safe_failure_reason(exc: httpx.HTTPStatusError | httpx.RequestError) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                body = exc.response.json()
            except ValueError:
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            return str(detail or f"downstream service returned HTTP {exc.response.status_code}")
        return "downstream service is unavailable"
