"""OpsPilot command line interface."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from sqlalchemy.exc import SQLAlchemyError

from opspilot.agents.cli import agent_app
from opspilot.core.errors import OpsPilotError
from opspilot.detection.config import load_detection_settings
from opspilot.detection.logs.drain3_detector import Drain3LogDetector, load_normal_log_records
from opspilot.detection.models.base import BaseDetector
from opspilot.detection.online import OnlineDetectionService
from opspilot.detection.registry import DetectorRegistry
from opspilot.detection.training.train_ml import train_classical_detectors
from opspilot.domain.models.telemetry import TimeRange
from opspilot.evaluation.detection_eval import evaluate_classical_detectors
from opspilot.evaluation.datasets import load_simulation_dataset
from opspilot.evaluation.rag_eval import evaluate_retrieval, load_golden_questions
from opspilot.ingestion.collectors.log_collector import LogCollector
from opspilot.ingestion.collectors.metrics_scraper import MetricsScraper
from opspilot.ingestion.config import load_ingestion_settings
from opspilot.ingestion.database import build_database_engine
from opspilot.ingestion.exporter import export_metrics_parquet
from opspilot.ingestion.file_import import import_simulation_artifacts
from opspilot.ingestion.pipeline import IngestionPipeline
from opspilot.ingestion.stores.postgres_incidents import PostgresIncidentStore
from opspilot.ingestion.stores.postgres_ground_truth import PostgresGroundTruthStore
from opspilot.ingestion.stores.postgres_logs import PostgresLogStore
from opspilot.ingestion.stores.postgres_metrics import PostgresMetricsStore
from opspilot.knowledge.config import load_rag_settings
from opspilot.knowledge.ingest.indexer import KnowledgeIndexer
from opspilot.knowledge.ingest.loaders import load_documents
from opspilot.knowledge.leakage import check_scenario_leakage
from opspilot.knowledge.service import build_retriever
from opspilot.simulator.virtual_runner import run_virtual_simulation

app = typer.Typer(
    name="opspilot",
    help="Simulate service incidents and generate reproducible telemetry.",
    no_args_is_help=True,
)
eval_app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
kb_app = typer.Typer(
    name="kb",
    help="Build and search the runbook and post-mortem knowledge base.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Manage OpsPilot simulation and data workflows."""


@app.command()
def simulate(
    virtual: Annotated[
        bool,
        typer.Option(help="Run the fast, HTTP-free virtual-time engine."),
    ] = True,
    hours: Annotated[int, typer.Option(min=1, help="Number of simulated hours.")] = 24,
    seed: Annotated[int, typer.Option(help="Seed used for reproducible load and logs.")] = 1,
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Simulator YAML configuration."),
    ] = Path("configs/simulator.yaml"),
    output: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root directory for generated data."),
    ] = Path("data"),
    normal_only: Annotated[
        bool,
        typer.Option(help="Generate a baseline run without injected faults or decoys."),
    ] = False,
) -> None:
    """Generate virtual-time metrics, structured logs, and fault ground truth."""
    if not virtual:
        typer.echo("Only virtual simulation is available in Phase 1.", err=True)
        raise typer.Exit(code=2)
    try:
        artifacts = run_virtual_simulation(
            config_path=config,
            hours=hours,
            seed=seed,
            output_root=output,
            normal_only=normal_only,
        )
    except OpsPilotError as exc:
        typer.echo(f"Simulation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Run: {artifacts.run_id}")
    typer.echo(f"Metrics: {artifacts.metrics_path} ({artifacts.metric_rows:,} rows)")
    typer.echo(f"Logs: {artifacts.logs_path} ({artifacts.log_rows:,} rows)")
    typer.echo(f"Ground truth: {artifacts.ground_truth_path} ({artifacts.fault_rows} faults)")


