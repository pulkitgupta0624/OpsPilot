"""Qdrant vector-store adapter using the client's persistent local mode."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opspilot.core.errors import KnowledgeBaseError
from opspilot.domain.models.knowledge import KnowledgeChunk, RetrievedChunk


class QdrantVectorStore:
    """Persist and search dense vectors without requiring a Qdrant server."""

    def __init__(self, index_dir: Path, collection_name: str) -> None:
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise KnowledgeBaseError(
                "RAG packages are missing. Install them with `uv sync --extra rag`."
            ) from exc
        storage_path = index_dir / "qdrant"
        storage_path.mkdir(parents=True, exist_ok=True)
        self._client: Any = QdrantClient(path=str(storage_path))
        self._collection_name = collection_name

    def rebuild(
        self,
        chunks: Sequence[KnowledgeChunk],
        vectors: NDArray[np.float32],
    ) -> None:
        """Replace the collection contents so repeated ingests stay idempotent."""
        if len(chunks) != len(vectors):
            raise KnowledgeBaseError("Vector count does not match the chunk count")
        if not chunks:
            raise KnowledgeBaseError("Cannot build a vector collection with no chunks")

        from qdrant_client.models import Distance, PointStruct, VectorParams

        if self._client.collection_exists(self._collection_name):
            self._client.delete_collection(self._collection_name)
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=VectorParams(size=int(vectors.shape[1]), distance=Distance.COSINE),
        )

        batch_size = 128
        for start in range(0, len(chunks), batch_size):
            batch_chunks = chunks[start : start + batch_size]
            batch_vectors = vectors[start : start + batch_size]
            points = [
                PointStruct(
                    id=chunk.chunk_id,
                    vector=vector.tolist(),
                    payload={
                        "chunk_id": chunk.chunk_id,
                        "doc_id": chunk.doc_id,
                        "section": chunk.section,
                        "text": chunk.text,
                        "metadata": chunk.metadata,
                    },
                )
                for chunk, vector in zip(batch_chunks, batch_vectors, strict=True)
            ]
            self._client.upsert(
                collection_name=self._collection_name,
                points=points,
                wait=True,
            )

    def search(
        self,
        query_vector: NDArray[np.float32],
        *,
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Find nearest vectors and reconstruct cited passages from Qdrant payloads."""
        from qdrant_client import models

        if not self._client.collection_exists(self._collection_name):
            raise KnowledgeBaseError(
                "The dense index is missing; run `opspilot kb ingest` before searching."
            )
        query_filter = _to_qdrant_filter(filters or {}, models)
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector.tolist(),
            query_filter=query_filter,
            limit=k,
            with_payload=True,
            with_vectors=False,
        )
        results: list[RetrievedChunk] = []
        for point in response.points:
            payload = point.payload or {}
            metadata = payload.get("metadata", {})
            results.append(
                RetrievedChunk(
                    chunk_id=str(payload["chunk_id"]),
                    doc_id=str(payload["doc_id"]),
                    section=str(payload["section"]),
                    text=str(payload["text"]),
                    score=float(point.score),
                    metadata=metadata if isinstance(metadata, dict) else {},
                    retrieval_scores={"dense": float(point.score)},
                )
            )
        return results

    def close(self) -> None:
        """Release the persistent local collection handle."""
        self._client.close()


def _to_qdrant_filter(filters: dict[str, Any], models: Any) -> Any | None:
    conditions = []
    for key, value in filters.items():
        if value is None:
            continue
        match = (
            models.MatchAny(any=list(value))
            if isinstance(value, (list, tuple, set))
            else models.MatchValue(value=value)
        )
        conditions.append(
            models.FieldCondition(key=f"metadata.{key}", match=match)
        )
    return models.Filter(must=conditions) if conditions else None
