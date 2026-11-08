"""Local command-line entry point for the screenshot prototype."""

import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from vibana_agent.config import Settings
from vibana_agent.controller import run_scenario
from vibana_agent.executor import DesktopExecutor, MockBrowserExecutor
from vibana_agent.grounding.ollama import OllamaSelector
from vibana_agent.report import FrameCollector, write_report
from vibana_agent.schema import (
    Box,
    Report,
    Scenario,
    Step,
    StepResult,
    load_scenario,
)
from vibana_agent.verifier import OllamaGoalVerifier

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


def parse_region(value: str) -> Box:
    """Parse x,y,width,height as primary-screen pixel coordinates."""
    try:
        coordinates = [int(part.strip()) for part in value.split(",")]
        if len(coordinates) != 4:
            raise ValueError("region needs four integers")
        return Box(
            x=coordinates[0],
            y=coordinates[1],
            width=coordinates[2],
            height=coordinates[3],
        )
    except (ValueError, ValidationError) as error:
        raise ValueError(
            "region must be x,y,width,height with positive size"
        ) from error


def run_desktop(scenario: Scenario, region: Box, root: Path) -> tuple[Report, Path]:
    """Run a desktop workflow with automatic live pixel actions."""
    observer = FrameCollector()

    try:
        executor = DesktopExecutor(region)
        try:
            report = run_scenario(
                scenario,
                executor,
                scenario.settings or Settings(),
                observer,
                OllamaSelector(),
                verifier=OllamaGoalVerifier(),
            )
        finally:
            executor.close()
    except Exception as error:
        logger.error("desktop run failed: %s", error)
        report = _infra_report(scenario, str(error))
    return report, write_report(report, observer.frames, root)


def run_local(
    path: Path, seed: int, root: Path, region: Box | None = None
) -> tuple[Report, Path]:
    """Run a validated local scenario and always write a run report."""
    scenario = load_scenario(path)
    if scenario.target == "desktop":
        if region is None and scenario.region is None:
            report = _infra_report(scenario, "desktop target requires --region")
            return report, write_report(report, [], root)
        return run_desktop(scenario, region or scenario.region, root)
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
                scenario,
                executor,
                scenario.settings or Settings(),
                observer,
                OllamaSelector(),
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
    region: Annotated[
        str | None,
        typer.Option(help="Desktop primary-screen region: x,y,width,height."),
    ] = None,
) -> None:
    """Execute a YAML scenario against its declared target."""
    try:
        if region is None:
            report, folder = run_local(scenario, seed, Path("runs"))
        else:
            report, folder = run_local(
                scenario, seed, Path("runs"), region=parse_region(region)
            )
    except (ValidationError, ValueError) as error:
        raise typer.BadParameter(f"invalid scenario: {error}") from error
    typer.echo(f"Verdict: {report.status}")
    typer.echo(f"Report: {folder / 'report.html'}")
    if report.error:
        typer.echo(f"Error: {report.error}")
    if report.status != "PASS":
        raise typer.Exit(code=2 if report.status == "INFRA_ERROR" else 1)


@app.command()
def desktop(
    steps: Annotated[
        list[str] | None, typer.Argument(help="Instructions in order.")
    ] = None,
    region: Annotated[
        str | None, typer.Option(help="Primary-screen region: x,y,width,height.")
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(exists=True, readable=True, help="Saved desktop YAML workflow."),
    ] = None,
) -> None:
    """Run desktop instructions or a saved YAML workflow."""
    try:
        if file is not None:
            if steps:
                raise ValueError("use --file or inline steps, not both")
            scenario = load_scenario(file)
            if scenario.target != "desktop":
                raise ValueError("file must declare a desktop target")
            bounded = parse_region(region) if region is not None else scenario.region
            if bounded is None:
                raise ValueError("desktop file requires region or --region")
            report, folder = run_desktop(scenario, bounded, Path("runs"))
        else:
            if region is None or not steps:
                raise ValueError("inline desktop steps require --region")
            bounded = parse_region(region)
            scenario = Scenario(
                name="desktop_run",
                target="desktop",
                steps=[Step(instruction=step.strip()) for step in steps],
            )
            report, folder = run_desktop(scenario, bounded, Path("runs"))
    except (ValidationError, ValueError) as error:
        raise typer.BadParameter(f"invalid desktop input: {error}") from error
    typer.echo(f"Verdict: {report.status}")
    typer.echo(f"Report: {folder / 'report.html'}")
    if report.error:
        typer.echo(f"Error: {report.error}")
    if report.status != "PASS":
        raise typer.Exit(code=2 if report.status == "INFRA_ERROR" else 1)


@app.callback()
def main() -> None:
    """Use a named subcommand for local runs."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
