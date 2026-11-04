"""Check that evaluation scenarios do not cite post-mortems present in the KB."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from opspilot.core.errors import KnowledgeBaseError
from opspilot.knowledge.ingest.loaders import load_documents


@dataclass(frozen=True)
class LeakageReport:
    """Summary of the scenario-to-knowledge-base separation check."""

    scenario_count: int
    reference_count: int
    leaked_references: tuple[str, ...]


def check_scenario_leakage(knowledge_dir: Path, scenarios_dir: Path) -> LeakageReport:
    """Find every ``source_postmortem`` referenced by scenarios and check the corpus."""
    if not scenarios_dir.exists() or not scenarios_dir.is_dir():
        raise KnowledgeBaseError(f"Scenario directory does not exist: {scenarios_dir}")

    documents = load_documents(knowledge_dir)
    corpus_ids = {document.doc_id.casefold() for document in documents}
    corpus_text = "\n".join(
        path.read_text(encoding="utf-8").casefold()
        for path in knowledge_dir.rglob("*.md")
    )
    scenario_files = sorted(
        path
        for path in scenarios_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".yaml", ".yml"}
    )

    references: set[str] = set()
    for path in scenario_files:
        for payload in _read_scenario_payloads(path):
            references.update(_source_postmortems(payload))

    leaked = tuple(
        sorted(
            reference
            for reference in references
            if reference.casefold() in corpus_ids or reference.casefold() in corpus_text
        )
    )
    return LeakageReport(
        scenario_count=len(scenario_files),
        reference_count=len(references),
        leaked_references=leaked,
    )


def _read_scenario_payloads(path: Path) -> list[Any]:
    try:
        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".jsonl":
            return [json.loads(line) for line in content.splitlines() if line.strip()]
        value = json.loads(content) if path.suffix.lower() == ".json" else yaml.safe_load(content)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise KnowledgeBaseError(f"Unable to parse evaluation scenario {path}: {exc}") from exc
    return [value]


def _source_postmortems(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_postmortem" and isinstance(child, str) and child.strip():
                found.add(child.strip())
            else:
                found.update(_source_postmortems(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_source_postmortems(child))
    return found
