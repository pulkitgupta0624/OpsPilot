"""Stable identifiers for reproducible simulation outputs."""

from datetime import datetime
from hashlib import sha256
from typing import Protocol


class ByteGenerator(Protocol):
    """Small structural interface for seeded random byte generation."""

    def bytes(self, length: int) -> bytes: ...


def simulation_run_id(seed: int, started_at: datetime) -> str:
    """Return the same run identifier for the same seed and start timestamp."""
    material = f"{seed}:{started_at.isoformat()}".encode("utf-8")
    return f"run-{sha256(material).hexdigest()[:12]}"


def trace_id(rng: ByteGenerator) -> str:
    """Create a trace identifier from the simulation's seeded random generator."""
    return rng.bytes(8).hex()

