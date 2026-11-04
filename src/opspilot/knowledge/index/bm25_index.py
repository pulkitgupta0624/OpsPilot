"""Persistent lexical index backed by BM25Okapi."""

import json
import re
from pathlib import Path
from typing import Any

from opspilot.core.errors import KnowledgeBaseError
from opspilot.domain.models.knowledge import KnowledgeChunk, RetrievedChunk

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Normalize identifiers and prose into BM25 terms."""
    return [token.casefold() for token in _TOKEN.findall(text)]


class BM25Index:
    """Sparse retrieval index that rebuilds its scorer from a compact JSON corpus."""

    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise KnowledgeBaseError(
                "RAG packages are missing. Install them with `uv sync --extra rag`."
            ) from exc
        self._chunks = chunks
        self._tokens = [
            tokenize(
                " ".join(
                    [
                        chunk.text,
                        chunk.section,
                        chunk.doc_id,
                        *(str(value) for value in chunk.metadata.values() if value is not None),
                    ]
                )
            )
            for chunk in chunks
        ]
        self._ranker: Any = BM25Okapi(self._tokens) if self._tokens else None

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        return self._chunks

    def search(
        self,
        query: str,
        *,
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the highest-scoring lexical matches after metadata filtering."""
        terms = tokenize(query)
        if not terms or self._ranker is None:
            return []
        scores = self._ranker.get_scores(terms)
        query_terms = set(terms)
        filters = filters or {}
        ranked = sorted(enumerate(scores), key=lambda item: float(item[1]), reverse=True)
        results: list[RetrievedChunk] = []
        for index, raw_score in ranked:
            score = float(raw_score)
            chunk = self._chunks[index]
            if not query_terms.intersection(self._tokens[index]) or not _matches(
                chunk.metadata, filters
            ):
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    section=chunk.section,
                    text=chunk.text,
                    score=score,
                    metadata=chunk.metadata,
                    retrieval_scores={"bm25": score},
                )
            )
            if len(results) >= k:
                break
        return results

    def save(self, path: Path) -> None:
        """Persist the source chunks so BM25 can be rebuilt deterministically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": 1,
            "chunks": [chunk.model_dump(mode="json") for chunk in self._chunks],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        """Load the saved corpus and reconstruct the BM25 scorer."""
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KnowledgeBaseError(
                f"Sparse index is missing: {path}. Run `opspilot kb ingest` first."
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise KnowledgeBaseError(f"Unable to read BM25 index at {path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("format_version") != 1:
            raise KnowledgeBaseError(f"Unsupported BM25 index format at {path}")
        try:
            chunks = [KnowledgeChunk.model_validate(row) for row in payload["chunks"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise KnowledgeBaseError(f"Invalid BM25 index data at {path}: {exc}") from exc
        return cls(chunks)


def _matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if expected is None:
            continue
        actual = metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True
