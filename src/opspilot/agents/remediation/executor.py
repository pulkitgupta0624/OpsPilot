"""Dry-run and simulator-only execution for validated action-catalog entries."""

from datetime import UTC, datetime

import httpx

from opspilot.agents.models import ActionResult, RemediationPlan


class SimulatorExecutor:
    """Send only fixed action names to configured OpsPilot simulator adapters."""

    def __init__(
        self,
        service_urls: dict[str, str],
        *,
        timeout_seconds: float,
        dry_run: bool,
    ) -> None:
        self._service_urls = service_urls
        self._timeout_seconds = timeout_seconds
        self._dry_run = dry_run

    def execute(self, plan: RemediationPlan) -> ActionResult:
        """Apply a catalog action to the named simulated service, or report dry-run intent."""
        if plan.target_service not in self._service_urls:
            return ActionResult(
                action=plan.action,
                service=plan.target_service,
                accepted=False,
                dry_run=self._dry_run,
                message="Target is not a configured simulator service.",
                completed_at=datetime.now(UTC),
            )
        if self._dry_run:
            return ActionResult(
                action=plan.action,
                service=plan.target_service,
                accepted=True,
                dry_run=True,
                message=(
                    f"Would POST the whitelisted '{plan.action.value}' action to the simulator."
                ),
                completed_at=datetime.now(UTC),
            )

        # The destination comes only from local ingestion configuration; the model supplies no URL.
        url = self._service_urls[plan.target_service].rstrip("/")
        endpoint = f"{url}/admin/action/{plan.action.value}"
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(endpoint)
                response.raise_for_status()
                payload = response.json()
            accepted = payload.get("accepted") is True
            message = (
                "Simulator accepted the remediation."
                if accepted
                else "Simulator rejected the remediation."
            )
        except (httpx.HTTPError, ValueError):
            accepted = False
            message = "Simulator action failed; details are available in the local application log."
        return ActionResult(
            action=plan.action,
            service=plan.target_service,
            accepted=accepted,
            dry_run=False,
            message=message,
            completed_at=datetime.now(UTC),
        )
