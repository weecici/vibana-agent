"""Full workflow with screenshot-derived deterministic selection."""

from pathlib import Path

from vibana_agent.config import Settings
from vibana_agent.controller import run_scenario
from vibana_agent.executor import MockBrowserExecutor
from vibana_agent.report import FrameCollector, write_report
from vibana_agent.schema import Candidate, Scenario, load_scenario


class LabelSelector:
    """Choose only OCR candidates from the current screenshot."""

    def select(
        self,
        image: bytes,
        instruction: str,
        candidates: list[Candidate],
        settings: Settings,
    ) -> Candidate:
        labels = {
            "Open Settings": "Settings",
            "Open Display": "Display",
            "Set brightness to 70%": "Increase brightness",
            "Return Home": "Return Home",
        }
        desired = labels[instruction]
        for candidate in candidates:
            if candidate.text == desired:
                return candidate
        raise AssertionError(f"OCR did not see {desired!r}")


def test_shifted_layout_smoke(tmp_path: Path) -> None:
    """Current screenshot labels guide four successful steps after a shift."""
    path = Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html"
    scenario: Scenario = load_scenario(Path("scenarios/settings_brightness_70.yaml"))
    executor = MockBrowserExecutor(path, seed=1)
    observer = FrameCollector()
    try:
        report = run_scenario(scenario, executor, Settings(), observer, LabelSelector())
    finally:
        executor.close()
    folder = write_report(report, observer.frames, tmp_path)
    assert report.status == "PASS", report.error
    assert [step.status for step in report.steps] == ["PASS"] * 4
    assert len(report.steps[2].attempts) == 3
    assert (folder / "final.png").is_file()
