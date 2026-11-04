"""Typed YAML settings for the local knowledge retrieval pipeline."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from opspilot.core.errors import ConfigurationError


class RagSettings(BaseModel):
    """Chunking and local index settings for Phase 4 retrieval."""

    model_config = ConfigDict(extra="forbid")

    embedding_model: str = Field(min_length=1)
    device: str = "cpu"
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    index_dir: Path = Path("data/rag")
    collection_name: str = Field(default="opspilot_knowledge", min_length=1)
    chunk_size_tokens: int = Field(default=650, ge=100, le=2_000)
    chunk_overlap_tokens: int = Field(default=80, ge=0, le=500)
    candidate_k: int = Field(default=20, ge=1, le=500)
    rrf_k: int = Field(default=60, ge=1, le=1_000)
    default_k: int = Field(default=5, ge=1, le=100)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "RagSettings":
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        return self


def load_rag_settings(path: Path) -> RagSettings:
    """Load and validate RAG settings from YAML."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("RAG configuration must be a YAML mapping")
        return RagSettings.model_validate(raw)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"RAG configuration file not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid RAG configuration at {path}: {exc}") from exc
