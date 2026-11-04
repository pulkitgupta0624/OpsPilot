"""Provider-neutral JSON chat interface with fake, hosted, and local adapters."""

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

import httpx

from opspilot.agents.config import AgentSettings
from opspilot.agents.triage import (
    directly_alerted_services,
    fault_signal_services,
    has_observed_fault_signal,
)


@dataclass(frozen=True)
class ProviderResponse:
    """Text and usage information returned by one model call."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ModelProvider(Protocol):
    """Small port so graph nodes can use fake or network-backed providers."""

    def complete(self, task: str, prompt: str, context: dict[str, Any]) -> ProviderResponse: ...


class JsonModel:
    """Apply prompt loading, JSON parsing, usage limits, and provider delegation."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    def invoke(
        self,
        task: str,
        prompt: str,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self._provider.complete(task, prompt, context)
        payload = _parse_json_object(response.content)
        usage = {
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        }
        return payload, usage


class FakeProvider:
    """Deterministic structured responder for local demos and recorded workflows."""

    def __init__(self, model: str = "deterministic-fake") -> None:
        self._model = model

    def complete(self, task: str, prompt: str, context: dict[str, Any]) -> ProviderResponse:
        payload = self._respond(task, context)
        content = json.dumps(payload, sort_keys=True)
        return ProviderResponse(
            content=content,
            model=self._model,
            input_tokens=max(1, len(prompt + json.dumps(context, sort_keys=True)) // 4),
            output_tokens=max(1, len(content) // 4),
        )

    def _respond(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        if task == "triage":
            incident = context.get("incident", {})
            alerts = context.get("alerts", [])
            fault_type = _infer_fault(context)
            matching_services = fault_signal_services(fault_type, alerts)
            alerted_services = directly_alerted_services(alerts)
            service = (
                matching_services[0]
                if matching_services
                else _primary_service(incident, alerts)
            )
            if len(alerted_services) > 1 and not matching_services:
                # Correlation alone cannot tell a root service from an affected caller.
                fault_type = "unknown"
            evidence_ids = [
                str(item["id"])
                for item in context.get("evidence", [])
                if item.get("id")
            ]
            if not evidence_ids:
                evidence_ids = [str(item["id"]) for item in alerts if item.get("id")]
            return {
                "severity": "sev2" if service == "payments" else "sev3",
                "affected_services": list(incident.get("affected_services", [service])),
                "hypotheses": [
                    {
                        "root_cause_service": service,
                        "fault_type": fault_type,
                        "confidence": 0.72 if fault_type != "unknown" else 0.35,
                        "supporting_evidence_ids": evidence_ids or ["alert-0001"],
                        "contradicting_evidence_ids": [],
                        "rationale": (
                            "Initial classification from alert features and service symptoms."
                        ),
                    }
                ],
            }
        if task == "critic":
            hypotheses = context.get("hypotheses", [])
            evidence = context.get("evidence", [])
            selected = hypotheses[0] if hypotheses else None
            confidence = float(selected.get("confidence", 0.35)) if selected else 0.0
            evidence_confirms = bool(selected) and has_observed_fault_signal(
                str(selected.get("fault_type", "unknown")), evidence
            )
            if evidence_confirms:
                confidence = max(confidence, 0.82)
                if selected is not None:
                    corroborating_ids = [
                        str(item["id"])
                        for item in evidence
                        if has_observed_fault_signal(
                            str(selected.get("fault_type", "unknown")), [item]
                        )
                    ]
                    selected = {
                        **selected,
                        "supporting_evidence_ids": list(
                            dict.fromkeys(
                                list(selected.get("supporting_evidence_ids", []))
                                + corroborating_ids
                            )
                        ),
                    }
            return {
                "accept": bool(selected and evidence_confirms and confidence >= 0.6),
                "top_hypothesis": selected,
                "confidence": confidence,
                "missing_evidence": (
                    []
                    if evidence_confirms
                    else ["a metric or log signal supporting the hypothesis"]
                ),
                "contradictions": [],
            }
        if task == "planner":
            hypothesis = context.get("hypothesis") or {}
            fault_type = str(hypothesis.get("fault_type", "unknown"))
            service = str(hypothesis.get("root_cause_service", _primary_service({}, [])))
            failed = set(context.get("failed_actions", []))
            action_options = {
                "memory_leak": ["restart_service", "scale_out"],
                "db_pool_exhaustion": ["increase_db_pool", "restart_service"],
                "slow_dependency": ["enable_circuit_breaker"],
                "bad_deployment": ["rollback_deployment"],
                "disk_full": ["clear_disk_space"],
            }.get(fault_type, [])
            action = next((item for item in action_options if item not in failed), None)
            if action is None:
                return {
                    "action": "escalate_to_human",
                    "reason": "No supported, untried action is available.",
                }
            metric, comparator, threshold = _verification_for(fault_type)
            evidence = context.get("evidence", [])
            evidence_ids = [str(item["id"]) for item in evidence if item.get("id")]
            if not evidence_ids:
                evidence_ids = list(hypothesis.get("supporting_evidence_ids", []))
            citations = [
                citation
                for item in evidence
                for citation in item.get("citations", [])
            ]
            return {
                "action": action,
                "target_service": service,
                "params": {},
                "expected_outcome": (
                    f"The {fault_type} symptoms stop and {metric} "
                    "returns to a healthy range."
                ),
                "verification": [
                    {
                        "metric": metric,
                        "service": service,
                        "comparator": comparator,
                        "threshold": threshold,
                        "window_s": 15,
                    }
                ],
                "rollback": None,
                "citations": citations,
                "evidence_ids": evidence_ids,
            }
        if task == "reporter":
            incident = context.get("incident", {})
            hypothesis = context.get("hypothesis") or {}
            plan = context.get("plan") or {}
            verification = context.get("verification") or {}
            evidence = context.get("evidence", [])
            citations = [
                citation
                for item in evidence
                for citation in item.get("citations", [])
            ]
            return {
                "summary": str(incident.get("summary", "Simulated service incident resolved.")),
                "root_cause": str(
                    hypothesis.get("rationale", hypothesis.get("fault_type", "Unknown"))
                ),
                "impact": (
                    "The affected simulated service showed anomalous telemetry until remediation."
                ),
                "resolution": (
                    f"Applied {plan.get('action', 'no action')}; "
                    f"{verification.get('message', 'recovery verified')}."
                ),
                "lessons": [
                    "Keep alert evidence and remediation approval attached to the incident."
                ],
                "citations": citations,
            }
        raise ValueError(f"Fake provider does not implement task '{task}'")


class HttpProvider:
    """HTTP adapters for OpenAI, Anthropic, Gemini, and Ollama chat endpoints."""

    def __init__(self, settings: AgentSettings) -> None:
        self._settings = settings

    def complete(self, task: str, prompt: str, context: dict[str, Any]) -> ProviderResponse:
        provider = self._settings.provider
        model = self._settings.model
        user_text = json.dumps({"task": task, "context": context}, ensure_ascii=False)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        base_url = (self._settings.base_url or "").rstrip("/")

        if provider == "openai":
            key = _required_env("OPENAI_API_KEY")
            url = base_url or "https://api.openai.com/v1/chat/completions"
            headers["Authorization"] = f"Bearer {key}"
            body = {
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_text},
                ],
            }
            return self._post_openai(url, headers, body, model)

        if provider == "anthropic":
            key = _required_env("ANTHROPIC_API_KEY")
            url = base_url or "https://api.anthropic.com/v1/messages"
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
            body = {
                "model": model,
                "max_tokens": 2_000,
                "temperature": 0,
                "system": prompt,
                "messages": [{"role": "user", "content": user_text}],
            }
            with httpx.Client(timeout=self._settings.request_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
            usage = data.get("usage", {})
            content = "".join(
                str(item.get("text", ""))
                for item in data.get("content", [])
                if item.get("type") == "text"
            )
            return ProviderResponse(
                content,
                model,
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
            )

        if provider == "google":
            key = _required_env("GOOGLE_API_KEY")
            url = base_url or (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent"
            )
            headers["x-goog-api-key"] = key
            body = {
                "systemInstruction": {"parts": [{"text": prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_text}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            }
            with httpx.Client(timeout=self._settings.request_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
            usage = data.get("usageMetadata", {})
            candidates = data.get("candidates", [])
            content = "".join(
                str(part.get("text", ""))
                for part in (
                    candidates[0].get("content", {}).get("parts", [])
                    if candidates
                    else []
                )
            )
            return ProviderResponse(
                content,
                model,
                int(usage.get("promptTokenCount", 0)),
                int(usage.get("candidatesTokenCount", 0)),
            )

        if provider == "ollama":
            url = base_url or "http://127.0.0.1:11434/api/chat"
            body = {
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_text},
                ],
            }
            with httpx.Client(timeout=self._settings.request_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
            message = data.get("message", {})
            return ProviderResponse(
                str(message.get("content", "")),
                model,
                int(data.get("prompt_eval_count", 0)),
                int(data.get("eval_count", 0)),
            )

        raise ValueError(f"Unsupported LLM provider '{provider}'")

    def _post_openai(
        self, url: str, headers: dict[str, str], body: dict[str, Any], model: str
    ) -> ProviderResponse:
        with httpx.Client(timeout=self._settings.request_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        usage = data.get("usage", {})
        choices = data.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        return ProviderResponse(
            str(message.get("content", "")),
            model,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )


class RecordingProvider:
    """Append provider requests and responses as JSONL for deterministic replay."""

    def __init__(self, wrapped: ModelProvider, path: Path) -> None:
        self._wrapped = wrapped
        self._path = path

    def complete(self, task: str, prompt: str, context: dict[str, Any]) -> ProviderResponse:
        request_hash = _request_hash(task, prompt, context)
        response = self._wrapped.complete(task, prompt, context)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "request_hash": request_hash,
                        "task": task,
                        "response": {
                            "content": response.content,
                            "model": response.model,
                            "input_tokens": response.input_tokens,
                            "output_tokens": response.output_tokens,
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
        return response


class ReplayProvider:
    """Replay recorded provider responses, rejecting unknown request payloads."""

    def __init__(self, path: Path) -> None:
        self._records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self._cursor = 0

    def complete(self, task: str, prompt: str, context: dict[str, Any]) -> ProviderResponse:
        request_hash = _request_hash(task, prompt, context)
        for position in range(self._cursor, len(self._records)):
            record = self._records[position]
            if record.get("request_hash") != request_hash:
                continue
            self._cursor = position + 1
            return ProviderResponse(**record["response"])
        raise ValueError(f"No recorded model response matches task '{task}'")


def build_provider(settings: AgentSettings) -> ModelProvider:
    """Create the configured provider and optional recording/replay adapter."""
    if settings.replay_file is not None:
        provider: ModelProvider = ReplayProvider(settings.replay_file)
    elif settings.provider == "fake":
        provider = FakeProvider(settings.model)
    else:
        provider = HttpProvider(settings)
    if settings.record_file is not None and settings.replay_file is None:
        provider = RecordingProvider(provider, settings.record_file)
    return provider


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Provider requires the {name} environment variable")
    return value


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Model response must be one JSON object")
    return value


def _request_hash(task: str, prompt: str, context: dict[str, Any]) -> str:
    material = json.dumps(
        {"task": task, "prompt": prompt, "context": context},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _primary_service(incident: dict[str, Any], alerts: list[dict[str, Any]]) -> str:
    for alert in alerts:
        service = alert.get("service")
        if service:
            return str(service)
    services = incident.get("affected_services", [])
    return str(services[0]) if services else "orders"


def _infer_fault(context: dict[str, Any]) -> str:
    alerts = context.get("alerts", [])
    evidence = context.get("evidence", [])
    parts = [str(context.get("incident", {}).get("summary", ""))]
    for alert in alerts:
        parts.extend(
            [
                str(alert.get("details", {})),
                " ".join(str(item.get("name", "")) for item in alert.get("suspect_features", [])),
            ]
        )
    parts.extend(str(item.get("summary", "")) for item in evidence)
    text = " ".join(parts).lower()
    rules = (
        ("db_pool_exhaustion", ("db_pool", "pool", "acquire", "connection")),
        ("memory_leak", ("memory", "oom", "gc pause")),
        ("slow_dependency", ("dependency", "upstream", "circuit")),
        ("bad_deployment", ("deployment", "version", "rollback")),
        ("disk_full", ("disk", "filesystem", "disk_used")),
    )
    matches = [(sum(token in text for token in tokens), fault) for fault, tokens in rules]
    score, selected = max(matches, default=(0, "unknown"))
    return selected if score else "unknown"


def _verification_for(fault_type: str) -> tuple[str, str, float]:
    return {
        "memory_leak": ("memory_mb", "lt", 900.0),
        "db_pool_exhaustion": ("db_pool_utilization", "lt", 0.8),
        "slow_dependency": ("latency_ms_p95", "lt", 800.0),
        "bad_deployment": ("error_rate", "lt", 0.08),
        "disk_full": ("disk_used_pct", "lt", 80.0),
    }.get(fault_type, ("error_rate", "lt", 0.08))
