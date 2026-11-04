"""CPU sentence-transformer adapter for document and query embeddings."""

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opspilot.core.errors import KnowledgeBaseError


class SentenceTransformerEmbedder:
    """Lazy-load a sentence-transformer and return normalized float vectors."""

    def __init__(self, model_name: str, *, device: str = "cpu", batch_size: int = 32) -> None:
        self._model_name = model_name
        self._device = device
        self._model: Any | None = None
        self._batch_size = batch_size

    def embed_documents(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Embed passages with normalized CPU vectors."""
        return self._encode(texts)

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Embed one retrieval query with the configured model."""
        vectors = self._encode([query])
        return vectors[0]

    def _encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        vectors = self._get_model().encode(
            list(texts),
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise KnowledgeBaseError(
                    "RAG packages are missing. Install them with `uv sync --extra rag`."
                ) from exc
            self._model = SentenceTransformer(self._model_name, device=self._device)
        return self._model
