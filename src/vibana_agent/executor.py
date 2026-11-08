"""Safe local screenshot and click backends."""

import logging
import os
import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from PIL import Image, ImageChops
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
    Route,
    sync_playwright,
)

from vibana_agent.desktop import (
    DesktopGui,
    GrimCapture,
    VirtualPointerBackend,
    X11Capture,
)
from vibana_agent.schema import Action, Box, Candidate

logger = logging.getLogger(__name__)
_DESKTOP_STABILITY_RADIUS_PX = 32


class SafetyError(ValueError):
    """An action violates the local prototype's input policy."""


class DesktopExecutor:
    """Linux desktop executor restricted to a selected screen region."""

    def __init__(
        self,
        region: Box,
        gui: DesktopGui | None = None,
        session_type: str | None = None,
    ) -> None:
        session = session_type or os.environ.get("XDG_SESSION_TYPE", "")
        if not sys.platform.startswith("linux"):
            raise SafetyError("desktop control requires Linux")
        if session.casefold() not in {"x11", "wayland"}:
            raise SafetyError("desktop control requires X11 or Wayland")
        if gui is not None:
            self._gui = gui
        elif session.casefold() == "wayland":
            self._gui = VirtualPointerBackend(GrimCapture())
        else:
            self._gui = VirtualPointerBackend(X11Capture())
        screen_width, screen_height = self._gui.size()
        if (
            region.x + region.width > screen_width
            or region.y + region.height > screen_height
        ):
            self._gui.close()
            raise SafetyError("desktop region is outside the primary screen")
        self._region = region
        self._before: Image.Image | None = None

    def _screenshot(self) -> Image.Image:
        return self._gui.screenshot(
            (
                self._region.x,
                self._region.y,
                self._region.width,
                self._region.height,
            )
        ).convert("RGB")

    def capture(self) -> bytes:
        """Capture the chosen desktop region in local screenshot pixels."""
        image = self._screenshot()
        self._before = image
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def perform(self, action: Action) -> None:
        """Inject a validated input after a fresh screenshot."""
        if action.kind in {"click", "scroll"} and (
            action.x is None
            or action.y is None
            or not (
                0 <= action.x < self._region.width
                and 0 <= action.y < self._region.height
            )
        ):
            raise SafetyError("pointer is outside the desktop region")
        if self._before is None:
            raise SafetyError("a fresh screenshot is required before input")
        if action.kind in {"click", "scroll"}:
            assert action.x is not None and action.y is not None
            current = self._screenshot()
            radius = _DESKTOP_STABILITY_RADIUS_PX
            target_bounds = (
                max(0, action.x - radius),
                max(0, action.y - radius),
                min(self._region.width, action.x + radius + 1),
                min(self._region.height, action.y + radius + 1),
            )
            before_target = self._before.crop(target_bounds)
            current_target = current.crop(target_bounds)
            if (
                ImageChops.difference(before_target, current_target).getbbox()
                is not None
            ):
                raise SafetyError("desktop target changed before the input")
            x = self._region.x + action.x
            y = self._region.y + action.y
            if action.kind == "click":
                self._gui.click(x, y)
            else:
                assert action.direction is not None and action.ticks is not None
                self._gui.scroll(x, y, action.direction, action.ticks)
        elif action.kind == "type_text":
            assert action.text is not None
            self._gui.type_text(action.text)
        else:
            assert action.key is not None
            try:
                self._gui.key_press(action.key)
            except ValueError as error:
                raise SafetyError(str(error)) from error
        self._before = None

    def viewport(self) -> tuple[int, int]:
        """Return the selected region dimensions in local screenshot pixels."""
        return self._region.width, self._region.height

    def close(self) -> None:
        """Release the cached screenshot and virtual input device."""
        self._before = None
        self._gui.close()


class Executor(Protocol):
    """Capture and act in screenshot pixel coordinates."""

    def capture(self) -> bytes:
        """Return a PNG in local viewport pixels (CSS on browser targets)."""
        ...

    def perform(self, action: Action) -> None:
        """Perform a validated action in local viewport pixels."""
        ...

    def viewport(self) -> tuple[int, int]:
        """Return viewport width and height in local pixels."""
        ...

    def close(self) -> None:
        """Release browser or replay resources."""
        ...


_ALLOWED_INSTRUCTIONS = frozenset(
    {"Open Settings", "Open Display", "Set brightness to 70%", "Return Home"}
)


