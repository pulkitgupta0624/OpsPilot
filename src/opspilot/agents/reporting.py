"""Create structured post-mortems and write them back as unverified KB documents."""

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from opspilot.agents.models import PostMortem
from opspilot.domain.enums import FaultType
from opspilot.knowledge.config import RagSettings
from opspilot.knowledge.ingest.indexer import IndexBuildSummary, KnowledgeIndexer


class KnowledgeWriter:
    """Write a stable Markdown record, then refresh the persistent retrieval indexes."""

    def __init__(
        self,
        *,
        source_dir: Path,
        rag_settings: RagSettings,
        index_dir: Path | None,
    ) -> None:
        self._source_dir = source_dir
        self._rag_settings = rag_settings
        self._index_dir = index_dir

    def write(
        self,
        *,
        incident_id: str,
        service: str,
        fault_type: str,
        severity: str,
        report: PostMortem,
    ) -> tuple[Path, IndexBuildSummary | None, str | None]:
        """Persist an unverified post-mortem; an index failure does not erase the report."""
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", incident_id).strip("-.")[:60]
        doc_id = f"pm_live_{safe_id or 'incident'}"
        today = date.today().isoformat()
        metadata: dict[str, Any] = {
            "doc_id": doc_id,
            "doc_type": "postmortem",
            "service": service,
            "fault_type": fault_type if fault_type in {item.value for item in FaultType} else None,
            "severity": severity,
            "date": today,
            "status": "unverified",
            "title": report.summary,
        }
        body = self._render(report, incident_id, service, fault_type)
        path = self._source_dir / "generated" / f"{doc_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        front_matter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        path.write_text(f"---\n{front_matter}\n---\n\n{body}\n", encoding="utf-8")
        try:
            summary = KnowledgeIndexer(
                self._rag_settings,
                index_dir=self._index_dir,
            ).ingest(self._source_dir)
            return path, summary, None
        except Exception as exc:  # preserve the report and surface a concise indexing issue
            return path, None, type(exc).__name__

    @staticmethod
    def _render(report: PostMortem, incident_id: str, service: str, fault_type: str) -> str:
        citations = "\n".join(
            f"- [{citation.doc_id} | {citation.section}]" for citation in report.citations
        ) or "- No knowledge-base citation was used."
        lessons = "\n".join(f"- {lesson}" for lesson in report.lessons)
        created = datetime.now(UTC).isoformat()
        return (
            f"# {report.summary}\n\n"
            f"## Incident\n\n- ID: `{incident_id}`\n- Service: `{service}`\n"
            f"- Fault type: `{fault_type}`\n- Reported at: `{created}`\n\n"
            f"## Root cause\n\n{report.root_cause}\n\n"
            f"## Impact\n\n{report.impact}\n\n"
            f"## Resolution\n\n{report.resolution}\n\n"
            f"## Lessons\n\n{lessons}\n\n## References\n\n{citations}\n"
        )
