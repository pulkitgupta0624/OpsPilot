"""LangGraph incident workflow with bounded investigation and human approval."""

import json
import logging
import operator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from opspilot.agents.audit import JsonlAuditLog
from opspilot.agents.config import AgentSettings, RemediationPolicy
from opspilot.agents.models import (
    ApprovalDecision,
    CriticVerdict,
    Evidence,
    Hypothesis,
    PolicyDecision,
    PostMortem,
    RemediationPlan,
)
from opspilot.agents.provider import JsonModel
from opspilot.agents.remediation.executor import SimulatorExecutor
from opspilot.agents.remediation.policy import evaluate_policy
from opspilot.agents.reporting import KnowledgeWriter
from opspilot.agents.tools import IncidentInvestigationTools
from opspilot.agents.triage import has_observed_fault_signal, root_cause_service_is_supported
from opspilot.agents.verification import SimulatorVerifier
from opspilot.core.errors import ConfigurationError
from opspilot.domain.enums import FaultType

logger = logging.getLogger(__name__)


class IncidentState(TypedDict, total=False):
    """JSON-serializable state persisted by LangGraph's SQLite checkpointer."""

    incident_id: str
    incident: dict[str, Any]
    alerts: list[dict[str, Any]]
    status: str
    severity: str
    affected_services: list[str]
    evidence: Annotated[list[dict[str, Any]], operator.add]
    hypotheses: list[dict[str, Any]]
    critic_verdict: dict[str, Any]
    investigation_round: int
    plan: dict[str, Any]
    policy: dict[str, Any]
    approval: dict[str, Any]
    approval_requested_at: str
    execution: dict[str, Any]
    verification: dict[str, Any]
    remediation_attempts: int
    failed_actions: list[str]
    report: dict[str, Any]
    report_path: str
    kb_indexed: bool
    kb_index_error: str | None
    escalation_reason: str
    tool_calls: int
    budget: dict[str, Any]
    trace: Annotated[list[dict[str, Any]], operator.add]


class BudgetExceeded(RuntimeError):
    """Raised when an agent run exceeds a configured hard limit."""

    def __init__(self, message: str, budget: dict[str, Any]) -> None:
        super().__init__(message)
        self.budget = budget


