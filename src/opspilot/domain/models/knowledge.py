"""Domain models for indexed knowledge and source citations."""

from datetime import date as DateType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    """Stable source reference attached to retrieved evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(min_length=1)
    section: str = Field(min_length=1)


class KnowledgeDocument(BaseModel):
    """One Markdown source document with validated YAML front matter."""

    model_config = ConfigDict(extra="allow", frozen=True)

    doc_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    doc_type: Literal["runbook", "postmortem", "service_doc"]
    service: str = Field(min_length=1)
    fault_type: str | None = None
    severity: str | None = None
    date: DateType | None = None
    status: Literal["verified", "unverified"] = "verified"
    tags: list[str] = Field(default_factory=list)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)

    def retrieval_metadata(self) -> dict[str, Any]:
        """Return JSON-ready metadata without the document's full body."""
        return self.model_dump(mode="json", exclude={"title", "text", "doc_id"})


class KnowledgeChunk(BaseModel):
    """Header-aware searchable passage derived from a parent document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    section: str = Field(min_length=1)
    text: str = Field(min_length=1)
    embedding_text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_count: int = Field(ge=1)


class RetrievedChunk(BaseModel):
    """A passage returned by dense, sparse, or hybrid retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    section: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_scores: dict[str, float] = Field(default_factory=dict)

    @property
    def citation(self) -> Citation:
        """Create the citation the agent should attach to claims from this chunk."""
        return Citation(doc_id=self.doc_id, section=self.section)
