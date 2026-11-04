# Phase 4: Knowledge Base and RAG

## What this phase adds

- A versioned Markdown corpus with YAML metadata: 15 runbooks, 30 historical post-mortems,
  and service documentation for orders, payments, and inventory.
- A header-aware loader and chunker. Every passage carries its parent document ID, section
  path, service, fault type, document type, severity, date, status, and a citation.
- CPU dense embeddings in a persistent local Qdrant collection and a separate BM25 index.
- Metadata-filtered dense and sparse retrieval, fused by reciprocal rank fusion (RRF).
- Verified documents are the default search scope; `--include-unverified` opts into draft
  post-mortems.
- `opspilot kb ingest`, `search`, `eval`, and `check-leakage` commands.
- A 60-question golden set with Hit@1/3/5, MRR, nDCG@5, context precision@5, and four
  retrieval ablations: BM25, dense, hybrid RRF, and hybrid RRF with service/fault filters.

The local Qdrant client stores its vector collection on disk; a Qdrant server or Docker
container is not required for this phase. The first ingest downloads the configured
Sentence Transformers model if it is not already cached. No LLM is used, so this phase
does not report answer faithfulness.

## Local workflow

The optional `rag` dependency group contains Qdrant, Sentence Transformers, and BM25. The
model runs on CPU and is independent of the PostgreSQL service used in Phase 3.

If the project virtual environment is outside OneDrive, point `uv` to that same environment
in each new PowerShell window before running project commands:

If your prompt shows `(opspilot)`, run `deactivate` first so `uv` uses the configured
project environment.

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "OpsPilot-venv"
uv sync --python 3.12 --extra dev --extra analysis --extra ml --extra rag --link-mode copy
$ragIndex = Join-Path $env:LOCALAPPDATA "OpsPilot-rag"
uv run opspilot kb ingest --index-dir $ragIndex
```

Search with a natural-language symptom query and optional metadata filters:

```powershell
uv run opspilot kb search "payments connection pool saturated and acquire timeouts" --service payments --fault-type db_pool_exhaustion --index-dir $ragIndex
```

The search output includes the document ID and section citation for each returned passage.
`--include-unverified` includes draft documents when a workflow needs them.
Run the automated evaluation and leakage check:

```powershell
uv run opspilot kb eval --index-dir $ragIndex
uv run opspilot kb check-leakage
```

Evaluation reports are written under `evals/reports/`. The index directory is under
`%LOCALAPPDATA%` in these commands to keep its persistent files outside OneDrive; use the
same `--index-dir` value for ingest, search, and evaluation.

## Definition of done

- Ingestion reports 48 documents and creates both indexes; repeating ingest replaces the
  existing collection and corpus instead of duplicating points.
- Search returns passages with valid `[doc_id | section]` citations and respects supplied
  service, fault-type, and document-type filters.
- `kb eval` writes its ablation table and reports measured retrieval metrics from the 60
  golden questions.
- `kb check-leakage` exits successfully with no source post-mortem from the evaluation
  scenario files present in the knowledge corpus.

Treat the metrics as local measurements. The README's Hit@5 target is an initial goal, not
a guaranteed outcome; report actual results and failure cases.
