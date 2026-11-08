"""Closed action set and browser boundary checks."""

from pathlib import Path

import pytest

from vibana_agent.executor import ReplayExecutor, SafetyError, validate_action
from vibana_agent.schema import Action, Box, Candidate

CANDIDATE = Candidate(id=1, box=Box(x=10, y=20, width=100, height=50))


def test_rejects_unapproved_instruction() -> None:
    """A destructive or purchase instruction cannot authorize a click."""
    action = Action(kind="click", x=60, y=45)
    for instruction in ("delete files", "purchase", "Open Settings now"):
        with pytest.raises(SafetyError):
            validate_action(action, (1280, 720), instruction, CANDIDATE)


def test_click_outside_viewport_is_rejected() -> None:
    """Pixels outside the viewport or chosen box cannot be sent to Playwright."""
    for action in (
        Action(kind="click", x=-1, y=45),
        Action(kind="click", x=1280, y=45),
        Action(kind="click", x=200, y=45),
    ):
        with pytest.raises(SafetyError):
            validate_action(action, (1280, 720), "Open Settings", CANDIDATE)


def test_replay_never_clicks(tmp_path: Path) -> None:
    """Offline screenshot replay cannot perform a live UI action."""
    replay = ReplayExecutor([tmp_path / "one.png"])
    with pytest.raises(SafetyError):
        replay.perform(Action(kind="click", x=60, y=45))
