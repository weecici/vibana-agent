"""Desktop CLI accepts instruction-only workflows and region bounds."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibana_agent import cli
from vibana_agent.config import Settings
from vibana_agent.schema import Box, Report, Scenario, Step


def test_desktop_command_needs_no_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Scenario] = []

    def fake_run_desktop(
        scenario: Scenario, region: Box, root: Path
    ) -> tuple[Report, Path]:
        seen.append(scenario)
        assert region.model_dump() == {"x": 100, "y": 100, "width": 300, "height": 200}
        return Report(scenario=scenario.name, status="PASS", steps=[]), tmp_path

    monkeypatch.setattr(cli, "run_desktop", fake_run_desktop)
    result = CliRunner().invoke(
        cli.app,
        ["desktop", "--region", "100,100,300,200", "Open Settings"],
    )
    assert result.exit_code == 0, result.output
    assert seen[0].target == "desktop"
    assert seen[0].steps[0].instruction == "Open Settings"
    assert seen[0].steps[0].expect is None


def test_invalid_desktop_region_is_rejected() -> None:
    for value in ("100,100,0,200", "-1,100,300,200", "not-a-region"):
        with pytest.raises(ValueError):
            cli.parse_region(value)


def test_desktop_file_supplies_region_and_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "name: saved_desktop\n"
        "target: desktop\n"
        "region: {x: 100, y: 50, width: 300, height: 200}\n"
        "settings: {max_candidates: 70, max_attempts: 2}\n"
        "steps:\n  - instruction: Open Settings\n",
        encoding="utf-8",
    )
    seen: list[tuple[Scenario, Box]] = []

    def fake_run_desktop(
        scenario: Scenario, region: Box, root: Path
    ) -> tuple[Report, Path]:
        seen.append((scenario, region))
        return Report(scenario=scenario.name, status="PASS", steps=[]), tmp_path

    monkeypatch.setattr(cli, "run_desktop", fake_run_desktop)
    result = CliRunner().invoke(cli.app, ["desktop", "--file", str(workflow)])
    assert result.exit_code == 0, result.output
    scenario, region = seen[0]
    assert region == Box(x=100, y=50, width=300, height=200)
    assert scenario.settings is not None
    assert scenario.settings.max_candidates == 70
    assert scenario.settings.max_attempts == 2


def test_desktop_file_rejects_non_desktop_target(tmp_path: Path) -> None:
    workflow = tmp_path / "mock.yaml"
    workflow.write_text(
        "name: mock\ntarget: hmi_mock\n"
        "steps:\n  - instruction: Open Settings\n"
        "    expect: {text_visible: Display}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli.app, ["desktop", "--file", str(workflow)])
    assert result.exit_code != 0
    assert "desktop target" in result.output


def test_desktop_run_uses_file_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario = Scenario(
        name="configured",
        target="desktop",
        settings=Settings(max_candidates=72),
        steps=[Step(instruction="Open Settings")],
    )
    observed: list[Settings] = []

    class StubExecutor:
        def __init__(self, region: Box) -> None:
            self.region = region

        def close(self) -> None:
            pass

    def fake_run_scenario(
        scenario: Scenario,
        executor: StubExecutor,
        settings: Settings,
        observer: object,
        selector: object,
        verifier: object,
        planner: object,
    ) -> Report:
        observed.append(settings)
        return Report(scenario=scenario.name, status="PASS", steps=[])

    monkeypatch.setattr(cli, "DesktopExecutor", StubExecutor)
    monkeypatch.setattr(cli, "run_scenario", fake_run_scenario)
    cli.run_desktop(scenario, Box(x=0, y=0, width=100, height=100), tmp_path)
    assert observed[0].max_candidates == 72
