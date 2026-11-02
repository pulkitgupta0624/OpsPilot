"""Retrying Prometheus text scraper for the simulator service adapters."""

import math
import re
from datetime import datetime

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from opspilot.core.clock import Clock, SystemClock
from opspilot.domain.models.telemetry import MetricSample

_SAMPLE_PATTERN = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eEInfNa]+)"
)


class MetricsScraper:
    """Collect normalized samples from one or more `/metrics` endpoints."""

    def __init__(
        self,
        service_urls: dict[str, str],
        *,
        timeout_seconds: float = 3.0,
        retry_attempts: int = 3,
        client: httpx.Client | None = None,
        clock: Clock | None = None,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be at least one")
        self._service_urls = dict(service_urls)
        self._retry_attempts = retry_attempts
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self._clock = clock or SystemClock()

    def scrape_all(self, *, run_id: str = "live") -> list[MetricSample]:
        """Scrape every configured service and return its numeric Prometheus samples."""
        samples: list[MetricSample] = []
        for service, base_url in self._service_urls.items():
            body = self._fetch(f"{base_url.rstrip('/')}/metrics")
            collected_at = self._clock.now()
            samples.extend(parse_prometheus_text(body, service, collected_at, run_id))
        return samples

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _fetch(self, url: str) -> str:
        retryer = Retrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=0.15, min=0.15, max=1.5),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        )

        def request() -> str:
            response = self._client.get(url)
            response.raise_for_status()
            return response.text

        return retryer(request)


def parse_prometheus_text(
    body: str,
    service: str,
    timestamp: datetime,
    run_id: str | None = None,
) -> list[MetricSample]:
    """Parse simple Prometheus exposition samples, ignoring comments and info labels."""
    samples: list[MetricSample] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_PATTERN.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name.endswith("_app_version_info"):
            continue
        raw_value = match.group("value")
        try:
            value = float(raw_value)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        normalized_name = name.removeprefix("opspilot_")
        samples.append(
            MetricSample(
                ts=timestamp,
                service=service,
                name=normalized_name,
                value=value,
                run_id=run_id,
            )
        )
    return samples

