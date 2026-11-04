"""Typer commands for starting and resuming persisted agent workflows."""

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy.exc import SQLAlchemyError

from opspilot.agents.config import load_agent_settings, load_remediation_policy
from opspilot.core.errors import OpsPilotError
from opspilot.ingestion.config import load_ingestion_settings
from opspilot.ingestion.database import build_database_engine
from opspilot.ingestion.stores.postgres_incidents import PostgresIncidentStore
from opspilot.knowledge.config import load_rag_settings

agent_app = typer.Typer(
    name="agent",
    help="Investigate persisted incidents and safely execute approved simulator actions.",
    no_args_is_help=True,
)


@agent_app.command("run")
def agent_run(
    incident_id: Annotated[
        str | None,
        typer.Option(help="Open incident ID; defaults to the latest open incident."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(help="Override provider in configs/agents.yaml."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="Override the configured model name.")] = None,
    dry_run: Annotated[
        bool,
        typer.Option(help="Show the plan without changing simulator state."),
    ] = False,
    index_dir: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Same persistent index directory used by `kb ingest`."),
    ] = None,
    agent_config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Agent budgets and provider settings."),
    ] = Path("configs/agents.yaml"),
    policy_config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Deterministic remediation policy."),
    ] = Path("configs/remediation_policy.yaml"),
    ingestion_config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Service URLs and database settings."),
    ] = Path("configs/ingestion.yaml"),
    rag_config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="RAG index settings."),
    ] = Path("configs/rag.yaml"),
    database_url: Annotated[
        str | None,
        typer.Option(help="Override the configured Postgres URL."),
    ] = None,
) -> None:
    """Start the agent for an open detected incident and pause for approval when required."""
    if provider is not None and provider not in {
        "fake",
        "openai",
        "anthropic",
        "google",
        "ollama",
    }:
        raise typer.BadParameter("Provider must be fake, openai, anthropic, google, or ollama.")
    settings = load_agent_settings(agent_config)
    overrides: dict[str, Any] = {}
    if provider is not None:
        overrides["provider"] = provider
    if model is not None:
        overrides["model"] = model
    if dry_run:
        overrides["dry_run"] = True
    settings = settings.model_copy(update=overrides)
    if settings.provider != "fake" and settings.model == "deterministic-fake":
        raise typer.BadParameter("Pass --model with the selected provider's current model ID.")

    engine = build_database_engine(database_url)
    try:
        record = PostgresIncidentStore(engine).load_open(incident_id)
        if record is None:
            raise typer.BadParameter(
                "No matching open incident with alerts was found. Start the Phase 3 "
                "monitor and trigger a fault first."
            )
        incident, alerts = record
        typer.echo(f"Starting agent for incident {incident.id} ({len(alerts)} alert(s)).")
        result = _invoke(
            settings=settings,
            policy_config=policy_config,
            ingestion_config=ingestion_config,
            rag_config=rag_config,
            index_dir=index_dir,
            incident=incident,
            alerts=alerts,
        )
        _display_result(result, incident.id)
        status = str(result.get("status", "escalated"))
        if status in {"resolved", "escalated"}:
            PostgresIncidentStore(engine).set_status(incident.id, status)
    except (OpsPilotError, OSError, ValueError, SQLAlchemyError) as exc:
        typer.echo(f"Agent run failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


@agent_app.command("approve")
def agent_approve(
    incident_id: str,
    approved: Annotated[
        bool,
        typer.Option("--approved/--rejected", help="Approve the displayed plan or reject it."),
    ],
    reviewer: Annotated[
        str,
        typer.Option(help="Human reviewer name."),
    ],
    comment: Annotated[str, typer.Option(help="Reason for the approval decision.")] = "",
    index_dir: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Same persistent index directory used by `kb ingest`."),
    ] = None,
    agent_config: Annotated[
        Path, typer.Option(exists=True, dir_okay=False)
    ] = Path("configs/agents.yaml"),
    policy_config: Annotated[
        Path, typer.Option(exists=True, dir_okay=False)
    ] = Path("configs/remediation_policy.yaml"),
    ingestion_config: Annotated[
        Path, typer.Option(exists=True, dir_okay=False)
    ] = Path("configs/ingestion.yaml"),
    rag_config: Annotated[
        Path, typer.Option(exists=True, dir_okay=False)
    ] = Path("configs/rag.yaml"),
    database_url: Annotated[
        str | None,
        typer.Option(help="Override the configured Postgres URL."),
    ] = None,
) -> None:
    """Resume one paused graph after recording a human approval or rejection."""
    settings = load_agent_settings(agent_config)
    engine = build_database_engine(database_url)
    try:
        with _runtime(
            settings=settings,
            policy_config=policy_config,
            ingestion_config=ingestion_config,
            rag_config=rag_config,
            index_dir=index_dir,
        ) as runtime:
            result = runtime.approve(
                incident_id,
                approved=approved,
                reviewer=reviewer,
                comment=comment,
            )
        _display_result(result, incident_id)
        status = str(result.get("status", "escalated"))
        if status in {"resolved", "escalated"}:
            PostgresIncidentStore(engine).set_status(incident_id, status)
    except (OpsPilotError, OSError, ValueError, SQLAlchemyError) as exc:
        typer.echo(f"Approval resume failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


def _invoke(
    *,
    settings: Any,
    policy_config: Path,
    ingestion_config: Path,
    rag_config: Path,
    index_dir: Path | None,
    incident: Any,
    alerts: list[Any],
) -> dict[str, Any]:
    with _runtime(
        settings=settings,
        policy_config=policy_config,
        ingestion_config=ingestion_config,
        rag_config=rag_config,
        index_dir=index_dir,
    ) as runtime:
        return runtime.run(incident, alerts)


def _runtime(
    *,
    settings: Any,
    policy_config: Path,
    ingestion_config: Path,
    rag_config: Path,
    index_dir: Path | None,
) -> Any:
    # LangGraph and its optional SQLite checkpointer are imported only for agent commands.
    from opspilot.agents.runner import AgentRuntime

    return AgentRuntime(
        settings=settings,
        policy=load_remediation_policy(policy_config),
        ingestion=load_ingestion_settings(ingestion_config),
        rag_settings=load_rag_settings(rag_config),
        rag_index_dir=index_dir,
    )


def _display_result(result: dict[str, Any], incident_id: str) -> None:
    interrupts = result.get("__interrupt__", [])
    if interrupts:
        payload = getattr(interrupts[0], "value", interrupts[0])
        typer.echo("Approval required for the current plan. It has not been executed.")
        if isinstance(payload, dict) and payload.get("previous_execution") is not None:
            typer.echo(
                "This incident has a previous action result and verification; review them below."
            )
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        typer.echo(
            "Resume with: uv run opspilot agent approve "
            f"{incident_id} --approved --reviewer \"Your Name\" --comment \"Reviewed\""
        )
        return

    status = str(result.get("status", "unknown"))
    typer.echo(f"Agent status: {status}")
    if result.get("plan"):
        typer.echo("Plan: " + json.dumps(result["plan"], ensure_ascii=False, default=str))
    if result.get("verification"):
        typer.echo(
            "Verification: "
            + json.dumps(result["verification"], ensure_ascii=False, default=str)
        )
    if result.get("report_path"):
        typer.echo(f"Post-mortem: {result['report_path']} (status: unverified)")
        typer.echo(f"Knowledge index refreshed: {bool(result.get('kb_indexed'))}")
        if result.get("kb_index_error"):
            typer.echo(f"Index refresh issue: {result['kb_index_error']}")
    if result.get("escalation_reason"):
        typer.echo(f"Escalation: {result['escalation_reason']}")
    if result.get("budget"):
        budget = result["budget"]
        typer.echo(
            "Budget: "
            f"tokens={budget.get('tokens', 0)}, cost_usd={budget.get('cost_usd', 0):.6f}, "
            f"tool_calls={result.get('tool_calls', 0)}"
        )
    typer.echo(f"Trace events: {len(result.get('trace', []))}")


