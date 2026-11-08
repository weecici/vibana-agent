"""OCR behavior on the real visual fixture."""

from pathlib import Path

from playwright.sync_api import sync_playwright

from vibana_agent.perception import perceive


def test_ocr_detects_settings_on_mock_screenshot() -> None:
    """The agent sees a Settings candidate from screenshot pixels."""
    path = Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(path.as_uri())
            screenshot = page.screenshot(scale="css")
        finally:
            browser.close()
    assert any("Settings" in (candidate.text or "") for candidate in perceive(screenshot))
