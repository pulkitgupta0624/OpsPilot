"""Offline retrieval metrics and ablations for the golden knowledge questions."""

import csv
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opspilot.core.errors import KnowledgeBaseError
from opspilot.domain.models.knowledge import RetrievedChunk
from opspilot.knowledge.retrieval.hybrid import HybridRetriever


class GoldenQuestion(BaseModel):
    """One labeled retrieval query from the versioned JSONL golden set."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    expected_doc_ids: list[str] = Field(min_length=1)
    fault_type: str | None = None
    difficulty: Literal["easy", "hard"]
    service: str | None = None


@dataclass(frozen=True)
class RagEvaluationSummary:
    """Generated report paths and number of evaluated questions."""

    question_count: int
    csv_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class _Variant:
    name: str
    mode: Literal["dense", "bm25", "hybrid"]
    filters: Callable[[GoldenQuestion], dict[str, Any]]


_VARIANTS = (
    _Variant("BM25 only", "bm25", lambda _: {}),
    _Variant("Dense only", "dense", lambda _: {}),
    _Variant("Hybrid RRF", "hybrid", lambda _: {}),
    _Variant(
        "Hybrid RRF + metadata filters",
        "hybrid",
        lambda question: {
            key: value
            for key, value in {
                "service": question.service,
                "fault_type": question.fault_type,
            }.items()
            if value is not None
        },
    ),
)


def load_golden_questions(path: Path) -> list[GoldenQuestion]:
    """Load and validate one question per non-empty JSONL line."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise KnowledgeBaseError(f"Unable to read RAG golden set {path}: {exc}") from exc
    questions: list[GoldenQuestion] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            questions.append(GoldenQuestion.model_validate_json(line))
        except ValidationError as exc:
            raise KnowledgeBaseError(
                f"Invalid RAG golden question at {path}:{line_number}: {exc}"
            ) from exc
    if not questions:
        raise KnowledgeBaseError(f"RAG golden set is empty: {path}")
    return questions


def evaluate_retrieval(
    retriever: HybridRetriever,
    questions: list[GoldenQuestion],
    *,
    corpus_doc_ids: set[str],
    report_dir: Path,
) -> RagEvaluationSummary:
    """Run four retrieval ablations and write a timestamped CSV and Markdown report."""
    if not questions:
        raise KnowledgeBaseError("Cannot evaluate an empty golden question set")
    missing_ids = sorted(
        {
            doc_id
            for question in questions
            for doc_id in question.expected_doc_ids
            if doc_id not in corpus_doc_ids
        }
    )
    if missing_ids:
        raise KnowledgeBaseError(
            "Golden questions reference document IDs missing from the corpus: "
            + ", ".join(missing_ids)
        )

    rows: list[dict[str, float | int | str]] = []
    detail_rows: list[dict[str, Any]] = []
    for variant in _VARIANTS:
        per_question: list[dict[str, float | str]] = []
        for question in questions:
            chunks: list[RetrievedChunk] = retriever.search(
                question.question,
                k=5,
                filters=variant.filters(question),
                mode=variant.mode,
            )
            ranked_doc_ids = list(dict.fromkeys(chunk.doc_id for chunk in chunks))
            metrics = _question_metrics(ranked_doc_ids, set(question.expected_doc_ids))
            per_question.append({**metrics, "difficulty": question.difficulty})
            detail_rows.append(
                {
                    "variant": variant.name,
                    "question": question.question,
                    "difficulty": question.difficulty,
                    "expected_doc_ids": ",".join(question.expected_doc_ids),
                    "retrieved_doc_ids": ",".join(ranked_doc_ids[:5]),
                    **metrics,
                }
            )

        for difficulty in ("all", "easy", "hard"):
            selected = (
                per_question
                if difficulty == "all"
                else [row for row in per_question if row["difficulty"] == difficulty]
            )
            if not selected:
                continue
            aggregate = {
                metric: sum(float(row[metric]) for row in selected) / len(selected)
            for metric in (
                "hit@1",
                "hit@3",
                "hit@5",
                "mrr",
                "ndcg@5",
                "context_precision@5",
            )
            }
            rows.append(
                {
                    "variant": variant.name,
                    "difficulty": difficulty,
                    "questions": len(selected),
                    **aggregate,
                }
            )

    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    csv_path = report_dir / f"rag_results_{timestamp}.csv"
    markdown_path = report_dir / f"rag_results_{timestamp}.md"
    _write_csv(csv_path, rows)
    _write_markdown(markdown_path, questions, rows, detail_rows)
    return RagEvaluationSummary(len(questions), csv_path, markdown_path)


def _question_metrics(ranked_doc_ids: list[str], expected: set[str]) -> dict[str, float]:
    ranks = [index for index, doc_id in enumerate(ranked_doc_ids, start=1) if doc_id in expected]
    first_rank = min(ranks) if ranks else None

    def hit(cutoff: int) -> float:
        return float(any(rank <= cutoff for rank in ranks))

    dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks if rank <= 5)
    ideal_count = min(len(expected), 5)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    precision_denominator = max(1, min(5, len(ranked_doc_ids)))
    precision = (
        sum(doc_id in expected for doc_id in ranked_doc_ids[:5]) / precision_denominator
    )
    return {
        "hit@1": hit(1),
        "hit@3": hit(3),
        "hit@5": hit(5),
        "mrr": 1.0 / first_rank if first_rank is not None else 0.0,
        "ndcg@5": dcg / ideal_dcg if ideal_dcg else 0.0,
        "context_precision@5": precision,
    }


def _write_csv(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    fields = [
        "variant",
        "difficulty",
        "questions",
        "hit@1",
        "hit@3",
        "hit@5",
        "mrr",
        "ndcg@5",
        "context_precision@5",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(
    path: Path,
    questions: list[GoldenQuestion],
    rows: list[dict[str, float | int | str]],
    details: list[dict[str, Any]],
) -> None:
    overall = [row for row in rows if row["difficulty"] == "all"]
    lines = [
        "# Retrieval evaluation",
        "",
        f"Questions: {len(questions)}",
        "",
        "Scores use expected document IDs; generated answers were not judged, so answer faithfulness is not measured in this phase.",
        "",
        "## Ablation summary",
        "",
        "| Variant | Questions | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | Context precision@5 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in overall:
        lines.append(
            f"| {row['variant']} | {row['questions']} | {row['hit@1']:.3f} | "
            f"{row['hit@3']:.3f} | {row['hit@5']:.3f} | {row['mrr']:.3f} | "
            f"{row['ndcg@5']:.3f} | {row['context_precision@5']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Per-question results",
            "",
            "| Variant | Difficulty | Hit@5 | MRR | Expected docs | Retrieved docs |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for row in details:
        question = str(row["question"]).replace("|", "\\|")
        lines.append(
            f"| {row['variant']} · {question} | {row['difficulty']} | "
            f"{row['hit@5']:.0f} | {row['mrr']:.3f} | {row['expected_doc_ids']} | "
            f"{row['retrieved_doc_ids']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
