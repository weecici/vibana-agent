"""Opt-in delivery checks against a disposable real desktop window."""

import os
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

from vibana_agent.desktop import GrimCapture, X11Capture
from vibana_agent.executor import DesktopExecutor
from vibana_agent.schema import Action, Box

pytestmark = pytest.mark.skipif(
    os.environ.get("VIBANA_TEST_LIVE_DESKTOP") != "1",
    reason="set VIBANA_TEST_LIVE_DESKTOP=1 to open a disposable input test window",
)


def color_center(screenshot: bytes, color: str) -> tuple[int, int]:
    """Find the center of a fixture marker in physical screenshot pixels."""
    image = Image.open(BytesIO(screenshot)).convert("RGB")
    difference = ImageChops.difference(image, Image.new("RGB", image.size, color))
    red, green, blue = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    bounds = distance.point(lambda value: 255 if value == 0 else 0).getbbox()
    assert bounds is not None, "the disposable window must be visible on screen"
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def test_live_keyboard_and_scroll_delivery(tmp_path: Path) -> None:
    """Actual uinput delivery must preserve full text, Enter and wheel direction."""
    fixture = tmp_path / "desktop-input.html"
    fixture.write_text(
        """<!doctype html>
        <title>Vibana disposable desktop input test</title>
        <h1>Vibana input regression test</h1>
        <form id="form">
          <input id="query" autocomplete="off"
            style="background:#12ab34;width:95%;font-size:24px">
        </form>
        <p id="submitted">Waiting for Enter</p>
        <div id="pane" style="overflow:auto;width:95%;height:180px">
          <div style="width:2000px;height:2000px;background:#3456ab"></div>
        </div>
        <script>
        window.submissions = [];
        window.events = [];
        for (const kind of ['keydown', 'keyup']) {
          document.addEventListener(kind, e => window.events.push(
            [kind, e.key, e.repeat, performance.now()]
          ));
        }
        document.querySelector('#form').onsubmit = e => {
          e.preventDefault();
          window.submissions.push(document.querySelector('#query').value);
          document.querySelector('#submitted').textContent = 'Submitted';
        };
        </script>
        """,
        encoding="utf-8",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page(viewport={"width": 700, "height": 500})
            page.goto(fixture.as_uri())
            page.bring_to_front()
            capture = (
                GrimCapture()
                if os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
                else X11Capture()
            )
            width, height = capture.size()
            executor = DesktopExecutor(Box(x=0, y=0, width=width, height=height))
            try:
                x, y = color_center(executor.capture(), "#12ab34")
                executor.perform(Action(kind="click", x=x, y=y))
                payloads = [
                    "How to become AI Engineer",
                    "How to become AI Engineer " * 20,
                ]
                for payload in payloads:
                    executor.capture()
                    executor.perform(Action(kind="key_press", key="Ctrl+A"))
                    executor.capture()
                    executor.perform(Action(kind="type_text", text=payload))
                    observed = page.locator("#query").input_value()
                    if observed != payload:
                        diagnostic = page.evaluate(
                            "JSON.stringify({submissions:window.submissions,events:window.events})"
                        )
                        (tmp_path / "keyboard-events.json").write_text(
                            diagnostic, encoding="utf-8"
                        )
                    assert observed == payload, tmp_path
                    executor.capture()
                    executor.perform(Action(kind="key_press", key="Enter"))
                    assert page.evaluate("window.submissions.at(-1)") == payload
                diagnostic = page.evaluate(
                    "JSON.stringify({submissions:window.submissions,events:window.events})"
                )
                (tmp_path / "keyboard-events.json").write_text(
                    diagnostic, encoding="utf-8"
                )
                assert page.evaluate("window.submissions") == payloads, tmp_path

                for direction, axis, comparison in (
                    ("down", "scrollTop", "> 0"),
                    ("up", "scrollTop", "=== 0"),
                    ("right", "scrollLeft", "> 0"),
                    ("left", "scrollLeft", "=== 0"),
                ):
                    x, y = color_center(executor.capture(), "#3456ab")
                    executor.perform(
                        Action.model_validate(
                            {
                                "kind": "scroll",
                                "x": x,
                                "y": y,
                                "direction": direction,
                                "ticks": 3,
                            }
                        )
                    )
                    page.wait_for_function(
                        f"document.querySelector('#pane').{axis} {comparison}"
                    )
            finally:
                executor.close()
        finally:
            browser.close()