def validate_action(
    action: Action,
    viewport: tuple[int, int],
    instruction: str,
    candidate: Candidate | None,
    allow_unlisted: bool = False,
) -> None:
    """Reject pointer input outside the chosen region or safe workflow."""
    if not allow_unlisted and instruction not in _ALLOWED_INSTRUCTIONS:
        raise SafetyError("instruction is not allowed in the local prototype")
    if not allow_unlisted and action.kind != "click":
        raise SafetyError("non-click actions require a desktop target")
    width, height = viewport
    if action.kind in {"click", "scroll"}:
        assert action.x is not None and action.y is not None
        if not (0 <= action.x < width and 0 <= action.y < height):
            raise SafetyError("pointer is outside the viewport")
        if action.kind == "click":
            if candidate is None:
                raise SafetyError("click requires a visible candidate")
            box = candidate.box
            if not (
                box.x <= action.x < box.x + box.width
                and box.y <= action.y < box.y + box.height
            ):
                raise SafetyError("click is outside the chosen candidate")


class MockBrowserExecutor:
    """Headless Chromium executor restricted to the bundled HMI page."""

    def __init__(self, path: Path, seed: int = 0) -> None:
        expected = Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html"
        if path.resolve() != expected.resolve():
            raise SafetyError("only the bundled mock HMI may receive clicks")
        self._root = expected.parent.resolve()
        playwright: Playwright | None = None
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720}, device_scale_factor=1
            )
            context.set_default_timeout(30_000)
            context.route("**/*", self._route)
            page = context.new_page()
            page.goto(f"{expected.as_uri()}?seed={seed}", timeout=30_000)
        except Exception:
            try:
                self._release(context, browser, playwright)
            except Exception:
                logger.exception("browser cleanup failed after startup error")
            raise
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._page = page

    @staticmethod
    def _release(
        context: BrowserContext | None,
        browser: Browser | None,
        playwright: Playwright | None,
    ) -> None:
        releases: list[Callable[[], None]] = []
        if context is not None:
            releases.append(context.close)
        if browser is not None:
            releases.append(browser.close)
        if playwright is not None:
            releases.append(playwright.stop)
        errors: list[Exception] = []
        for release in releases:
            try:
                release()
            except Exception as error:
                errors.append(error)
                logger.exception("browser resource cleanup failed")
        if errors:
            raise errors[0]

    def _route(self, route: Route) -> None:
        parsed = urlparse(route.request.url)
        resource = Path(unquote(parsed.path)).resolve()
        if parsed.scheme == "file" and resource.is_relative_to(self._root):
            route.continue_()
        else:
            route.abort()

    def capture(self) -> bytes:
        """Capture the current local HMI viewport in CSS pixels."""
        return self._page.screenshot(scale="css", timeout=30_000)

    def perform(self, action: Action) -> None:
        """Click inside the local viewport in CSS pixels."""
        if action.kind != "click":
            raise SafetyError("mock HMI supports clicks only")
        assert action.x is not None and action.y is not None
        width, height = self.viewport()
        if not (0 <= action.x < width and 0 <= action.y < height):
            raise SafetyError("click is outside the viewport")
        self._page.mouse.click(action.x, action.y)

    def viewport(self) -> tuple[int, int]:
        """Return the browser viewport in CSS pixels."""
        size = self._page.viewport_size
        if size is None:
            raise RuntimeError("browser viewport is unavailable")
        return size["width"], size["height"]

    def close(self) -> None:
        """Release the browser and Playwright driver."""
        self._release(self._context, self._browser, self._playwright)


class ReplayExecutor:
    """Read-only offline screenshot sequence."""

    def __init__(self, images: list[Path]) -> None:
        self._images = images
        self._index = 0

    def capture(self) -> bytes:
        """Return the next replay PNG without any live UI access."""
        if self._index >= len(self._images):
            raise RuntimeError("replay screenshots exhausted")
        image = self._images[self._index].read_bytes()
        self._index += 1
        return image

    def perform(self, action: Action) -> None:
        """Reject every live action on a replay target."""
        raise SafetyError("replay is read-only")

    def viewport(self) -> tuple[int, int]:
        """Return the next replay image dimensions in pixels."""
        if self._index >= len(self._images):
            raise RuntimeError("replay screenshots exhausted")
        with Image.open(self._images[self._index]) as image:
            return image.size

    def close(self) -> None:
        """Release replay resources (none are held)."""
