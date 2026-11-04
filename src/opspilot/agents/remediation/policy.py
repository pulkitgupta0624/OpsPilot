"""Pure, deterministic validation and risk decisions for remediation plans."""

from opspilot.agents.config import RemediationPolicy
from opspilot.agents.models import PolicyDecision, RemediationPlan
from opspilot.domain.enums import ActionType, FaultType

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

# These mappings match the simulator fault catalog's documented recoveries.
ACTION_CATALOG: dict[FaultType, frozenset[ActionType]] = {
    FaultType.MEMORY_LEAK: frozenset({ActionType.RESTART_SERVICE, ActionType.SCALE_OUT}),
    FaultType.DB_POOL_EXHAUSTION: frozenset(
        {ActionType.INCREASE_DB_POOL, ActionType.RESTART_SERVICE}
    ),
    FaultType.SLOW_DEPENDENCY: frozenset({ActionType.ENABLE_CIRCUIT_BREAKER}),
    FaultType.BAD_DEPLOYMENT: frozenset({ActionType.ROLLBACK_DEPLOYMENT}),
    FaultType.DISK_FULL: frozenset({ActionType.CLEAR_DISK, ActionType.CLEAR_DISK_SPACE}),
}


def evaluate_policy(
    plan: RemediationPlan,
    *,
    fault_type: FaultType | str,
    affected_services: list[str],
    confidence: float,
    policy: RemediationPolicy,
    failed_actions: list[str],
    remediation_attempts: int,
    evidence: list[dict[str, object]] | None = None,
    cooldown_active: bool = False,
) -> PolicyDecision:
    """Fail closed on unsupported actions, targets, parameters, and exhausted budgets."""
    violations: list[str] = []
    rationale: list[str] = []
    try:
        known_fault = FaultType(fault_type)
    except ValueError:
        known_fault = None

    if known_fault is None or plan.action not in ACTION_CATALOG.get(known_fault, frozenset()):
        violations.append(
            "Action is not in the simulator's remediation catalog for this fault type"
        )
    if plan.target_service not in affected_services:
        violations.append("Target service is outside the incident's affected-service set")
    if plan.params:
        violations.append("This simulator adapter does not accept action parameters")
    if plan.action.value not in policy.actions:
        violations.append("Action has no risk declaration in remediation_policy.yaml")
        risk = "high"
    else:
        risk = policy.actions[plan.action.value]
    if plan.action.value in failed_actions:
        violations.append("The proposed action already failed during this incident")
    if cooldown_active:
        violations.append("The service/action cooldown is still active")
    if plan.action == ActionType.ROLLBACK_DEPLOYMENT:
        deployment_evidence = [
            item for item in (evidence or []) if item.get("source") == "deployments"
        ]
        if not deployment_evidence or "version changed by simulated fault" not in str(
            deployment_evidence[-1].get("summary", "")
        ):
            violations.append(
                "Rollback requires evidence of a deployment after the initial version"
            )
    if remediation_attempts >= policy.defaults.max_actions_per_incident:
        violations.append("Maximum remediation actions for this incident has been reached")

    if confidence < 0.6 and risk != "high":
        risk = "medium" if risk == "low" else "high"
        rationale.append("Raised risk because root-cause confidence is below 0.6")
    if plan.target_service in policy.defaults.require_approval_for_services:
        rationale.append(f"{plan.target_service} always requires human approval")
    if violations:
        rationale.append("Policy violations fail closed and require escalation")

    approval_required = (
        RISK_ORDER[risk] > RISK_ORDER[policy.defaults.auto_execute_max_risk]
        or plan.target_service in policy.defaults.require_approval_for_services
    )
    if approval_required and not violations:
        rationale.append(f"Risk level '{risk}' exceeds the automatic-execution limit")
    return PolicyDecision(
        risk=risk,
        approval_required=approval_required,
        violations=violations,
        rationale=rationale,
    )
