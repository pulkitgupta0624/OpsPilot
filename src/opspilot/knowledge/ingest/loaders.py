"""Markdown loader with validated YAML front matter and stable document IDs."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from opspilot.core.errors import KnowledgeBaseError
from opspilot.domain.models.knowledge import KnowledgeDocument

MINIMUM_DOCUMENT_COUNTS = {"runbook": 15, "postmortem": 30, "service_doc": 3}


def load_documents(root: Path) -> list[KnowledgeDocument]:
    """Read every Markdown document below ``root`` in deterministic order."""
    if not root.exists() or not root.is_dir():
        raise KnowledgeBaseError(f"Knowledge-base directory does not exist: {root}")
    paths = sorted(root.rglob("*.md"))
    if not paths:
        raise KnowledgeBaseError(f"No Markdown documents found below: {root}")

    documents = [load_document(path) for path in paths]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for document in documents:
        if document.doc_id in seen:
            duplicates.add(document.doc_id)
        seen.add(document.doc_id)
    if duplicates:
        raise KnowledgeBaseError(
            "Document IDs must be unique; duplicates: " + ", ".join(sorted(duplicates))
        )
    return documents


def load_document(path: Path) -> KnowledgeDocument:
    """Parse one Markdown file and validate its front matter contract."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise KnowledgeBaseError(f"Unable to read knowledge document {path}: {exc}") from exc
    if not lines or lines[0].strip() != "---":
        raise KnowledgeBaseError(f"Knowledge document must start with YAML front matter: {path}")

    try:
        closing = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise KnowledgeBaseError(f"Knowledge document has unclosed front matter: {path}") from exc

    try:
        metadata: Any = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise KnowledgeBaseError(f"Invalid YAML front matter in {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise KnowledgeBaseError(f"Front matter must be a YAML mapping in {path}")

    body = "\n".join(lines[closing + 1 :]).strip()
    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip():
        title = next(
            (line.lstrip("#").strip() for line in body.splitlines() if line.startswith("#")),
            path.stem.replace("_", " ").replace("-", " ").title(),
        )
    try:
        return KnowledgeDocument.model_validate({**metadata, "title": title, "text": body})
    except ValidationError as exc:
        raise KnowledgeBaseError(f"Invalid knowledge metadata in {path}: {exc}") from exc


def validate_corpus_counts(documents: list[KnowledgeDocument]) -> dict[str, int]:
    """Enforce the minimum Phase 4 corpus size and return type counts."""
    counts = {doc_type: 0 for doc_type in MINIMUM_DOCUMENT_COUNTS}
    for document in documents:
        counts[document.doc_type] += 1
    deficits = [
        f"{doc_type}: need {minimum}, found {counts[doc_type]}"
        for doc_type, minimum in MINIMUM_DOCUMENT_COUNTS.items()
        if counts[doc_type] < minimum
    ]
    if deficits:
        raise KnowledgeBaseError(
            "Knowledge corpus is below the README minimums: " + "; ".join(deficits)
        )
    return counts
