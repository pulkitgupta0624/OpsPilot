"""Header-aware Markdown splitting with bounded chunk size and overlap."""

import re
from uuid import NAMESPACE_URL, uuid5

from opspilot.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument

_HEADER = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def chunk_documents(
    documents: list[KnowledgeDocument],
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[KnowledgeChunk]:
    """Split documents at Markdown headers, then apply a word-budget overlap."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than max_tokens")

    chunks: list[KnowledgeChunk] = []
    for document in documents:
        for section_number, (section, section_text) in enumerate(
            _header_sections(document.text, document.title)
        ):
            words = section_text.split()
            if not words:
                continue
            step = max_tokens - overlap_tokens
            for chunk_index, start in enumerate(range(0, len(words), step)):
                text = " ".join(words[start : start + max_tokens]).strip()
                if not text:
                    continue
                fault_type = document.fault_type or "general"
                context = f"[{document.doc_type} | {document.service} | {fault_type}] {section}"
                chunk_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{document.doc_id}:{section_number}:{section}:{chunk_index}:{text}",
                    )
                )
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=chunk_id,
                        doc_id=document.doc_id,
                        section=section,
                        text=text,
                        embedding_text=f"{context}\n{text}",
                        metadata=document.retrieval_metadata(),
                        token_count=len(text.split()),
                    )
                )
                if start + max_tokens >= len(words):
                    break
    return chunks


def _header_sections(text: str, document_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            path = " > ".join(title for _, title in heading_stack) or document_title
            sections.append((path, content))

    for line in text.splitlines():
        match = _HEADER.match(line)
        if match is None:
            current_lines.append(line)
            continue
        flush()
        current_lines.clear()
        level = len(match.group(1))
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, match.group(2).strip()))
    flush()
    if not sections and text.strip():
        sections.append((document_title, text.strip()))
    return sections
