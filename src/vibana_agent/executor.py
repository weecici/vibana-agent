"""Safe local screenshot and click backends."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from PIL import Image
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
    Route,
    sync_playwright,
)

from vibana_agent.schema import Action, Candidate

logger = logging.getLogger(__name__)


class SafetyError(ValueError):
    """An action violates the local prototype's click policy."""


class Executor(Protocol):
    """Capture and act in screenshot pixel coordinates."""

    def capture(self) -> bytes:
        """Return a PNG of the current viewport in CSS pixels."""
        ...

    def perform(self, action: Action) -> None:
        """Perform a validated action in CSS pixels."""
        ...

    def viewport(self) -> tuple[int, int]:
        """Return viewport width and height in CSS pixels."""
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
    candidate: Candidate,
) -> None:
    """Reject clicks outside the chosen region or the local safe workflow."""
    if instruction not in _ALLOWED_INSTRUCTIONS:
        raise SafetyError("instruction is not allowed in the local prototype")
    width, height = viewport
    if not (0 <= action.x < width and 0 <= action.y < height):
        raise SafetyError("click is outside the viewport")
    box = candidate.box
    if not (
        box.x <= action.x < box.x + box.width and box.y <= action.y < box.y + box.height
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
