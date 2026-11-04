"""Composition root for API requests and adapter lifetimes."""

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from opspilot.agents.config import AgentSettings, load_agent_settings, load_remediation_policy
from opspilot.api.settings import APISettings
from opspilot.ingestion.config import IngestionSettings, load_ingestion_settings
from opspilot.ingestion.database import build_database_engine
from opspilot.knowledge.config import RagSettings, load_rag_settings
from opspilot.knowledge.retrieval.hybrid import HybridRetriever
from opspilot.knowledge.service import build_retriever


@dataclass
class APIServices:
    """Long-lived database and lazy retrieval adapters shared by HTTP routes."""

    settings: APISettings
    engine: Engine
    ingestion: IngestionSettings
    rag_settings: RagSettings
    _retriever: HybridRetriever | None = None
    _retriever_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def create(cls, settings: APISettings) -> "APIServices":
        ingestion = load_ingestion_settings(settings.ingestion_config)
        rag_settings = load_rag_settings(settings.rag_config)
        if settings.rag_index_dir is not None:
            rag_settings = rag_settings.model_copy(update={"index_dir": settings.rag_index_dir})
        return cls(
            settings=settings,
            engine=build_database_engine(ingestion.database_url),
            ingestion=ingestion,
            rag_settings=rag_settings,
        )

    def agent_settings(self) -> AgentSettings:
        """Load the same provider, budgets, and checkpoint paths used by the CLI."""
        return load_agent_settings(self.settings.agent_config)

    def open_agent_runtime(self) -> Any:
        """Create a short-lived workflow runtime for state reads or commands."""
        from opspilot.agents.runner import AgentRuntime

        settings = self.agent_settings()
        return AgentRuntime(
            settings=settings,
            policy=load_remediation_policy(self.settings.policy_config),
            ingestion=self.ingestion,
            rag_settings=self.rag_settings,
            rag_index_dir=self.settings.rag_index_dir,
        )

    def retriever(self) -> HybridRetriever:
        """Load the embedding and vector adapters on first knowledge-search request."""
        if self._retriever is None:
            with self._retriever_lock:
                if self._retriever is None:
                    self._retriever = build_retriever(
                        self.rag_settings,
                        index_dir=self.settings.rag_index_dir,
                    )
        return self._retriever

    def audit_events(self, incident_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Read bounded JSONL audit events for one incident."""
        path = self.agent_settings().audit_log
        if not path.is_file():
            return []
        events: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-20_000:]:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("incident_id") == incident_id:
                    events.append(event)
        except OSError:
            return []
        return events[-limit:]

    def latest_eval_reports(self) -> dict[str, Any]:
        """Return bounded Markdown/CSV excerpts from the latest local eval reports."""
        if not self.settings.eval_report_dir.is_dir():
            return {"reports": []}
        files = sorted(
            (
                path
                for pattern in ("*.md", "*.csv", "*.json")
                for path in self.settings.eval_report_dir.glob(pattern)
                if path.is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:20]
        reports = []
        for path in files:
            try:
                content = path.read_text(encoding="utf-8")[:40_000]
            except OSError:
                continue
            reports.append({"filename": path.name, "content": content})
        return {"reports": reports}

    def close(self) -> None:
        """Release API-owned handles at application shutdown."""
        if self._retriever is not None:
            self._retriever.close()
            self._retriever = None
        self.engine.dispose()
