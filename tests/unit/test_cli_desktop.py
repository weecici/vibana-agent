"""Desktop CLI accepts instruction-only workflows and region bounds."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibana_agent import cli
from vibana_agent.schema import Box, Report, Scenario


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
