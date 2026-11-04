"""Runtime composition for persistent, interruptible incident workflows."""

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from opspilot.agents.audit import JsonlAuditLog
from opspilot.agents.config import AgentSettings, RemediationPolicy
from opspilot.agents.graph import AgentServices, build_graph, initial_state
from opspilot.agents.provider import JsonModel, build_provider
from opspilot.agents.remediation.executor import SimulatorExecutor
from opspilot.agents.reporting import KnowledgeWriter
from opspilot.agents.tools import IncidentInvestigationTools
from opspilot.agents.verification import SimulatorVerifier
from opspilot.domain.models.incident import Alert, Incident
from opspilot.ingestion.config import IngestionSettings
from opspilot.knowledge.config import RagSettings


class AgentRuntime:
    """Own the SQLite checkpointer and injected ports for one CLI invocation."""

    def __init__(
        self,
        *,
        settings: AgentSettings,
        policy: RemediationPolicy,
        ingestion: IngestionSettings,
        rag_settings: RagSettings,
        knowledge_source: Path = Path("knowledge_base"),
        rag_index_dir: Path | None = None,
    ) -> None:
        if settings.provider in {"openai", "anthropic", "google"} and (
            settings.input_cost_per_1k_tokens <= 0 or settings.output_cost_per_1k_tokens <= 0
        ):
            raise ValueError(
                "Set current input_cost_per_1k_tokens and output_cost_per_1k_tokens in "
                "configs/agents.yaml before using a hosted provider."
            )
        self._settings = settings
        self._connection: sqlite3.Connection | None = None
        checkpoint_path = settings.state_db
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._connection)
        self._checkpointer.setup()

        tools = IncidentInvestigationTools(
            ingestion=ingestion,
            agent_settings=settings,
            rag_settings=rag_settings,
            rag_index_dir=rag_index_dir,
        )
        provider = build_provider(settings)
        services = AgentServices(
            settings=settings,
            policy=policy,
            model=JsonModel(provider),
            prompts_dir=Path(__file__).parent / "prompts",
            tools=tools,
            executor=SimulatorExecutor(
                ingestion.services,
                timeout_seconds=settings.request_timeout_seconds,
                dry_run=settings.dry_run,
            ),
            verifier=SimulatorVerifier(ingestion, settings),
            writer=KnowledgeWriter(
                source_dir=knowledge_source,
                rag_settings=rag_settings,
                index_dir=rag_index_dir,
            ),
            audit=JsonlAuditLog(settings.audit_log),
        )
        self._graph = build_graph(services, checkpointer=self._checkpointer)

    def run(self, incident: Incident, alerts: list[Alert]) -> dict[str, Any]:
        """Start one incident workflow, checkpointed under its incident ID."""
        state = initial_state(
            incident.model_dump(mode="json"),
            [alert.model_dump(mode="json") for alert in alerts],
        )
        return self._graph.invoke(state, self._config(incident.id))

    def approve(
        self,
        incident_id: str,
        *,
        approved: bool,
        reviewer: str,
        comment: str,
    ) -> dict[str, Any]:
        """Resume a pending human approval on its original incident thread."""
        snapshot = self._graph.get_state(self._config(incident_id))
        if not snapshot.values or snapshot.values.get("status") != "waiting_approval":
            raise ValueError(f"Incident '{incident_id}' has no pending approval checkpoint")
        return self._graph.invoke(
            Command(
                resume={
                    "approved": approved,
                    "reviewer": reviewer,
                    "comment": comment,
                }
            ),
            self._config(incident_id),
        )

    def state(self, incident_id: str) -> dict[str, Any]:
        """Read the latest persisted graph state for an incident thread."""
        snapshot = self._graph.get_state(self._config(incident_id))
        return dict(snapshot.values or {})

    def close(self) -> None:
        """Close the SQLite connection after graph invocations are complete."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "AgentRuntime":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _config(incident_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": incident_id},
            "recursion_limit": 80,
        }
