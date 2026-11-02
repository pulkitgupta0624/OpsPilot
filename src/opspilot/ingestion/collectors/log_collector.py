"""Retrying JSON collector for the simulator's structured log endpoint."""

from typing import Any

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from opspilot.domain.models.telemetry import LogRecord


class LogCollector:
    """Fetch recent structured logs from configured service adapters."""

    def __init__(
        self,
        service_urls: dict[str, str],
        *,
        timeout_seconds: float = 3.0,
        retry_attempts: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be at least one")
        self._service_urls = dict(service_urls)
        self._retry_attempts = retry_attempts
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def collect_all(self, *, limit: int = 500) -> list[LogRecord]:
        """Fetch logs from every configured service, preserving source fields."""
        records: list[LogRecord] = []
        for service, base_url in self._service_urls.items():
            payload = self._fetch(f"{base_url.rstrip('/')}/admin/logs", limit)
            if not isinstance(payload, list):
                raise ValueError(f"Log endpoint for {service} did not return a JSON array")
            for item in payload:
                if not isinstance(item, dict):
                    continue
                normalized = {**item, "service": service}
                records.append(LogRecord.model_validate(normalized))
        return records

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _fetch(self, url: str, limit: int) -> Any:
        retryer = Retrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=0.15, min=0.15, max=1.5),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        )

        def request() -> Any:
            response = self._client.get(url, params={"limit": limit})
            response.raise_for_status()
            return response.json()

        return retryer(request)

