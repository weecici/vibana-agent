from pathlib import Path

import pytest
from pydantic import ValidationError

from vibana_agent.config import Settings
from vibana_agent.schema import Scenario, load_scenario


def test_missing_expect_is_invalid() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            {
                "name": "bad",
                "target": "hmi_mock",
                "steps": [{"instruction": "Open Settings"}],
            }
        )


def test_four_step_scenario_loads() -> None:
    scenario = load_scenario(Path("scenarios/settings_brightness_70.yaml"))
    assert len(scenario.steps) == 4
    assert scenario.steps[0].instruction == "Open Settings"
    assert scenario.steps[-1].expect is not None
    assert scenario.steps[-1].expect.text_visible == "Home"
    assert Settings().max_attempts == 3
    assert Settings().max_steps == 10


def test_desktop_scenario_needs_only_instructions(tmp_path: Path) -> None:
    scenario_path = tmp_path / "desktop.yaml"
    scenario_path.write_text(
        "name: desktop_demo\ntarget: desktop\nsteps:\n  - instruction: Open Settings\n",
        encoding="utf-8",
    )
    scenario = load_scenario(scenario_path)
    assert scenario.target == "desktop"
    assert scenario.steps[0].expect is None
