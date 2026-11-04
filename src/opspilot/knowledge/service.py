"""Application factory for search over the persisted local knowledge indexes."""

from pathlib import Path

from opspilot.knowledge.config import RagSettings
from opspilot.knowledge.index.bm25_index import BM25Index
from opspilot.knowledge.index.embedder import SentenceTransformerEmbedder
from opspilot.knowledge.index.qdrant_store import QdrantVectorStore
from opspilot.knowledge.retrieval.hybrid import HybridRetriever


def build_retriever(
    settings: RagSettings,
    *,
    index_dir: Path | None = None,
) -> HybridRetriever:
    """Open both persisted indexes and wire the RAG retriever."""
    root = index_dir or settings.index_dir
    bm25_index = BM25Index.load(root / "bm25_index.json")
    dense_store = QdrantVectorStore(root, settings.collection_name)
    return HybridRetriever(
        dense_store=dense_store,
        bm25_index=bm25_index,
        embedder=SentenceTransformerEmbedder(
            settings.embedding_model,
            device=settings.device,
            batch_size=settings.embedding_batch_size,
        ),
        candidate_k=settings.candidate_k,
        rrf_k=settings.rrf_k,
    )
