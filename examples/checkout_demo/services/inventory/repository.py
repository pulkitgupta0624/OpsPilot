"""Persistence operations owned by the inventory service."""

from __future__ import annotations

import os
import sqlite3

from common.database import database

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/inventory.sqlite3")
SEED_PRODUCTS = (
    ("coffee-beans", "Northstar Coffee Beans", 1299, 25),
    ("travel-mug", "Northstar Travel Mug", 1899, 15),
)


class InsufficientInventory(Exception):
    """Raised when a product is missing or does not have enough stock."""


def initialize() -> None:
    with database(DATABASE_PATH) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK (price_cents > 0),
                available INTEGER NOT NULL CHECK (available >= 0)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS reservations (
                order_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL REFERENCES products(sku),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                status TEXT NOT NULL CHECK (status IN ('reserved', 'released'))
            )"""
        )
        connection.executemany(
            "INSERT OR IGNORE INTO products (sku, name, price_cents, available) VALUES (?, ?, ?, ?)",
            SEED_PRODUCTS,
        )


def list_products() -> list[dict[str, object]]:
    with database(DATABASE_PATH) as connection:
        rows = connection.execute(
            "SELECT sku, name, price_cents, available FROM products ORDER BY sku"
        ).fetchall()
    return [dict(row) for row in rows]


def get_product(sku: str) -> dict[str, object] | None:
    with database(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT sku, name, price_cents, available FROM products WHERE sku = ?", (sku,)
        ).fetchone()
    return dict(row) if row else None


def reserve(order_id: str, sku: str, quantity: int) -> dict[str, object]:
    with database(DATABASE_PATH) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT order_id, sku, quantity, status FROM reservations WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if existing:
            if existing["sku"] != sku or existing["quantity"] != quantity:
                raise ValueError("Order already has a different reservation")
            if existing["status"] == "reserved":
                return dict(existing)
            raise ValueError("Reservation has already been released")

        product = connection.execute(
            "SELECT available FROM products WHERE sku = ?", (sku,)
        ).fetchone()
        if product is None or product["available"] < quantity:
            raise InsufficientInventory(sku)

        connection.execute(
            "UPDATE products SET available = available - ? WHERE sku = ?", (quantity, sku)
        )
        connection.execute(
            "INSERT INTO reservations (order_id, sku, quantity, status) VALUES (?, ?, ?, 'reserved')",
            (order_id, sku, quantity),
        )
    return {"order_id": order_id, "sku": sku, "quantity": quantity, "status": "reserved"}


def release(order_id: str) -> dict[str, object] | None:
    with database(DATABASE_PATH) as connection:
        connection.execute("BEGIN IMMEDIATE")
        reservation = connection.execute(
            "SELECT order_id, sku, quantity, status FROM reservations WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if reservation is None:
            return None
        if reservation["status"] == "reserved":
            connection.execute(
                "UPDATE products SET available = available + ? WHERE sku = ?",
                (reservation["quantity"], reservation["sku"]),
            )
            connection.execute(
                "UPDATE reservations SET status = 'released' WHERE order_id = ?", (order_id,)
            )
        return dict(
            connection.execute(
                "SELECT order_id, sku, quantity, status FROM reservations WHERE order_id = ?",
                (order_id,),
            ).fetchone()
        )
