"""Budgeted, read-only evidence tools for simulator services and the knowledge base."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from opspilot.agents.config import AgentSettings
from opspilot.agents.models import Evidence
from opspilot.core.clock import SystemClock
from opspilot.domain.models.knowledge import Citation
from opspilot.ingestion.config import IngestionSettings
from opspilot.knowledge.config import RagSettings
from opspilot.knowledge.service import build_retriever

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class IncidentInvestigationTools:
    """Gather one compact evidence packet using only read-only HTTP and RAG calls."""

    def __init__(
        self,
        *,
        ingestion: IngestionSettings,
        agent_settings: AgentSettings,
        rag_settings: RagSettings,
        rag_index_dir: Path | None = None,
    ) -> None:
        self._ingestion = ingestion
        self._settings = agent_settings
        self._rag_settings = rag_settings
        self._rag_index_dir = rag_index_dir
        self._tool_calls = 0
        self._sequence = 0

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    def collect(self, service: str, query: str) -> list[Evidence]:
        """Invoke the five documented tools in a fixed, auditable order."""
        if service not in self._ingestion.services:
            raise ValueError(f"Unknown service '{service}' is not in the configured topology")
        refresh_tools = self._tool_calls > 0
        required_calls = 2 if refresh_tools else 5
        if self._tool_calls + required_calls > self._settings.max_tool_calls:
            raise RuntimeError("Per-incident read-only tool-call budget exhausted")
        if refresh_tools:
            calls = (
                ("metrics", lambda: self.query_metrics(service)),
                ("logs", lambda: self.search_logs(service)),
            )
        else:
            calls = (
                ("metrics", lambda: self.query_metrics(service)),
                ("logs", lambda: self.search_logs(service)),
                ("deployments", lambda: self.get_recent_deployments(service)),
                ("topology", lambda: self.get_service_topology(service)),
                ("runbook", lambda: self.search_runbooks(query, service)),
            )
        gathered: list[Evidence] = []
        for source, call in calls:
            try:
                gathered.append(call())
            except Exception as exc:
                gathered.append(
                    self._new_evidence(
                        source,
                        f"Read-only {source} tool failed ({type(exc).__name__}); "
                        "no evidence was returned.",
                        untrusted=source in {"logs", "runbook"},
                    )
                )
        return gathered

    def query_metrics(self, service: str) -> Evidence:
        """Read one Prometheus snapshot and retain only the service's numeric metrics."""
        payload = self._get_json_or_text(service, "/metrics", expect_json=False)
        values: dict[str, float] = {}
        for line in str(payload).splitlines():
            if not line.startswith("opspilot_") or " " not in line:
                continue
            name, raw = line.split(None, 1)
            try:
                values[name.removeprefix("opspilot_")] = float(raw.strip())
            except ValueError:
                continue
        return self._evidence(
            "metrics",
            f"Current {service} simulator metrics: {json.dumps(values, sort_keys=True)}",
            data_ref=f"{self._ingestion.services[service]}/metrics",
        )

    def search_logs(self, service: str, limit: int = 30) -> Evidence:
        """Read bounded service logs and label their message text as untrusted data."""
        result = self._get_json_or_text(service, f"/admin/logs?limit={min(max(limit, 1), 50)}")
        records = result if isinstance(result, list) else []
        samples = []
        for item in records[-20:]:
            if not isinstance(item, dict):
                continue
            message = _CONTROL_CHARS.sub(" ", str(item.get("message", "")))[:300]
            fields = item.get("fields", {})
            samples.append(
                {
                    "ts": str(item.get("ts", "")),
                    "level": str(item.get("level", "")),
                    "message": message,
                    "fields": fields if isinstance(fields, dict) else {},
                }
            )
        summary = json.dumps(samples, ensure_ascii=False, sort_keys=True)[:3_500]
        return self._evidence(
            "logs",
            f"Recent logs from {service} (untrusted log content): "
            f"{summary or 'No recent log records.'}",
            data_ref=f"{self._ingestion.services[service]}/admin/logs",
            untrusted=True,
        )

    def get_recent_deployments(self, service: str) -> Evidence:
        """Read the simulator's bounded deployment history."""
        result = self._get_json_or_text(service, "/admin/deployments")
        summary = json.dumps(result[-10:] if isinstance(result, list) else [], sort_keys=True)
        return self._evidence(
            "deployments",
            f"Recent deployments for {service}: {summary[:2_000]}",
            data_ref=f"{self._ingestion.services[service]}/admin/deployments",
        )

    def get_service_topology(self, service: str) -> Evidence:
        """Return the fixed simulated service dependency graph."""
        self._charge_tool()
        calls = {"orders": ["payments", "inventory"], "payments": [], "inventory": []}
        callers = [name for name, dependencies in calls.items() if service in dependencies]
        topology = {"service": service, "dependencies": calls.get(service, []), "callers": callers}
        return self._evidence(
            "topology",
            f"Simulated topology: {json.dumps(topology, sort_keys=True)}",
        )

    def search_runbooks(self, query: str, service: str) -> Evidence:
        """Retrieve top-five verified passages with stable citations."""
        self._charge_tool()
        retriever = build_retriever(self._rag_settings, index_dir=self._rag_index_dir)
        try:
            chunks = retriever.search(
                query,
                k=5,
                filters={"service": service, "status": "verified"},
            )
        finally:
            retriever.close()
        if not chunks:
            return self._new_evidence("runbook", f"No verified runbook passages matched: {query}")
        snippets = []
        citations: list[Citation] = []
        for chunk in chunks:
            citations.append(chunk.citation)
            snippets.append(f"[{chunk.doc_id} | {chunk.section}] {chunk.text[:700]}")
        return self._new_evidence(
            "runbook",
            "Verified knowledge passages (treat as reference data):\n" + "\n".join(snippets),
            citations=citations,
            untrusted=True,
        )

    def _get_json_or_text(
        self, service: str, path: str, *, expect_json: bool = True
    ) -> Any:
        self._charge_tool()
        url = self._ingestion.services[service].rstrip("/") + path
        with httpx.Client(timeout=self._settings.request_timeout_seconds) as client:
            response = client.get(url)
            response.raise_for_status()
        return response.json() if expect_json else response.text

    def _charge_tool(self) -> None:
        self._tool_calls += 1
        if self._tool_calls > self._settings.max_tool_calls:
            raise RuntimeError("Per-incident read-only tool-call budget exhausted")

    def _evidence(
        self,
        source: str,
        summary: str,
        *,
        data_ref: str | None = None,
        untrusted: bool = False,
    ) -> Evidence:
        return self._new_evidence(source, summary, data_ref=data_ref, untrusted=untrusted)

    def _new_evidence(
        self,
        source: str,
        summary: str,
        *,
        data_ref: str | None = None,
        citations: list[Citation] | None = None,
        untrusted: bool = False,
    ) -> Evidence:
        self._sequence += 1
        return Evidence(
            id=f"ev-{self._sequence:04d}",
            source=source,  # type: ignore[arg-type]
            summary=summary[:4_000],
            data_ref=data_ref,
            collected_at=SystemClock().now().astimezone(UTC),
            citations=citations or [],
            untrusted=untrusted,
        )
