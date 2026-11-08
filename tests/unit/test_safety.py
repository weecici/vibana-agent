"""Closed action set and browser boundary checks."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from evdev import ecodes
from PIL import Image, ImageGrab

from vibana_agent import executor as executor_module
from vibana_agent.desktop import GrimCapture, VirtualPointerBackend, X11Capture
from vibana_agent.executor import (
    DesktopExecutor,
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


class FakeDesktopGui:
    """In-memory desktop API that records real pixel click coordinates."""

    def __init__(self) -> None:
        self.color = "navy"
        self.clicks: list[tuple[int, int]] = []
        self.scrolls: list[tuple[int, int, str, int]] = []
        self.typed: list[str] = []
        self.keys: list[str] = []
        self.closed = False

    def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
        return Image.new("RGB", (region[2], region[3]), self.color)

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def scroll(self, x: int, y: int, direction: str, ticks: int) -> None:
        self.scrolls.append((x, y, direction, ticks))

    def type_text(self, value: str) -> None:
        self.typed.append(value)

    def key_press(self, key: str) -> None:
        self.keys.append(key)

    def size(self) -> tuple[int, int]:
        return 1280, 720

    def close(self) -> None:
        self.closed = True


def test_desktop_accepts_wayland_backend() -> None:
    gui = FakeDesktopGui()
    executor = DesktopExecutor(
        Box(x=100, y=100, width=300, height=200),
        gui=gui,
        session_type="wayland",
    )
    executor.capture()
    executor.perform(Action(kind="click", x=25, y=35))
    assert gui.clicks == [(125, 135)]


def test_invalid_region_releases_virtual_input() -> None:
    gui = FakeDesktopGui()
    with pytest.raises(SafetyError, match="outside the primary screen"):
        DesktopExecutor(
            Box(x=1200, y=100, width=300, height=200),
            gui=gui,
            session_type="wayland",
        )
    assert gui.closed


def test_desktop_click_stays_inside_region_without_approval() -> None:
    gui = FakeDesktopGui()
    executor = DesktopExecutor(
        Box(x=100, y=100, width=300, height=200),
        gui=gui,
        session_type="x11",
    )
    executor.capture()
    executor.perform(Action(kind="click", x=25, y=35))
    assert gui.clicks == [(125, 135)]
    with pytest.raises(SafetyError):
        executor.perform(Action(kind="click", x=300, y=35))
    assert gui.clicks == [(125, 135)]


def test_desktop_rejects_changed_screen_before_click() -> None:
    gui = FakeDesktopGui()
    executor = DesktopExecutor(
        Box(x=100, y=100, width=300, height=200),
        gui=gui,
        session_type="x11",
    )
    executor.capture()
    gui.color = "red"
    with pytest.raises(SafetyError, match="changed"):
        executor.perform(Action(kind="click", x=25, y=35))
    assert gui.clicks == []


def test_desktop_routes_scroll_and_keyboard_with_fresh_capture() -> None:
    gui = FakeDesktopGui()
    executor = DesktopExecutor(
        Box(x=100, y=100, width=300, height=200),
        gui=gui,
        session_type="x11",
    )
    executor.capture()
    executor.perform(
        Action(kind="scroll", x=25, y=35, direction="down", ticks=2)
    )
    assert gui.scrolls == [(125, 135, "down", 2)]
    with pytest.raises(SafetyError, match="fresh screenshot"):
        executor.perform(Action(kind="type_text", text="hello"))
    executor.capture()
    executor.perform(Action(kind="type_text", text="hello"))
    executor.capture()
    executor.perform(Action(kind="key_press", key="Enter"))
    assert gui.typed == ["hello"]
    assert gui.keys == ["Enter"]


def test_desktop_rejects_scroll_outside_region() -> None:
    gui = FakeDesktopGui()
    executor = DesktopExecutor(
        Box(x=100, y=100, width=300, height=200),
        gui=gui,
        session_type="x11",
    )
    executor.capture()
    with pytest.raises(SafetyError, match="outside the desktop region"):
        executor.perform(
            Action(kind="scroll", x=300, y=35, direction="down", ticks=1)
        )
    assert gui.scrolls == []


def test_grim_capture_uses_region_pixels() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str]) -> bytes:
        calls.append(command)
        output = BytesIO()
        Image.new("RGB", (300, 200), "navy").save(output, format="PNG")
        return output.getvalue()

    capture = GrimCapture(runner=runner)
    assert capture.screenshot((100, 50, 300, 200)).size == (300, 200)
    assert calls == [["grim", "-g", "100,50 300x200", "-"]]


def test_x11_capture_uses_display_and_region_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[int, int, int, int] | None, str | None]] = []

    def grab(
        bbox: tuple[int, int, int, int] | None = None,
        xdisplay: str | None = None,
    ) -> Image.Image:
        calls.append((bbox, xdisplay))
        return Image.new("RGB", (300, 200), "navy")

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(ImageGrab, "grab", grab)
    capture = X11Capture()
    assert capture.screenshot((100, 50, 300, 200)).size == (300, 200)
    assert calls == [((100, 50, 400, 250), ":99")]


class FakePointerDevice:
    """Record kernel pointer events without touching the host desktop."""

    def __init__(self) -> None:
        self.events: list[tuple[int, int, int] | str] = []

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value))

    def syn(self) -> None:
        self.events.append("syn")

    def close(self) -> None:
        self.events.append("close")


def test_virtual_pointer_moves_and_clicks_at_exact_pixels() -> None:
    gui = FakeDesktopGui()
    device = FakePointerDevice()
    backend = VirtualPointerBackend(gui, device=device, press_delay_s=0)
    backend.click(125, 135)
    assert device.events == [
        (ecodes.EV_ABS, ecodes.ABS_X, 131),
        (ecodes.EV_ABS, ecodes.ABS_Y, 141),
        "syn",
        (ecodes.EV_ABS, ecodes.ABS_X, 125),
        (ecodes.EV_ABS, ecodes.ABS_Y, 135),
        "syn",
        (ecodes.EV_KEY, ecodes.BTN_LEFT, 1),
        "syn",
        (ecodes.EV_KEY, ecodes.BTN_LEFT, 0),
        "syn",
    ]
    backend.close()
    assert device.events[-1] == "close"


def test_virtual_pointer_releases_after_flush_error() -> None:
    class FailingSynDevice(FakePointerDevice):
        def syn(self) -> None:
            self.events.append("syn")
            if self.events.count("syn") == 3:
                raise OSError("input flush failed")

    device = FailingSynDevice()
    backend = VirtualPointerBackend(FakeDesktopGui(), device=device, press_delay_s=0)
    with pytest.raises(OSError, match="input flush failed"):
        backend.click(125, 135)
    assert (ecodes.EV_KEY, ecodes.BTN_LEFT, 0) in device.events
