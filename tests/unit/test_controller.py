"""Controller verdicts from post-action screenshots."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from vibana_agent import controller
from vibana_agent.config import Settings
from vibana_agent.executor import SafetyError
from vibana_agent.grounding.ollama import parse_selection
from vibana_agent.report import write_report
from vibana_agent.schema import Action, Box, Candidate, Evidence, Scenario

CANDIDATE = Candidate(id=1, box=Box(x=10, y=20, width=100, height=50))
UNKNOWN = Candidate(id=99, box=Box(x=10, y=20, width=100, height=50))


def frame(color: str) -> bytes:
    """Build a valid screenshot with a distinct evidence color."""
    image = Image.new("RGB", (320, 200), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeExecutor:
    """Return a controlled sequence of pre/post screenshot pixels."""

    def __init__(self, images: list[bytes]) -> None:
        self.images = iter(images)
        self.clicks = 0
        self.actions: list[Action] = []

    def capture(self) -> bytes:
        return next(self.images)

    def perform(self, action: Action) -> None:
        self.clicks += 1
        self.actions.append(action)

    def viewport(self) -> tuple[int, int]:
        return 320, 200

    def close(self) -> None:
        pass


class FakeSelector:
    """Select one current candidate or an intentionally invalid ID."""

    def __init__(self, selected: Candidate) -> None:
        self.selected = selected

    def select(
        self,
        image: bytes,
        instruction: str,
        candidates: list[Candidate],
        settings: Settings,
    ) -> Candidate:
        return self.selected


class FakeObserver:
    """Collect screenshot evidence from completed and stopped attempts."""

    def __init__(self) -> None:
        self.records: list[tuple[int, int, bytes, bytes | None, bytes | None]] = []

    def record(
        self,
        step_number: int,
        attempt_number: int,
        before: bytes,
        action: bytes | None,
        after: bytes | None,
    ) -> None:
        self.records.append((step_number, attempt_number, before, action, after))


def setup_pixels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only OCR with controlled pixel evidence."""
    monkeypatch.setattr(
        controller,
        "perceive",
        lambda image, instruction=None, max_candidates=40: [CANDIDATE],
    )

    def verify(image: bytes, expected: str, max_candidates: int = 40) -> Evidence:
        pixel = Image.open(BytesIO(image)).getpixel((0, 0))
        matched = pixel == (0, 128, 0)
        return Evidence(matched=matched, observed_text=expected if matched else "")

    monkeypatch.setattr(controller, "verify_text", verify)


def one_step() -> Scenario:
    """Make one safe, checkable scenario."""
    return Scenario.model_validate(
        {
            "name": "test",
            "target": "hmi_mock",
            "steps": [
                {"instruction": "Open Settings", "expect": {"text_visible": "Display"}}
            ],
        }
    )


def test_requires_fresh_positive_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """A matching before screenshot never grants PASS."""
    setup_pixels(monkeypatch)
    executor = FakeExecutor([frame("green"), frame("red")] * 3)
    report = controller.run_scenario(
        one_step(), executor, Settings(), FakeObserver(), FakeSelector(CANDIDATE)
    )
    assert report.status == "FAIL"
    assert report.steps[0].status == "FAIL"
    assert executor.clicks == 3


def test_invalid_action_exhausts_to_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown selected ID causes no click and skips later steps."""
    setup_pixels(monkeypatch)
    scenario = Scenario.model_validate(
        {
            "name": "test",
            "target": "hmi_mock",
            "steps": [
                {"instruction": "Open Settings", "expect": {"text_visible": "Display"}},
                {
                    "instruction": "Open Display",
                    "expect": {"text_visible": "Brightness"},
                },
            ],
        }
    )
    executor = FakeExecutor([frame("red")] * 3)
    observer = FakeObserver()
    report = controller.run_scenario(
        scenario, executor, Settings(), observer, FakeSelector(UNKNOWN)
    )
    assert executor.clicks == 0
    assert [attempt.status for attempt in report.steps[0].attempts] == [
        "ACTION_ERROR"
    ] * 3
    assert [step.status for step in report.steps] == ["ERROR", "SKIPPED"]
    assert len(observer.records) == 3
    assert all(before == frame("red") for _, _, before, _, _ in observer.records)
    assert all(
        action is None and after is None for _, _, _, action, after in observer.records
    )


def test_failed_verification_exhausts_to_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executed clicks with false evidence become FAIL at the budget."""
    setup_pixels(monkeypatch)
    executor = FakeExecutor([frame("red")] * 6)
    report = controller.run_scenario(
        one_step(), executor, Settings(), FakeObserver(), FakeSelector(CANDIDATE)
    )
    assert report.steps[0].status == "FAIL"
    assert [attempt.status for attempt in report.steps[0].attempts] == ["EXECUTED"] * 3


