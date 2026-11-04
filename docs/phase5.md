# Phase 5: Incident Agent Workflow

## What this phase adds

- A typed, persisted LangGraph workflow for incidents already detected and stored by
  the Phase 3 online monitor.
- Read-only evidence tools for current service metrics, simulator logs, deployments,
  service topology, and verified RAG passages with citations.
- Root-cause service selection is grounded in direct alert services and fault-specific
  suspect features; the planner must target the selected root-cause service.
- The critic requires incident-specific metrics, logs, or deployment evidence; a
  retrieved runbook alone cannot confirm that an incident has its described fault.
- Fake, OpenAI, Anthropic, Gemini, and Ollama JSON providers behind one interface;
  the fake provider is the default and needs no key or network access.
- Per-incident tool, investigation-round, remediation, token, cost, and wall-clock caps.
- A remediation catalog and deterministic policy gate. The planner cannot provide a
  URL or shell command; the executor only calls fixed `/admin/action/<catalog-action>`
  routes on configured local simulator services.
- Human approval with LangGraph `interrupt()` and a SQLite checkpointer. The workflow
  can be resumed from another process using the same incident ID.
- A dry-run option, append-only JSONL audit trail, and versioned prompts.
- Bounded live metric verification after simulator actions.
- Structured post-mortem Markdown written as `status: unverified` and re-indexed into
  the Phase 4 knowledge base after recovery.

The SQLite checkpointer is intended for this local, single-user workflow. The project
README leaves Postgres-backed graph persistence as a stretch item.

## Prerequisites

Start the Phase 3 PostgreSQL container, simulator services, and `opspilot monitor` as
described in `docs/phase3.md`. Generate at least one detected, still-open incident by
triggering a simulator fault. Phase 4's local knowledge index should already exist.

The default provider is deterministic `fake`, so the workflow can be demonstrated
without provider credentials. To use a hosted provider, set its standard API key in
PowerShell and choose it with `--provider`; provider calls use the existing `httpx`
dependency. Ollama uses its local HTTP API.

## Local workflow

In each new PowerShell window, point `uv` at the same environment outside OneDrive.
If the prompt shows `(opspilot)`, first run `deactivate`.

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "OpsPilot-venv"
$env:LANGGRAPH_STRICT_MSGPACK = "true"
uv sync --python 3.12 --extra dev --extra analysis --extra ml --extra rag --extra agents --link-mode copy
$ragIndex = Join-Path $env:LOCALAPPDATA "OpsPilot-rag"
```

After the monitor has inserted an open incident, start the agent. It chooses the most
recent open incident by default; pass `--incident-id` to select a specific one.

```powershell
uv run opspilot agent run --index-dir $ragIndex
```

For payments, medium-risk actions require approval. The run prints a review payload and
pauses before the executor makes any change. Resume it with the same incident ID and
index path:

```powershell
uv run opspilot agent approve <INCIDENT_ID> --approved --reviewer "Your Name" --comment "Reviewed the evidence and plan" --index-dir $ragIndex
```

If verification fails after an action, the workflow may pause for approval on a second
plan. Review the included previous action and verification result before deciding; do
not assume that a later approval prompt means no earlier action ran.

Rejecting a plan records the decision and routes to a new plan or escalation:

```powershell
uv run opspilot agent approve <INCIDENT_ID> --rejected --reviewer "Your Name" --comment "Need more evidence" --index-dir $ragIndex
```

Inspect the generated draft under `knowledge_base/generated/`. It remains unverified by
default. On successful recovery, the RAG indexer refreshes the local index; unverified
post-mortems are excluded from normal retrieval.

Use a dry run to inspect the approved plan without changing simulator state:

```powershell
uv run opspilot agent run --dry-run --index-dir $ragIndex
```

Provider examples (set keys only in the local shell, never in YAML or Git):

```powershell
$env:OPENAI_API_KEY = "<your-key>"
# Set current per-1,000-token prices for this model in configs/agents.yaml.
uv run opspilot agent run --provider openai --model YOUR_CURRENT_MODEL_ID --index-dir $ragIndex
```

Use `ANTHROPIC_API_KEY` with `--provider anthropic`, `GOOGLE_API_KEY` with
`--provider google`, or `--provider ollama --model <local-model>` for Ollama.

## Local artifacts

- `data/agents/checkpoints.sqlite`: interruptible graph state and approval checkpoints.
- `data/agents/audit.jsonl`: append-only tool, policy, approval, action, verification,
  and report events.
- `knowledge_base/generated/`: unverified live post-mortems.
- `data/rag/` or the supplied `--index-dir`: refreshed dense and sparse indexes.

## Definition of done for this vertical slice

- A Phase 3 open incident can be selected from PostgreSQL and investigated with all five
  read-only tools.
- The graph produces traceable hypotheses, a cited action plan, and deterministic policy
  decision. Payments actions pause for human approval.
- Approval can be resumed from another PowerShell process using the same incident ID.
- The executor only calls the local simulator's fixed action route; the verifier observes
  three consecutive passing metric samples or escalates.
- A verified recovery writes an unverified post-mortem draft, updates the audit trail,
  and refreshes the RAG index.

This phase has not been executed or tested in this workspace. Run the commands above
locally and share any output or errors before using a real provider or accepting a plan.
