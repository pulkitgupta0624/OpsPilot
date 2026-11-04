"""Composition for rebuilding dense and sparse indexes from Markdown sources."""

from dataclasses import dataclass
from pathlib import Path

from opspilot.core.errors import KnowledgeBaseError
from opspilot.knowledge.config import RagSettings
from opspilot.knowledge.index.bm25_index import BM25Index
from opspilot.knowledge.index.embedder import SentenceTransformerEmbedder
from opspilot.knowledge.index.qdrant_store import QdrantVectorStore
from opspilot.knowledge.ingest.chunking import chunk_documents
from opspilot.knowledge.ingest.loaders import load_documents, validate_corpus_counts


@dataclass(frozen=True)
class IndexBuildSummary:
    """Counts and paths emitted by one idempotent knowledge index build."""

    document_count: int
    document_counts: dict[str, int]
    chunk_count: int
    index_dir: Path


class KnowledgeIndexer:
    """Load, chunk, embed, and persist a corpus into both retrieval indexes."""

    def __init__(self, settings: RagSettings, *, index_dir: Path | None = None) -> None:
        self._settings = settings
        self._index_dir = index_dir or settings.index_dir

    def ingest(self, source_dir: Path) -> IndexBuildSummary:
        """Rebuild the Qdrant collection and BM25 corpus from Markdown documents."""
        documents = load_documents(source_dir)
        document_counts = validate_corpus_counts(documents)
        chunks = chunk_documents(
            documents,
            max_tokens=self._settings.chunk_size_tokens,
            overlap_tokens=self._settings.chunk_overlap_tokens,
        )
        if not chunks:
            raise KnowledgeBaseError("Chunking produced no searchable passages")

        embedder = SentenceTransformerEmbedder(
            self._settings.embedding_model,
            device=self._settings.device,
            batch_size=self._settings.embedding_batch_size,
        )
        vectors = embedder.embed_documents([chunk.embedding_text for chunk in chunks])
        self._index_dir.mkdir(parents=True, exist_ok=True)
        vector_store = QdrantVectorStore(self._index_dir, self._settings.collection_name)
        try:
            vector_store.rebuild(chunks, vectors)
        finally:
            vector_store.close()

        BM25Index(chunks).save(self._index_dir / "bm25_index.json")
        return IndexBuildSummary(
            document_count=len(documents),
            document_counts=document_counts,
            chunk_count=len(chunks),
            index_dir=self._index_dir,
        )
