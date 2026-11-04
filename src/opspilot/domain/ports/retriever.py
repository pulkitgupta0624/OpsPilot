"""Retrieval port used by agent and application services."""

from typing import Any, Protocol

from opspilot.domain.models.knowledge import RetrievedChunk


class Retriever(Protocol):
    """Search the knowledge base and return passages with source citations."""

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]: ...
