# Knowledge document authoring guide

## Required metadata

Each Markdown file starts with YAML front matter containing a stable `doc_id`, `doc_type`,
`service`, `status`, and `tags`. Use `doc_type: runbook`, `postmortem`, or `service_doc`.
Runbooks and post-mortems also include `fault_type`, `severity`, and `date`. Use ISO dates
and keep scenario definitions in `evals/scenarios/`, outside `knowledge_base/`.

## Runbooks

Write actionable steps for symptoms, diagnosis, remediation, rollback, and verification.
State an explicit unsafe or ineffective action where relevant. A reader should be able to
follow the runbook without assuming that every latency spike has the same root cause.

## Post-mortems

Include impact, a timestamped timeline, root cause, contributing factors, corrective action,
verification, and lessons. Use historical, synthetic incidents that are similar to the
evaluation scenarios without copying their incident record or `source_postmortem` ID into
the searchable corpus. Vary symptoms and terminology so retrieval is not a keyword lookup.

## Service documents

Describe service responsibilities, dependencies, operational signals, SLOs, and deployment
ownership. Keep service context separate from incident-specific instructions.

## Chunking and citations

Use meaningful Markdown headings. The loader preserves the heading path and parent document
metadata on each chunk. Citations use `[doc_id | section path]`; retain stable IDs when
editing a document so evaluation labels and audit trails remain understandable.
