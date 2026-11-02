"""Daily seasonality, weekday effects, Poisson traffic, and normal bursts."""

from datetime import datetime
from typing import Protocol

import numpy as np

from opspilot.core.config import SimulationConfig


class RandomGenerator(Protocol):
    """Subset of NumPy's Generator used by the load profile."""

    def poisson(self, lam: float, size: int | None = None) -> int | np.ndarray: ...

    def random(self, size: int | None = None) -> float | np.ndarray: ...

    def uniform(self, low: float, high: float, size: int | None = None) -> float | np.ndarray: ...


class DailyLoadProfile:
    """Generate deterministic-by-seed service request rates."""

    def __init__(
        self,
        config: SimulationConfig,
        rng: RandomGenerator,
        *,
        burst_probability: float = 0.012,
    ) -> None:
        self._config = config
        self._rng = rng
        self._burst_probability = burst_probability

    def sample(self, timestamp: datetime) -> dict[str, float]:
        """Return requests/s for each service at ``timestamp``."""
        hour_angle = 2.0 * np.pi * (timestamp.hour + timestamp.minute / 60.0) / 24.0
        daily_factor = 0.68 + 0.32 * (0.5 + 0.5 * np.sin(hour_angle - np.pi / 2.0))
        weekday_factor = 1.0 if timestamp.weekday() < 5 else 0.78
        factor = daily_factor * weekday_factor
        rates: dict[str, float] = {}
        for service, service_config in self._config.services.items():
            expected = service_config.base_request_rate_per_s * factor
            observed = float(self._rng.poisson(expected))
            if float(self._rng.random()) < self._burst_probability:
                observed *= float(self._rng.uniform(1.5, 2.6))
            rates[service] = max(0.0, observed)
        return rates