class AgentServices:
    """Injected adapters and hard limits shared by the graph's deterministic nodes."""

    def __init__(
        self,
        *,
        settings: AgentSettings,
        policy: RemediationPolicy,
        model: JsonModel,
        prompts_dir: Path,
        tools: IncidentInvestigationTools,
        executor: SimulatorExecutor,
        verifier: SimulatorVerifier,
        writer: KnowledgeWriter,
        audit: JsonlAuditLog,
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.model = model
        self.prompts_dir = prompts_dir
        self.tools = tools
        self.executor = executor
        self.verifier = verifier
        self.writer = writer
        self.audit = audit

    def invoke_model(
        self, task: str, context: dict[str, Any], budget: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Call a versioned prompt and update per-incident token/cost accounting."""
        self.check_budget(budget)
        prompt_path = self.prompts_dir / f"{task}.v1.md"
        if not prompt_path.is_file():
            raise ConfigurationError(f"Versioned prompt is missing: {prompt_path}")
        if int(budget.get("tokens", 0)) >= self.settings.max_tokens_per_incident:
            raise BudgetExceeded("Per-incident token budget is exhausted", dict(budget))
        if float(budget.get("cost_usd", 0.0)) >= self.settings.max_cost_usd_per_incident:
            raise BudgetExceeded("Per-incident cost budget is exhausted", dict(budget))
        prompt = prompt_path.read_text(encoding="utf-8")
        output, usage = self.model.invoke(task, prompt, context)
        updated = dict(budget)
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        total_tokens = int(updated.get("tokens", 0)) + input_tokens + output_tokens
        total_cost = float(updated.get("cost_usd", 0.0)) + (
            input_tokens * self.settings.input_cost_per_1k_tokens
            + output_tokens * self.settings.output_cost_per_1k_tokens
        ) / 1_000
        updated.update(
            {
                "tokens": total_tokens,
                "cost_usd": round(total_cost, 8),
                "last_model": usage.get("model", self.settings.model),
            }
        )
        if total_tokens > self.settings.max_tokens_per_incident:
            raise BudgetExceeded("Per-incident token budget exceeded", updated)
        if total_cost > self.settings.max_cost_usd_per_incident:
            raise BudgetExceeded("Per-incident cost budget exceeded", updated)
        return output, updated, prompt_path.name

    def check_budget(self, budget: dict[str, Any]) -> None:
        """Check elapsed active wall time, excluding time spent waiting for approval."""
        started_at = datetime.fromisoformat(str(budget["started_at"]))
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        active_elapsed = elapsed - float(budget.get("excluded_approval_seconds", 0.0))
        if active_elapsed > self.settings.max_wall_clock_seconds:
            raise BudgetExceeded("Per-incident active wall-clock budget exceeded", dict(budget))


def build_graph(services: AgentServices, *, checkpointer: Any) -> Any:
    """Compile the complete incident graph with a persistent interrupt checkpointer."""
    builder = StateGraph(IncidentState)

    builder.add_node("intake", _guarded("intake", services, _intake))
    builder.add_node("triage", _guarded("triage", services, _triage))
    builder.add_node("investigator", _guarded("investigator", services, _investigator))
    builder.add_node("critic", _guarded("critic", services, _critic))
    builder.add_node("planner", _guarded("planner", services, _planner))
    builder.add_node("policy_gate", _guarded("policy_gate", services, _policy_gate))
    builder.add_node("approval", _approval_node(services))
    builder.add_node("executor", _guarded("executor", services, _executor))
    builder.add_node("verifier", _guarded("verifier", services, _verifier))
    builder.add_node("reporter", _guarded("reporter", services, _reporter))
    builder.add_node("escalate", _guarded("escalate", services, _escalate))

    builder.add_edge(START, "intake")
    builder.add_conditional_edges(
        "intake",
        _route_status,
        {"continue": "triage", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "triage",
        _route_status,
        {"continue": "investigator", "escalate": "escalate"},
    )
    builder.add_edge("investigator", "critic")
    builder.add_conditional_edges(
        "critic",
        lambda state: _route_critic(state, services.settings),
        {"planner": "planner", "investigator": "investigator", "escalate": "escalate"},
    )
    builder.add_edge("planner", "policy_gate")
    builder.add_conditional_edges(
        "policy_gate",
        _route_policy,
        {"approval": "approval", "executor": "executor", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "approval",
        lambda state: _route_approval(state, services.settings),
        {"executor": "executor", "planner": "planner", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "executor",
        lambda state: (
            "escalate"
            if state.get("status") == "escalated"
            else "end"
            if state.get("execution", {}).get("dry_run")
            else "verify"
        ),
        {"end": END, "verify": "verifier", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "verifier",
        lambda state: _route_verification(state, services.settings),
        {"reporter": "reporter", "planner": "planner", "escalate": "escalate"},
    )
    builder.add_edge("reporter", END)
    builder.add_edge("escalate", END)
    return builder.compile(checkpointer=checkpointer)


def initial_state(incident: dict[str, Any], alerts: list[dict[str, Any]]) -> IncidentState:
    """Create an incident state with stable alert evidence and a fresh budget."""
    now = datetime.now(UTC)
    incident_id = str(incident["id"])
    initial_evidence: list[dict[str, Any]] = []
    for index, alert in enumerate(alerts, start=1):
        features = alert.get("suspect_features", [])
        details = alert.get("details", {})
        summary = (
            f"Alert {alert.get('id')} from {alert.get('detector')} on {alert.get('service')}; "
            f"source={alert.get('source')}; suspect features="
            f"{', '.join(str(item.get('name', '')) for item in features)}; "
            f"details={json.dumps(details, sort_keys=True, default=str)[:700]}"
        )
        initial_evidence.append(
            Evidence(
                id=f"alert-{index:04d}",
                source="alert",
                summary=summary,
                data_ref=str(alert.get("id", "")),
                collected_at=now,
                untrusted=alert.get("source") == "logs",
            ).model_dump(mode="json")
        )
    services = list(incident.get("affected_services", []))
    return IncidentState(
        incident_id=incident_id,
        incident=incident,
        alerts=alerts,
        status="started",
        severity=str(incident.get("severity", "unknown")),
        affected_services=services,
        evidence=initial_evidence,
        hypotheses=[],
        investigation_round=0,
        remediation_attempts=0,
        failed_actions=[],
        tool_calls=0,
        budget={
            "started_at": now.isoformat(),
            "excluded_approval_seconds": 0.0,
            "tokens": 0,
            "cost_usd": 0.0,
        },
        trace=[],
    )


def _guarded(name: str, services: AgentServices, fn: Any) -> Any:
    """Convert node errors and hard stops into a fail-closed escalation state."""
    def run(state: IncidentState) -> dict[str, Any]:
        try:
            services.check_budget(state.get("budget", {}))
            return fn(state, services)
        except BudgetExceeded as exc:
            return _failure_update(state, name, str(exc), budget=exc.budget)
        except Exception as exc:
            logger.exception(
                "agent node failed",
                extra={"node": name, "incident_id": state.get("incident_id")},
            )
            return _failure_update(state, name, f"{name} failed ({type(exc).__name__})")

    return run


def _failure_update(
    state: IncidentState, node: str, reason: str, *, budget: dict[str, Any] | None = None
) -> dict[str, Any]:
    event = _trace_event(node, "failed_closed", {"reason": reason})
    return {
        "status": "escalated",
        "escalation_reason": reason,
        "budget": budget or state.get("budget", {}),
        "trace": [event],
    }


def _intake(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    incident = state.get("incident", {})
    if not state.get("incident_id") or not state.get("alerts"):
        return {
            "status": "escalated",
            "escalation_reason": "Incident has no persisted alert evidence.",
        }
    if not state.get("affected_services"):
        return {"status": "escalated", "escalation_reason": "Incident has no affected service."}
    services.audit.append(
        str(state["incident_id"]),
        "intake",
        {"summary": incident.get("summary"), "affected_services": state["affected_services"]},
    )
    return {
        "status": "investigating",
        "trace": [_trace_event("intake", "complete", {"alert_count": len(state["alerts"])})],
    }


def _triage(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    context = {
        "incident": state["incident"],
        "alerts": state["alerts"],
        "evidence": state.get("evidence", []),
    }
    raw, budget, prompt_version = services.invoke_model("triage", context, state["budget"])
    hypotheses = [Hypothesis.model_validate(item) for item in raw.get("hypotheses", [])]
    known_ids = {str(item["id"]) for item in state.get("evidence", [])}
    if not hypotheses or any(
        not set(item.supporting_evidence_ids + item.contradicting_evidence_ids).issubset(known_ids)
        for item in hypotheses
    ):
        raise ValueError("Triage output is empty or cites evidence that was not supplied")
    if any(
        not root_cause_service_is_supported(
            item.root_cause_service, str(item.fault_type), state.get("alerts", [])
        )
        for item in hypotheses
    ):
        raise ValueError(
            "Triage selected a root-cause service without matching direct alert evidence"
        )
    affected = sorted(set(raw.get("affected_services", [])) & set(state["affected_services"]))
    if not affected:
        raise ValueError("Triage tried to expand the incident outside its affected services")
    event = _trace_event(
        "triage",
        "complete",
        {"severity": raw.get("severity"), "prompt_version": prompt_version},
    )
    event["details"].update(
        {
            "model": budget.get("last_model"),
            "tokens": budget.get("tokens"),
            "cost_usd": budget.get("cost_usd"),
        }
    )
    services.audit.append(str(state["incident_id"]), "triage", event["details"])
    return {
        "severity": str(raw.get("severity", state.get("severity", "unknown"))),
        "affected_services": affected,
        "hypotheses": [item.model_dump(mode="json") for item in hypotheses],
        "budget": budget,
        "status": "investigating",
        "trace": [event],
    }


def _investigator(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    hypotheses = state.get("hypotheses", [])
    primary = hypotheses[0] if hypotheses else {}
    service = str(primary.get("root_cause_service") or state["affected_services"][0])
    fault = str(primary.get("fault_type", "unknown"))
    features = sorted(
        {
            str(item.get("name"))
            for alert in state.get("alerts", [])
            for item in alert.get("suspect_features", [])
            if item.get("name")
        }
    )
    query = (
        f"{service} {fault} symptoms {' '.join(features)} "
        f"{state['incident'].get('summary', '')}"
    )
    tool_calls_before = services.tools.tool_calls
    evidence = services.tools.collect(service, query)
    evidence_dicts = [item.model_dump(mode="json") for item in evidence]
    tool_calls = max(int(state.get("tool_calls", 0)), services.tools.tool_calls)
    services.audit.append(
        str(state["incident_id"]),
        "investigation_tools",
        {
            "calls_this_round": services.tools.tool_calls - tool_calls_before,
            "evidence_ids": [item.id for item in evidence],
        },
    )
    event = _trace_event(
        "investigator",
        "evidence_collected",
        {
            "round": int(state.get("investigation_round", 0)) + 1,
            "evidence_ids": [item.id for item in evidence],
        },
    )
    return {
        "evidence": evidence_dicts,
        "tool_calls": tool_calls,
        "investigation_round": int(state.get("investigation_round", 0)) + 1,
        "trace": [event],
    }


def _critic(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    raw, budget, prompt_version = services.invoke_model(
        "critic",
        {"hypotheses": state.get("hypotheses", []), "evidence": state.get("evidence", [])},
        state["budget"],
    )
    verdict = CriticVerdict.model_validate(raw)
    known_ids = {str(item["id"]) for item in state.get("evidence", [])}
    cited_ids = (
        verdict.top_hypothesis.supporting_evidence_ids
        + verdict.top_hypothesis.contradicting_evidence_ids
        if verdict.top_hypothesis is not None
        else []
    )
    if verdict.top_hypothesis is not None and not set(cited_ids).issubset(known_ids):
        raise ValueError("Critic cited an unknown evidence ID")
    if verdict.top_hypothesis is not None and not root_cause_service_is_supported(
        verdict.top_hypothesis.root_cause_service,
        str(verdict.top_hypothesis.fault_type),
        state.get("alerts", []),
    ):
        raise ValueError(
            "Critic selected a root-cause service without matching direct alert evidence"
        )
    if (
        verdict.accept
        and verdict.top_hypothesis is not None
        and not has_observed_fault_signal(
            str(verdict.top_hypothesis.fault_type), state.get("evidence", [])
        )
    ):
        verdict = verdict.model_copy(
            update={
                "accept": False,
                "missing_evidence": list(
                    dict.fromkeys(
                        verdict.missing_evidence
                        + ["incident-specific metric, log, or deployment evidence"]
                    )
                ),
            }
        )
    accepted = verdict.accept and verdict.confidence >= services.settings.critic_accept_confidence
    if accepted and verdict.top_hypothesis is None:
        raise ValueError("Critic accepted a hypothesis without identifying it")
    if verdict.top_hypothesis is not None:
        hypotheses = [verdict.top_hypothesis.model_dump(mode="json")]
    else:
        hypotheses = state.get("hypotheses", [])
    verdict = verdict.model_copy(update={"accept": accepted})
    event = _trace_event(
        "critic",
        "accepted" if accepted else "needs_more_evidence",
        {"confidence": verdict.confidence, "prompt_version": prompt_version},
    )
    event["details"].update(
        {
            "model": budget.get("last_model"),
            "tokens": budget.get("tokens"),
            "cost_usd": budget.get("cost_usd"),
        }
    )
    services.audit.append(str(state["incident_id"]), "critic", event["details"])
    return {
        "critic_verdict": verdict.model_dump(mode="json"),
        "hypotheses": hypotheses,
        "budget": budget,
        "trace": [event],
    }


def _planner(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    verdict = state.get("critic_verdict", {})
    hypothesis = verdict.get("top_hypothesis")
    if not hypothesis:
        hypothesis = (state.get("hypotheses") or [{}])[0]
    raw, budget, prompt_version = services.invoke_model(
        "planner",
        {
            "hypothesis": hypothesis,
            "evidence": state.get("evidence", []),
            "failed_actions": state.get("failed_actions", []),
            "catalog": {
                fault.value: sorted(action.value for action in actions)
                for fault, actions in _catalog().items()
            },
        },
        state["budget"],
    )
    plan = RemediationPlan.model_validate(raw)
    known_evidence = {str(item["id"]) for item in state.get("evidence", [])}
    if not set(plan.evidence_ids).issubset(known_evidence):
        raise ValueError("Plan cited an unknown evidence ID")
    available_citations = {
        (str(citation.get("doc_id")), str(citation.get("section")))
        for item in state.get("evidence", [])
        for citation in item.get("citations", [])
    }
    if any((item.doc_id, item.section) not in available_citations for item in plan.citations):
        raise ValueError("Plan cited a knowledge passage that was not retrieved")
    if plan.target_service != str(hypothesis.get("root_cause_service", "")):
        raise ValueError("Plan target must match the evidence-supported root-cause service")
    event = _trace_event(
        "planner",
        "plan_created",
        {
            "action": plan.action.value,
            "target_service": plan.target_service,
            "prompt_version": prompt_version,
        },
    )
    event["details"].update(
        {
            "model": budget.get("last_model"),
            "tokens": budget.get("tokens"),
            "cost_usd": budget.get("cost_usd"),
        }
    )
    services.audit.append(str(state["incident_id"]), "plan", plan.model_dump(mode="json"))
    return {"plan": plan.model_dump(mode="json"), "budget": budget, "trace": [event]}


def _policy_gate(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    plan = RemediationPlan.model_validate(state["plan"])
    hypothesis = (state.get("hypotheses") or [{}])[0]
    fault_type = str(hypothesis.get("fault_type", "unknown"))
    decision = evaluate_policy(
        plan,
        fault_type=fault_type,
        affected_services=state.get("affected_services", []),
        confidence=float((state.get("critic_verdict") or {}).get("confidence", 0.0)),
        policy=services.policy,
        failed_actions=state.get("failed_actions", []),
        remediation_attempts=int(state.get("remediation_attempts", 0)),
        evidence=state.get("evidence", []),
        cooldown_active=services.audit.cooldown_active(
            plan.target_service,
            plan.action.value,
            services.policy.defaults.cooldown_seconds_per_service_action,
        ),
    )
    event = _trace_event(
        "policy_gate",
        "blocked"
        if decision.violations
        else "approval_required"
        if decision.approval_required
        else "auto_allowed",
        decision.model_dump(mode="json"),
    )
    services.audit.append(
        str(state["incident_id"]),
        "policy_decision",
        decision.model_dump(mode="json"),
    )
    update: dict[str, Any] = {"policy": decision.model_dump(mode="json"), "trace": [event]}
    if decision.violations:
        update.update(status="escalated", escalation_reason="; ".join(decision.violations))
    elif decision.approval_required:
        update.update(
            status="waiting_approval",
            approval_requested_at=datetime.now(UTC).isoformat(),
            escalation_reason="",
        )
    else:
        update.update(status="executing", escalation_reason="")
    return update


def _approval_node(services: AgentServices) -> Any:
    """Pause before any side effect and resume from the same incident thread."""
    def approval(state: IncidentState) -> dict[str, Any]:
        requested_at = str(state.get("approval_requested_at") or datetime.now(UTC).isoformat())
        payload = {
            "incident_id": state["incident_id"],
            "plan": state.get("plan"),
            "risk": (state.get("policy") or {}).get("risk"),
            "evidence": [
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "citations": item.get("citations", []),
                }
                for item in state.get("evidence", [])
            ],
            "requested_at": requested_at,
        }
        if state.get("execution") is not None:
            payload["previous_execution"] = state["execution"]
        if state.get("verification") is not None:
            payload["previous_verification"] = state["verification"]
        resumed = interrupt(payload)
        raw = dict(resumed) if isinstance(resumed, dict) else {"approved": False}
        raw.setdefault("decided_at", datetime.now(UTC).isoformat())
        raw.setdefault("reviewer", "unknown")
        raw.setdefault("comment", "")
        try:
            decision = ApprovalDecision.model_validate(raw)
        except ValueError:
            return {
                "status": "escalated",
                "escalation_reason": "Approval input was invalid; no action was executed.",
            }
        elapsed = max(
            0.0,
            (decision.decided_at - datetime.fromisoformat(requested_at)).total_seconds(),
        )
        timed_out = elapsed > services.settings.approval_timeout_seconds
        if timed_out:
            decision = decision.model_copy(
                update={
                    "approved": False,
                    "comment": "Approval arrived after the configured timeout.",
                }
            )
        budget = dict(state.get("budget", {}))
        budget["excluded_approval_seconds"] = float(
            budget.get("excluded_approval_seconds", 0.0)
        ) + elapsed
        services.audit.append(
            str(state["incident_id"]),
            "approval_decision",
            {**decision.model_dump(mode="json"), "timed_out": timed_out},
        )
        event = _trace_event(
            "approval",
            "approved" if decision.approved else "rejected",
            decision.model_dump(mode="json"),
        )
        if decision.approved:
            return {
                "approval": decision.model_dump(mode="json"),
                "status": "executing",
                "budget": budget,
                "trace": [event],
            }

        attempts = int(state.get("remediation_attempts", 0)) + 1
        failed = list(state.get("failed_actions", []))
        if state.get("plan", {}).get("action") not in failed:
            failed.append(str(state.get("plan", {}).get("action")))
        return {
            "approval": decision.model_dump(mode="json"),
            "status": (
                "replanning"
                if attempts < services.settings.max_remediation_attempts and not timed_out
                else "escalated"
            ),
            "escalation_reason": "Plan rejected or approval timed out.",
            "remediation_attempts": attempts,
            "failed_actions": failed,
            "budget": budget,
            "trace": [event],
        }

    return approval


def _executor(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    plan = RemediationPlan.model_validate(state["plan"])
    policy = PolicyDecision.model_validate(state["policy"])
    if policy.approval_required and not (state.get("approval") or {}).get("approved"):
        return {
            "status": "escalated",
            "escalation_reason": "Executor refused to run without approval.",
        }
    result = services.executor.execute(plan)
    actor = str((state.get("approval") or {}).get("reviewer", "policy"))
    services.audit.append(
        str(state["incident_id"]),
        "action_execution",
        {"actor": actor, **result.model_dump(mode="json")},
    )
    event = _trace_event(
        "executor",
        "dry_run" if result.dry_run else "completed",
        result.model_dump(mode="json"),
    )
    update: dict[str, Any] = {
        "execution": result.model_dump(mode="json"),
        "remediation_attempts": int(state.get("remediation_attempts", 0))
        + (0 if result.dry_run else 1),
        "status": "dry_run_complete" if result.dry_run else "verifying",
        "trace": [event],
    }
    if not result.accepted and not result.dry_run:
        update.update(
            status="escalated",
            escalation_reason="Simulator rejected or could not apply the action.",
        )
    return update


def _verifier(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    plan = RemediationPlan.model_validate(state["plan"])
    result = services.verifier.verify(plan)
    event = _trace_event(
        "verifier",
        "recovered" if result.recovered else "not_recovered",
        result.model_dump(mode="json"),
    )
    services.audit.append(str(state["incident_id"]), "verification", result.model_dump(mode="json"))
    failed_actions = list(state.get("failed_actions", []))
    if not result.recovered and plan.action.value not in failed_actions:
        failed_actions.append(plan.action.value)
    return {
        "verification": result.model_dump(mode="json"),
        "failed_actions": failed_actions,
        "status": "resolved" if result.recovered else "replanning",
        "trace": [event],
    }


def _reporter(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    hypothesis = (state.get("hypotheses") or [{}])[0]
    context = {
        "incident": state["incident"],
        "hypothesis": hypothesis,
        "plan": state.get("plan", {}),
        "verification": state.get("verification", {}),
        "evidence": state.get("evidence", []),
    }
    try:
        raw, budget, prompt_version = services.invoke_model("reporter", context, state["budget"])
        report = PostMortem.model_validate(raw)
    except Exception as exc:
        logger.warning("post-mortem model fallback", extra={"error_type": type(exc).__name__})
        budget = state.get("budget", {})
        report = PostMortem(
            summary=(
                f"Resolved {hypothesis.get('fault_type', 'unknown')} incident on "
                f"{hypothesis.get('root_cause_service', 'service')}"
            ),
            root_cause=str(
                hypothesis.get("rationale", "Root cause identified from incident evidence.")
            ),
            impact="The simulated service had anomalous telemetry before remediation.",
            resolution=str(state.get("verification", {}).get("message", "Recovery was verified.")),
            lessons=["Review the attached evidence and verify this generated draft before reuse."],
            citations=[],
        )
        prompt_version = "template-fallback"
    allowed_citations = {
        (str(citation.get("doc_id")), str(citation.get("section")))
        for item in state.get("evidence", [])
        for citation in item.get("citations", [])
    }
    citations = [
        citation
        for citation in report.citations
        if (citation.doc_id, citation.section) in allowed_citations
    ]
    report = report.model_copy(update={"citations": citations})
    service = str(hypothesis.get("root_cause_service", state["affected_services"][0]))
    fault_type = str(hypothesis.get("fault_type", "unknown"))
    path, indexed, index_error = services.writer.write(
        incident_id=str(state["incident_id"]),
        service=service,
        fault_type=fault_type,
        severity=state.get("severity", "unknown"),
        report=report,
    )
    services.audit.append(
        str(state["incident_id"]),
        "postmortem_written",
        {"path": str(path), "indexed": indexed is not None, "index_error": index_error},
    )
    event = _trace_event(
        "reporter",
        "complete",
        {"path": str(path), "indexed": indexed is not None, "prompt_version": prompt_version},
    )
    event["details"].update(
        {
            "model": budget.get("last_model"),
            "tokens": budget.get("tokens"),
            "cost_usd": budget.get("cost_usd"),
        }
    )
    return {
        "report": report.model_dump(mode="json"),
        "report_path": str(path),
        "kb_indexed": indexed is not None,
        "kb_index_error": index_error,
        "budget": budget,
        "status": "resolved",
        "trace": [event],
    }


def _escalate(state: IncidentState, services: AgentServices) -> dict[str, Any]:
    reason = state.get(
        "escalation_reason",
        "Investigation ended without a safe verified resolution.",
    )
    services.audit.append(str(state.get("incident_id", "unknown")), "escalated", {"reason": reason})
    return {
        "status": "escalated",
        "escalation_reason": reason,
        "trace": [_trace_event("escalate", "human_action_required", {"reason": reason})],
    }


def _route_status(state: IncidentState) -> str:
    return "escalate" if state.get("status") == "escalated" else "continue"


def _route_critic(state: IncidentState, settings: AgentSettings) -> str:
    if state.get("status") == "escalated":
        return "escalate"
    verdict = state.get("critic_verdict", {})
    if verdict.get("accept") and float(verdict.get("confidence", 0.0)) >= (
        settings.critic_accept_confidence
    ):
        return "planner"
    if int(state.get("investigation_round", 0)) < settings.max_investigation_rounds:
        return "investigator"
    return "escalate"


def _route_policy(state: IncidentState) -> str:
    if state.get("status") == "escalated" or (state.get("policy") or {}).get("violations"):
        return "escalate"
    return "approval" if (state.get("policy") or {}).get("approval_required") else "executor"


def _route_approval(state: IncidentState, settings: AgentSettings) -> str:
    approval = state.get("approval", {})
    if approval.get("approved"):
        return "executor"
    if state.get("status") == "replanning" and int(
        state.get("remediation_attempts", 0)
    ) < settings.max_remediation_attempts:
        return "planner"
    return "escalate"


def _route_verification(state: IncidentState, settings: AgentSettings) -> str:
    if (state.get("verification") or {}).get("recovered"):
        return "reporter"
    if int(state.get("remediation_attempts", 0)) < settings.max_remediation_attempts:
        return "planner"
    return "escalate"


def _trace_event(node: str, event: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": datetime.now(UTC).isoformat(),
        "node": node,
        "event": event,
        "details": json.loads(json.dumps(details, default=str)),
    }


def _catalog() -> dict[FaultType, frozenset[Any]]:
    from opspilot.agents.remediation.policy import ACTION_CATALOG

    return ACTION_CATALOG