@app.command()
def ingest(
    once: Annotated[
        bool,
        typer.Option(help="Collect and persist one batch, then exit."),
    ] = False,
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Ingestion YAML configuration."),
    ] = Path("configs/ingestion.yaml"),
    database_url: Annotated[
        str | None,
        typer.Option(help="Override OPSPILOT_DATABASE_URL for this run."),
    ] = None,
) -> None:
    """Poll live service metrics and logs into Postgres."""
    try:
        settings = load_ingestion_settings(config)
        engine = build_database_engine(database_url or settings.database_url)
        scraper = MetricsScraper(
            settings.services,
            timeout_seconds=settings.request_timeout_seconds,
            retry_attempts=settings.retry_attempts,
        )
        collector = LogCollector(
            settings.services,
            timeout_seconds=settings.request_timeout_seconds,
            retry_attempts=settings.retry_attempts,
        )
        pipeline = IngestionPipeline(
            scraper,
            collector,
            PostgresMetricsStore(engine),
            PostgresLogStore(engine),
            batch_capacity=settings.batch_capacity,
        )
        try:
            if once:
                succeeded = pipeline.run_once()
                typer.echo(
                    "Ingestion batch persisted."
                    if succeeded
                    else f"Database unavailable; {pipeline.pending_batches} batch(es) buffered."
                )
            else:
                typer.echo("Polling services. Press Ctrl+C to stop.")
                pipeline.run_forever(interval_seconds=settings.scrape_interval_seconds)
        finally:
            pipeline.close()
            engine.dispose()
    except (OpsPilotError, OSError, ValueError, SQLAlchemyError) as exc:
        typer.echo(f"Ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        typer.echo("Ingestion stopped.")


@app.command()
def monitor(
    detector: Annotated[
        str,
        typer.Option(help="Registered detector name, such as rolling_zscore or lstm_autoencoder."),
    ] = "rolling_zscore",
    once: Annotated[
        bool,
        typer.Option(help="Collect and score one batch, then exit."),
    ] = False,
    ingestion_config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Ingestion YAML configuration."),
    ] = Path("configs/ingestion.yaml"),
    detection_config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Detection YAML configuration."),
    ] = Path("configs/detection.yaml"),
    data_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root containing normal-only Phase 1 data."),
    ] = Path("data"),
    model_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root containing registered detector artifacts."),
    ] = Path("data/models"),
    database_url: Annotated[
        str | None,
        typer.Option(help="Override OPSPILOT_DATABASE_URL for this monitor."),
    ] = None,
) -> None:
    """Poll services, persist telemetry, detect anomalies, and write incident rows."""
    engine = None
    pipeline = None
    try:
        ingestion = load_ingestion_settings(ingestion_config)
        detection = load_detection_settings(detection_config)
        model: BaseDetector = DetectorRegistry(model_root).load_latest(detector)
        log_detector = Drain3LogDetector(
            load_normal_log_records(data_root),
            detection.logs,
        )
        engine = build_database_engine(database_url or ingestion.database_url)
        online_detector = OnlineDetectionService(
            detector=model,
            settings=detection,
            log_detector=log_detector,
            incident_store=PostgresIncidentStore(engine),
        )
        baseline_dataset = load_simulation_dataset(data_root)
        all_runs = set(baseline_dataset.metrics["run_id"].astype(str).unique())
        fault_runs = (
            set(baseline_dataset.faults["run_id"].astype(str).unique())
            if not baseline_dataset.faults.empty
            else set()
        )
        normal_runs = sorted(all_runs - fault_runs)
        if not normal_runs:
            raise ValueError(
                "No normal-only metrics found for monitor warmup. Generate a run with "
                "`opspilot simulate --virtual --normal-only --hours 24 --seed 11`."
            )
        baseline_run = normal_runs[-1]
        normal_baseline = baseline_dataset.metrics.loc[
            baseline_dataset.metrics["run_id"].astype(str) == baseline_run
        ]
        online_detector.prime_baseline(normal_baseline)
        scraper = MetricsScraper(
            ingestion.services,
            timeout_seconds=ingestion.request_timeout_seconds,
            retry_attempts=ingestion.retry_attempts,
        )
        collector = LogCollector(
            ingestion.services,
            timeout_seconds=ingestion.request_timeout_seconds,
            retry_attempts=ingestion.retry_attempts,
        )
        pipeline = IngestionPipeline(
            scraper,
            collector,
            PostgresMetricsStore(engine),
            PostgresLogStore(engine),
            batch_capacity=ingestion.batch_capacity,
            on_persist=online_detector.process_batch,
        )
        if once:
            succeeded = pipeline.run_once()
            typer.echo(
                "Collection and detection batch completed."
                if succeeded
                else f"Database unavailable; {pipeline.pending_batches} batch(es) buffered."
            )
        else:
            typer.echo(
                f"Monitoring services with a normal baseline from {baseline_run}. "
                "Press Ctrl+C to stop."
            )
            pipeline.run_forever(interval_seconds=ingestion.scrape_interval_seconds)
    except (OpsPilotError, OSError, ValueError, KeyError, SQLAlchemyError) as exc:
        typer.echo(f"Monitoring failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        typer.echo("Monitoring stopped.")
    finally:
        if pipeline is not None:
            pipeline.close()
        if engine is not None:
            engine.dispose()


@app.command()
def train(
    detector: Annotated[
        str,
        typer.Option(help="Use 'ml' for all registered detectors, or select one by name."),
    ] = "ml",
    data_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root containing processed and ground-truth data."),
    ] = Path("data"),
    model_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Destination for versioned model artifacts."),
    ] = Path("data/models"),
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Detection settings YAML."),
    ] = Path("configs/detection.yaml"),
) -> None:
    """Train registered detectors on normal-only runs and calibrate their thresholds."""
    try:
        artifacts = train_classical_detectors(
            detector=detector,
            data_root=data_root,
            model_root=model_root,
            config_path=config,
        )
    except (OpsPilotError, OSError, ValueError) as exc:
        typer.echo(f"Training failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for artifact in artifacts:
        typer.echo(
            f"{artifact.name}: threshold={artifact.threshold:.6f}, "
            f"train={artifact.train_rows:,}, validation={artifact.validation_rows:,}, "
            f"artifact={artifact.artifact_dir}"
        )


@eval_app.callback()
def evaluation_group() -> None:
    """Run evaluation workflows."""


@eval_app.command("detection")
def eval_detection(
    data_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root containing processed and ground-truth data."),
    ] = Path("data"),
    model_root: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root containing trained model artifacts."),
    ] = Path("data/models"),
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Detection settings YAML."),
    ] = Path("configs/detection.yaml"),
    report_dir: Annotated[
        Path,
        typer.Option(file_okay=False, help="Destination for evaluation reports."),
    ] = Path("evals/reports"),
) -> None:
    """Compare registered detectors using event-level metrics."""
    try:
        results, report = evaluate_classical_detectors(
            data_root=data_root,
            model_root=model_root,
            config_path=config,
            report_dir=report_dir,
        )
    except (OpsPilotError, OSError, ValueError, KeyError) as exc:
        typer.echo(f"Detection evaluation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(results.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    typer.echo(f"CSV report: {report.csv_path}")
    typer.echo(f"Markdown report: {report.markdown_path}")
    typer.echo(f"Scores: {report.scores_path}")


@kb_app.command("ingest")
def kb_ingest(
    source_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Markdown knowledge-base directory."),
    ] = Path("knowledge_base"),
    index_dir: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Persistent Qdrant and BM25 index directory."),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="RAG settings YAML."),
    ] = Path("configs/rag.yaml"),
) -> None:
    """Rebuild dense Qdrant and sparse BM25 indexes from Markdown documents."""
    try:
        summary = KnowledgeIndexer(load_rag_settings(config), index_dir=index_dir).ingest(
            source_dir
        )
    except (OpsPilotError, OSError, ValueError) as exc:
        typer.echo(f"Knowledge-base ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    type_counts = ", ".join(
        f"{count} {document_type.replace('_', ' ')}"
        for document_type, count in summary.document_counts.items()
    )
    typer.echo(
        f"Indexed {summary.document_count} documents ({type_counts}) into "
        f"{summary.chunk_count} chunks. Index: {summary.index_dir}"
    )