def test_all_steps_pass_only_after_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each PASS requires an action and green post-action evidence."""
    setup_pixels(monkeypatch)
    executor = FakeExecutor([frame("red"), frame("green")])
    observer = FakeObserver()
    report = controller.run_scenario(
        one_step(), executor, Settings(), observer, FakeSelector(CANDIDATE)
    )
    assert report.status == "PASS"
    assert report.steps[0].status == "PASS"
    assert executor.clicks == 1
    assert len(observer.records) == 1


def test_desktop_step_uses_visual_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """An instruction-only step advances from fresh visual evidence."""
    setup_pixels(monkeypatch)
    scenario = Scenario.model_validate(
        {
            "name": "desktop_test",
            "target": "desktop",
            "steps": [{"instruction": "Open vehicle controls"}],
        }
    )

    class FakeGoalVerifier:
        def verify(
            self, before: bytes, after: bytes, instruction: str, settings: Settings
        ) -> Evidence:
            assert before != after
            assert instruction == "Open vehicle controls"
            return Evidence(
                matched=True, observed_text="Settings shown", source="vision"
            )

    executor = FakeExecutor([frame("red"), frame("green")])
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(),
        FakeObserver(),
        FakeSelector(CANDIDATE),
        verifier=FakeGoalVerifier(),
    )
    assert report.status == "PASS"
    assert report.steps[0].attempts[0].evidence == Evidence(
        matched=True, observed_text="Settings shown", source="vision"
    )
    assert executor.actions[0].instruction == "Open vehicle controls"
    assert executor.actions[0].target_label is None


def test_visual_verifier_failure_preserves_screenshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model outage after a click still leaves images for diagnosis."""
    setup_pixels(monkeypatch)
    scenario = Scenario.model_validate(
        {
            "name": "desktop_test",
            "target": "desktop",
            "steps": [{"instruction": "Open vehicle controls"}],
        }
    )

    class BrokenVerifier:
        def verify(
            self, before: bytes, after: bytes, instruction: str, settings: Settings
        ) -> Evidence:
            raise RuntimeError("model unavailable")

    observer = FakeObserver()
    report = controller.run_scenario(
        scenario,
        FakeExecutor([frame("red"), frame("green")]),
        Settings(),
        observer,
        FakeSelector(CANDIDATE),
        verifier=BrokenVerifier(),
    )
    assert report.status == "INFRA_ERROR"
    assert len(observer.records) == 1


def test_safety_rejection_stops_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A declined or stale desktop click is never proposed repeatedly."""
    setup_pixels(monkeypatch)

    class DeniedExecutor(FakeExecutor):
        def perform(self, action: Action) -> None:
            raise SafetyError("desktop click declined by user")

    executor = DeniedExecutor([frame("red")])
    report = controller.run_scenario(
        one_step(), executor, Settings(), FakeObserver(), FakeSelector(CANDIDATE)
    )
    assert report.status == "FAIL"
    assert len(report.steps[0].attempts) == 1
    assert report.steps[0].attempts[0].status == "ACTION_ERROR"


def test_coercible_model_choice_cannot_click(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed model JSON cannot coerce a visible ID into a click."""
    setup_pixels(monkeypatch)

    class CoercingSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            return parse_selection(
                '{"candidate_id": true, "reason": "guess"}', candidates
            )

    executor = FakeExecutor([frame("red")] * 6)
    report = controller.run_scenario(
        one_step(), executor, Settings(), FakeObserver(), CoercingSelector()
    )
    assert executor.clicks == 0
    assert report.status == "FAIL"
    assert [attempt.status for attempt in report.steps[0].attempts] == [
        "ACTION_ERROR"
    ] * 3


def test_step_budget_keeps_visual_report_layout(tmp_path: Path) -> None:
    """A rejected run still reports every unexecuted step and image slot."""
    scenario = Scenario.model_validate(
        {
            "name": "test",
            "target": "hmi_mock",
            "steps": [
                {"instruction": "Open Settings", "expect": {"text_visible": "Display"}},
                {
                    "instruction": "Open Display",
                    "expect": {"text_visible": "Brightness"},
                },
            ],
        }
    )
    executor = FakeExecutor([])
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(max_steps=1),
        FakeObserver(),
        FakeSelector(CANDIDATE),
    )
    assert report.status == "FAIL"
    assert report.error == "scenario exceeds max_steps"
    assert [step.status for step in report.steps] == ["SKIPPED", "SKIPPED"]
    assert executor.clicks == 0
    folder = write_report(report, [], tmp_path)
    assert not (folder / "01_after.png").exists()
    assert not (folder / "02_after.png").exists()
    assert "Open Display" in (folder / "report.html").read_text()
