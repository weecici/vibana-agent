"""Local command-line entry point for the screenshot prototype."""

import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from vibana_agent.config import Settings
from vibana_agent.controller import run_scenario
from vibana_agent.executor import MockBrowserExecutor
from vibana_agent.grounding.ollama import OllamaSelector
from vibana_agent.report import FrameCollector, write_report
from vibana_agent.schema import Report, Scenario, StepResult, load_scenario

app = typer.Typer(help="Run the safe local Vibana HMI prototype.")
logger = logging.getLogger(__name__)


def _infra_report(scenario: Scenario, message: str) -> Report:
    """Keep one skipped result per step when infrastructure fails."""
    return Report(
        scenario=scenario.name,
        status="INFRA_ERROR",
        steps=[
            StepResult(instruction=step.instruction, status="SKIPPED", attempts=[])
            for step in scenario.steps
        ],
        error=message,
    )


def run_local(path: Path, seed: int, root: Path) -> tuple[Report, Path]:
    """Run a validated local scenario and always write a run report."""
    scenario = load_scenario(path)
    observer = FrameCollector()
    if scenario.target != "hmi_mock":
        report = _infra_report(
            scenario, "only hmi_mock is executable in this prototype"
        )
        return report, write_report(report, observer.frames, root)
    mock_path = Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html"
    try:
        executor = MockBrowserExecutor(mock_path, seed)
        try:
            report = run_scenario(
                scenario, executor, Settings(), observer, OllamaSelector()
            )
        finally:
            executor.close()
    except Exception as error:
        logger.error("local run failed: %s", error)
        report = _infra_report(scenario, str(error))
    return report, write_report(report, observer.frames, root)


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(exists=True, readable=True)],
    seed: Annotated[int, typer.Option(help="Deterministic mock HMI layout seed.")] = 0,
) -> None:
    """Execute a YAML scenario against the bundled local mock HMI."""
    try:
        report, folder = run_local(scenario, seed, Path("runs"))
    except (ValidationError, ValueError) as error:
        raise typer.BadParameter(f"invalid scenario: {error}") from error
    typer.echo(f"Verdict: {report.status}")
    typer.echo(f"Report: {folder / 'report.html'}")
    if report.error:
        typer.echo(f"Error: {report.error}")
    if report.status != "PASS":
        raise typer.Exit(code=2 if report.status == "INFRA_ERROR" else 1)


@app.callback()
def main() -> None:
    """Use a named subcommand for local runs."""
