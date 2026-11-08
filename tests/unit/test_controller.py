"""Controller verdicts from post-action screenshots."""

from io import BytesIO

import pytest
from PIL import Image

from vibana_agent import controller
from vibana_agent.config import Settings
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

    def capture(self) -> bytes:
        return next(self.images)

    def perform(self, action: Action) -> None:
        self.clicks += 1

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
    """Collect emitted before/action/after image triples."""

    def __init__(self) -> None:
        self.records: list[tuple[int, int, bytes, bytes, bytes]] = []

    def record(
        self,
        step_number: int,
        attempt_number: int,
        before: bytes,
        action: bytes,
        after: bytes,
    ) -> None:
        self.records.append((step_number, attempt_number, before, action, after))


def setup_pixels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only OCR with controlled pixel evidence."""
    monkeypatch.setattr(controller, "perceive", lambda image: [CANDIDATE])

    def verify(image: bytes, expected: str) -> Evidence:
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
    report = controller.run_scenario(
        scenario, executor, Settings(), FakeObserver(), FakeSelector(UNKNOWN)
    )
    assert executor.clicks == 0
    assert [attempt.status for attempt in report.steps[0].attempts] == [
        "ACTION_ERROR"
    ] * 3
    assert [step.status for step in report.steps] == ["ERROR", "SKIPPED"]


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
