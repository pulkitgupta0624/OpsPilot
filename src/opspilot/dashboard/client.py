"""Small authenticated HTTP client shared by dashboard pages."""

from typing import Any

import httpx


class APIClientError(RuntimeError):
    """Safe, user-presentable API request failure."""


class OpsPilotAPIClient:
    """Thin client for the versioned OpsPilot REST API."""

    def __init__(self, base_url: str, api_key: str, *, timeout_seconds: float = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout_seconds

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", path, params=params or None)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers,
                timeout=self._timeout,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise APIClientError("Could not connect to the OpsPilot API.") from exc
        if response.is_error:
            try:
                envelope = response.json().get("error", {})
                message = str(envelope.get("message", "API request failed."))
            except (ValueError, AttributeError):
                message = "API request failed."
            raise APIClientError(message)
        payload = response.json()
        if not isinstance(payload, dict):
            raise APIClientError("The API returned an unexpected response.")
        return payload
