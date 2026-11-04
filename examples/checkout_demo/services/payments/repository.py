"""Persistence operations owned by the payments service."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from common.database import database

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/payments.sqlite3")


def initialize() -> None:
    with database(DATABASE_PATH) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS charges (
                order_id TEXT PRIMARY KEY,
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                status TEXT NOT NULL CHECK (status = 'charged'),
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS demo_faults (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms BETWEEN 0 AND 4000),
                reject_charges INTEGER NOT NULL DEFAULT 0 CHECK (reject_charges IN (0, 1))
            )"""
        )
        connection.execute(
            "INSERT OR IGNORE INTO demo_faults (singleton, latency_ms, reject_charges) VALUES (1, 0, 0)"
        )


def get_charge(order_id: str) -> dict[str, object] | None:
    with database(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT order_id, amount_cents, status, created_at FROM charges WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def create_charge(order_id: str, amount_cents: int) -> dict[str, object]:
    created_at = datetime.now(UTC).isoformat()
    with database(DATABASE_PATH) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO charges (order_id, amount_cents, status, created_at) VALUES (?, ?, 'charged', ?)",
            (order_id, amount_cents, created_at),
        )
        row = connection.execute(
            "SELECT order_id, amount_cents, status, created_at FROM charges WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if row["amount_cents"] != amount_cents:
            raise ValueError("Order was already charged for a different amount")
    return dict(row)


def get_fault_configuration() -> dict[str, object]:
    with database(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT latency_ms, reject_charges FROM demo_faults WHERE singleton = 1"
        ).fetchone()
    return {"latency_ms": row["latency_ms"], "reject_charges": bool(row["reject_charges"])}


def set_fault_configuration(latency_ms: int, reject_charges: bool) -> dict[str, object]:
    with database(DATABASE_PATH) as connection:
        connection.execute(
            "UPDATE demo_faults SET latency_ms = ?, reject_charges = ? WHERE singleton = 1",
            (latency_ms, int(reject_charges)),
        )
    return get_fault_configuration()


def reset_fault_configuration() -> dict[str, object]:
    return set_fault_configuration(latency_ms=0, reject_charges=False)