@kb_app.command("search")
def kb_search(
    query: str,
    k: Annotated[
        int | None,
        typer.Option(min=1, max=50, help="Number of cited passages."),
    ] = None,
    service: Annotated[str | None, typer.Option(help="Filter by service.")] = None,
    fault_type: Annotated[str | None, typer.Option(help="Filter by fault type.")] = None,
    doc_type: Annotated[str | None, typer.Option(help="Filter by document type.")] = None,
    include_unverified: Annotated[
        bool,
        typer.Option(help="Include documents marked unverified."),
    ] = False,
    mode: Annotated[
        Literal["hybrid", "dense", "bm25"],
        typer.Option(help="Choose hybrid RRF, dense, or BM25 retrieval."),
    ] = "hybrid",
    index_dir: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Persistent Qdrant and BM25 index directory."),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="RAG settings YAML."),
    ] = Path("configs/rag.yaml"),
) -> None:
    """Search for relevant passages and print source citations."""
    retriever = None
    try:
        settings = load_rag_settings(config)
        retriever = build_retriever(settings, index_dir=index_dir)
        filters = {
            key: value
            for key, value in {
                "service": service,
                "fault_type": fault_type,
                "doc_type": doc_type,
            }.items()
            if value is not None
        }
        filters["status"] = None if include_unverified else "verified"
        results = retriever.search(
            query,
            k=k or settings.default_k,
            filters=filters,
            mode=mode,
        )
    except (OpsPilotError, OSError, ValueError) as exc:
        typer.echo(f"Knowledge-base search failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if retriever is not None:
            retriever.close()

    if not results:
        typer.echo("No matching knowledge passages found.")
        raise typer.Exit(code=0)
    for rank, result in enumerate(results, start=1):
        metadata = result.metadata
        service_name = metadata.get("service", "unknown")
        doc_type_name = metadata.get("doc_type", "unknown")
        typer.echo(
            f"{rank}. {result.doc_id} · {result.section} · {service_name} · "
            f"{doc_type_name} · score={result.score:.4f}"
        )
        typer.echo(f"   Citation: [{result.citation.doc_id} | {result.citation.section}]")
        typer.echo(f"   {result.text[:700]}")


@kb_app.command("eval")
def kb_eval(
    golden: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Golden retrieval questions in JSONL."),
    ] = Path("evals/datasets/rag_golden.jsonl"),
    source_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Markdown knowledge-base directory."),
    ] = Path("knowledge_base"),
    index_dir: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Persistent Qdrant and BM25 index directory."),
    ] = None,
    report_dir: Annotated[
        Path,
        typer.Option(file_okay=False, help="Destination for timestamped retrieval reports."),
    ] = Path("evals/reports"),
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="RAG settings YAML."),
    ] = Path("configs/rag.yaml"),
) -> None:
    """Measure retrieval quality and write the four-way ablation table."""
    retriever = None
    try:
        settings = load_rag_settings(config)
        questions = load_golden_questions(golden)
        documents = load_documents(source_dir)
        retriever = build_retriever(settings, index_dir=index_dir)
        summary = evaluate_retrieval(
            retriever,
            questions,
            corpus_doc_ids={document.doc_id for document in documents},
            report_dir=report_dir,
        )
    except (OpsPilotError, OSError, ValueError) as exc:
        typer.echo(f"RAG evaluation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if retriever is not None:
            retriever.close()
    typer.echo(f"Questions: {summary.question_count}")
    typer.echo(f"CSV report: {summary.csv_path}")
    typer.echo(f"Markdown report: {summary.markdown_path}")


@kb_app.command("check-leakage")
def kb_check_leakage(
    source_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Markdown knowledge-base directory."),
    ] = Path("knowledge_base"),
    scenarios_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Evaluation scenario directory."),
    ] = Path("evals/scenarios"),
) -> None:
    """Fail if a scenario's source post-mortem is present in the searchable KB."""
    try:
        report = check_scenario_leakage(source_dir, scenarios_dir)
    except (OpsPilotError, OSError, ValueError) as exc:
        typer.echo(f"Knowledge leakage check failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if report.leaked_references:
        typer.echo(
            "Leaked source post-mortem(s): " + ", ".join(report.leaked_references),
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(
        f"No leakage found across {report.scenario_count} scenario file(s) and "
        f"{report.reference_count} source-postmortem reference(s)."
    )


@data_app.callback()
def data_group() -> None:
    """Import and export telemetry datasets."""


@data_app.command("ingest")
def data_ingest(
    metrics: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Phase 1 metrics Parquet file."),
    ],
    logs: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Phase 1 structured logs JSONL file."),
    ],
    ground_truth: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, help="Phase 1 fault labels JSONL file."),
    ],
    database_url: Annotated[
        str | None,
        typer.Option(help="Override OPSPILOT_DATABASE_URL for this import."),
    ] = None,
) -> None:
    """Import one simulator run into the Postgres stores; repeated imports are safe."""
    engine = build_database_engine(database_url)
    try:
        counts = import_simulation_artifacts(
            metrics_path=metrics,
            logs_path=logs,
            ground_truth_path=ground_truth,
            metrics_store=PostgresMetricsStore(engine),
            log_store=PostgresLogStore(engine),
            ground_truth_store=PostgresGroundTruthStore(engine),
        )
    except (OpsPilotError, OSError, ValueError, SQLAlchemyError) as exc:
        typer.echo(f"Data import failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"Inserted rows: metrics={counts.metric_rows:,}, logs={counts.log_rows:,}, "
        f"ground_truth={counts.fault_rows:,}"
    )


