"""Persistence operations owned by the orders service."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from common.database import database

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/orders.sqlite3")


class IdempotencyConflict(Exception):
    """Raised when a key is reused for a different checkout request."""


def initialize() -> None:
    with database(DATABASE_PATH) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0),
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'failed')),
                failure_reason TEXT,
                created_at TEXT NOT NULL
            )"""
        )


def _to_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    return dict(row) if row else None


def get_or_create_pending(
    idempotency_key: str,
    sku: str,
    product_name: str,
    quantity: int,
    unit_price_cents: int,
) -> dict[str, object]:
    amount_cents = quantity * unit_price_cents
    with database(DATABASE_PATH) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM orders WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing:
            if existing["sku"] != sku or existing["quantity"] != quantity:
                raise IdempotencyConflict("Idempotency-Key was already used for a different order")
            return dict(existing)

        order_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        try:
            connection.execute(
                """INSERT INTO orders (
                    order_id, idempotency_key, sku, product_name, quantity,
                    unit_price_cents, amount_cents, status, failure_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?)""",
                (
                    order_id,
                    idempotency_key,
                    sku,
                    product_name,
                    quantity,
                    unit_price_cents,
                    amount_cents,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError:
            existing = connection.execute(
                "SELECT * FROM orders WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is None:
                raise
            if existing["sku"] != sku or existing["quantity"] != quantity:
                raise IdempotencyConflict(
                    "Idempotency-Key was already used for a different order"
                )
            return dict(existing)
        created = connection.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
    result = _to_dict(created)
    assert result is not None
    return result


def update_status(order_id: str, status: str, failure_reason: str | None = None) -> None:
    with database(DATABASE_PATH) as connection:
        connection.execute(
            "UPDATE orders SET status = ?, failure_reason = ? WHERE order_id = ?",
            (status, failure_reason, order_id),
        )


def get_order(order_id: str) -> dict[str, object] | None:
    with database(DATABASE_PATH) as connection:
        row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    return _to_dict(row)


def list_orders(limit: int = 50) -> list[dict[str, object]]:
    with database(DATABASE_PATH) as connection:
        rows = connection.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
