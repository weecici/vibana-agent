"""Closed action set and browser boundary checks."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from vibana_agent import executor as executor_module
from vibana_agent.executor import (
    MockBrowserExecutor,
    ReplayExecutor,
    SafetyError,
    validate_action,
)
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


@pytest.mark.parametrize("failure_stage", ["launch", "context", "page", "goto"])
def test_browser_startup_failure_releases_resources(
    monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    """Each acquired browser resource closes when later startup fails."""
    driver = Mock()
    playwright = Mock()
    browser = Mock()
    context = Mock()
    page = Mock()
    driver.start.return_value = playwright
    playwright.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = page
    failures = {
        "launch": playwright.chromium.launch,
        "context": browser.new_context,
        "page": context.new_page,
        "goto": page.goto,
    }
    failures[failure_stage].side_effect = RuntimeError("startup failed")
    monkeypatch.setattr(executor_module, "sync_playwright", lambda: driver)
    path = Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html"
    with pytest.raises(RuntimeError, match="startup failed"):
        MockBrowserExecutor(path)
    playwright.stop.assert_called_once()
    if failure_stage != "launch":
        browser.close.assert_called_once()
    if failure_stage in {"page", "goto"}:
        context.close.assert_called_once()


def test_browser_close_continues_after_context_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A context close error cannot strand Chromium or Playwright."""
    driver = Mock()
    playwright = Mock()
    browser = Mock()
    context = Mock()
    driver.start.return_value = playwright
    playwright.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    monkeypatch.setattr(executor_module, "sync_playwright", lambda: driver)
    path = Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html"
    executor = MockBrowserExecutor(path)
    context.close.side_effect = RuntimeError("context close failed")
    with pytest.raises(RuntimeError, match="context close failed"):
        executor.close()
    browser.close.assert_called_once()
    playwright.stop.assert_called_once()