@data_app.command("export")
def data_export(
    from_ts: Annotated[
        str,
        typer.Option(..., "--from", help="Inclusive ISO-8601 start time with timezone."),
    ],
    to_ts: Annotated[
        str,
        typer.Option(..., "--to", help="Inclusive ISO-8601 end time with timezone."),
    ],
    out: Annotated[
        Path,
        typer.Option(..., "--out", dir_okay=False, help="Destination Parquet file."),
    ],
    service: Annotated[str | None, typer.Option(help="Optional service filter.")] = None,
    run_id: Annotated[str | None, typer.Option(help="Optional simulation run filter.")] = None,
    database_url: Annotated[
        str | None,
        typer.Option(help="Override OPSPILOT_DATABASE_URL for this export."),
    ] = None,
) -> None:
    """Export a time-range query from Postgres to wide Parquet."""
    engine = build_database_engine(database_url)
    try:
        row_count = export_metrics_parquet(
            PostgresMetricsStore(engine),
            time_range=TimeRange(
                start=_parse_timezone_datetime(from_ts),
                end=_parse_timezone_datetime(to_ts),
            ),
            output_path=out,
            service=service,
            run_id=run_id,
        )
    except (OpsPilotError, OSError, ValueError, SQLAlchemyError) as exc:
        typer.echo(f"Data export failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()
    typer.echo(f"Exported {row_count:,} rows to {out}")


def _parse_timezone_datetime(value: str) -> datetime:
    """Parse ISO-8601 timestamps and require an explicit timezone offset."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone, e.g. 2026-01-15T00:00:00Z")
    return parsed


app.add_typer(eval_app, name="eval")
app.add_typer(data_app, name="data")
app.add_typer(kb_app, name="kb")
app.add_typer(agent_app, name="agent")


if __name__ == "__main__":
    app()

