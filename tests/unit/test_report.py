"""Visual report and CLI infrastructure verdict checks."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from vibana_agent import cli
from vibana_agent.report import Frame, write_report
from vibana_agent.schema import Attempt, Evidence, Report, StepResult


def image_bytes() -> bytes:
    """Return a tiny valid PNG for report output."""
    output = BytesIO()
    Image.new("RGB", (80, 60), "navy").save(output, format="PNG")
    return output.getvalue()


def test_report_contains_required_artifacts(tmp_path: Path) -> None:
    """Report JSON, HTML, and images are linked and escaped."""
    report = Report(
        scenario="demo",
        status="PASS",
        steps=[
            StepResult(
                instruction="<script>alert(1)</script>",
                status="PASS",
                attempts=[
                    Attempt(
                        status="EXECUTED",
                        strategy="candidate",
                        evidence=Evidence(matched=True, observed_text="Home"),
                        latency_ms=20,
                    )
                ],
            )
        ],
    )
    png = image_bytes()
    folder = write_report(
        report,
        [Frame(step_number=1, attempt_number=1, before=png, action=png, after=png)],
        tmp_path,
    )
    for name in (
        "report.json",
        "report.html",
        "01_before.png",
        "01_action.png",
        "01_after.png",
        "final.png",
    ):
        assert (folder / name).is_file()
    assert (
        Report.model_validate_json((folder / "report.json").read_text()).status
        == "PASS"
    )
    html = (folder / "report.html").read_text()
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "01_action.png" in html


def test_failed_attempt_keeps_real_before_screenshot(tmp_path: Path) -> None:
    """A stopped attempt displays its capture without fabricating later frames."""
    report = Report(
        scenario="stopped",
        status="FAIL",
        steps=[
            StepResult(
                instruction="Open Calendar",
                status="ERROR",
                attempts=[Attempt(status="ACTION_ERROR", latency_ms=1)],
            )
        ],
    )
    png = image_bytes()
    folder = write_report(
        report,
        [Frame(step_number=1, attempt_number=1, before=png)],
        tmp_path,
    )
    assert (folder / "01_before.png").read_bytes() == png
    assert (folder / "final.png").read_bytes() == png
    assert not (folder / "01_action.png").exists()
    assert not (folder / "01_after.png").exists()
    assert "No post-action screenshot" in (folder / "report.html").read_text()


def test_missing_service_is_infra_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing browser produces an actionable report, not a traceback."""

    def missing_browser(path: Path, seed: int) -> None:
        raise FileNotFoundError(
            "Chromium missing; run uv run playwright install chromium"
        )

    monkeypatch.setattr(cli, "MockBrowserExecutor", missing_browser)
    report, folder = cli.run_local(
        Path("scenarios/settings_brightness_70.yaml"), seed=0, root=tmp_path
    )
    assert report.status == "INFRA_ERROR"
    assert "install chromium" in (report.error or "")
    assert (folder / "report.html").is_file()
    assert [step.status for step in report.steps] == ["SKIPPED"] * 4
    assert not (folder / "04_after.png").exists()
    assert "Step not captured" in (folder / "report.html").read_text()


def test_cli_accepts_run_subcommand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented `vibana run` invocation reaches the run command."""
    from typer.testing import CliRunner

    def fake_run_local(path: Path, seed: int, root: Path) -> tuple[Report, Path]:
        return Report(scenario="demo", status="PASS", steps=[]), tmp_path

    monkeypatch.setattr(cli, "run_local", fake_run_local)
    result = CliRunner().invoke(
        cli.app, ["run", "scenarios/settings_brightness_70.yaml"]
    )
    assert result.exit_code == 0
    assert "Verdict: PASS" in result.stdout
