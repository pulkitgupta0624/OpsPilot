"""OpsPilot command line interface."""

from pathlib import Path
from typing import Annotated

import typer

from opspilot.core.errors import OpsPilotError
from opspilot.simulator.virtual_runner import run_virtual_simulation

app = typer.Typer(
    name="opspilot",
    help="Simulate service incidents and generate reproducible telemetry.",
    no_args_is_help=True,
)


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
        )
    except OpsPilotError as exc:
        typer.echo(f"Simulation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Run: {artifacts.run_id}")
    typer.echo(f"Metrics: {artifacts.metrics_path} ({artifacts.metric_rows:,} rows)")
    typer.echo(f"Logs: {artifacts.logs_path} ({artifacts.log_rows:,} rows)")
    typer.echo(f"Ground truth: {artifacts.ground_truth_path} ({artifacts.fault_rows} faults)")


if __name__ == "__main__":
    app()

