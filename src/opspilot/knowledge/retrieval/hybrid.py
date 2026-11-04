"""Dense, BM25, and reciprocal-rank-fusion retriever."""

from typing import Any, Literal

from opspilot.domain.models.knowledge import RetrievedChunk
from opspilot.knowledge.index.bm25_index import BM25Index
from opspilot.knowledge.index.embedder import SentenceTransformerEmbedder
from opspilot.knowledge.index.qdrant_store import QdrantVectorStore

RetrievalMode = Literal["hybrid", "dense", "bm25"]


class HybridRetriever:
    """Combine independently ranked dense and sparse results with RRF."""

    def __init__(
        self,
        *,
        dense_store: QdrantVectorStore,
        bm25_index: BM25Index,
        embedder: SentenceTransformerEmbedder,
        candidate_k: int,
        rrf_k: int,
    ) -> None:
        self._dense_store = dense_store
        self._bm25_index = bm25_index
        self._embedder = embedder
        self._candidate_k = candidate_k
        self._rrf_k = rrf_k

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict[str, Any] | None = None,
        mode: RetrievalMode = "hybrid",
    ) -> list[RetrievedChunk]:
        """Search with one or both indexes and return passages carrying citations."""
        if not query.strip():
            raise ValueError("Search query must not be empty")
        if k < 1:
            raise ValueError("k must be positive")
        if mode not in ("hybrid", "dense", "bm25"):
            raise ValueError(f"Unsupported retrieval mode: {mode}")
        effective_filters: dict[str, Any] = {"status": "verified"}
        effective_filters.update(filters or {})

        dense_results: list[RetrievedChunk] = []
        sparse_results: list[RetrievedChunk] = []
        if mode in ("hybrid", "dense"):
            query_vector = self._embedder.embed_query(query)
            dense_results = self._dense_store.search(
                query_vector,
                k=self._candidate_k,
                filters=effective_filters,
            )
        if mode in ("hybrid", "bm25"):
            sparse_results = self._bm25_index.search(
                query,
                k=self._candidate_k,
                filters=effective_filters,
            )

        if mode == "dense":
            return dense_results[:k]
        if mode == "bm25":
            return sparse_results[:k]
        return self._fuse(dense_results, sparse_results, k=k)

    def close(self) -> None:
        """Close the persistent vector-store handle."""
        self._dense_store.close()

    def _fuse(
        self,
        dense_results: list[RetrievedChunk],
        sparse_results: list[RetrievedChunk],
        *,
        k: int,
    ) -> list[RetrievedChunk]:
        fused: dict[str, dict[str, Any]] = {}
        for source_name, results in (("dense", dense_results), ("bm25", sparse_results)):
            for rank, chunk in enumerate(results, start=1):
                entry = fused.setdefault(
                    chunk.chunk_id,
                    {"chunk": chunk, "score": 0.0, "sources": {}},
                )
                entry["score"] += 1.0 / (self._rrf_k + rank)
                entry["sources"][source_name] = chunk.score

        ranked = sorted(fused.values(), key=lambda entry: entry["score"], reverse=True)
        return [
            RetrievedChunk(
                chunk_id=entry["chunk"].chunk_id,
                doc_id=entry["chunk"].doc_id,
                section=entry["chunk"].section,
                text=entry["chunk"].text,
                score=float(entry["score"]),
                metadata=entry["chunk"].metadata,
                retrieval_scores=dict(entry["sources"]),
            )
            for entry in ranked[:k]
        ]
