"""Browser checks for the local demonstration fixture."""

from pathlib import Path

from playwright.sync_api import sync_playwright

MOCK_URL = (Path(__file__).resolve().parents[2] / "hmi_mock" / "index.html").as_uri()


def test_mock_workflow_and_shift() -> None:
    """Both layouts expose the same safe four-step workflow."""
    positions: list[float] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for seed in (0, 1):
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(f"{MOCK_URL}?seed={seed}")
                assert page.get_by_text("Home", exact=True).is_visible()
                settings = page.get_by_role("button", name="Settings")
                box = settings.bounding_box()
                assert box is not None
                positions.append(box["x"])
                settings.click()
                assert page.get_by_role("button", name="Display").is_visible()
                page.get_by_role("button", name="Display").click()
                assert page.get_by_text("Brightness", exact=True).is_visible()
                for expected in ("50%", "60%", "70%"):
                    page.get_by_role("button", name="Increase brightness").click()
                    assert page.get_by_text(expected, exact=True).is_visible()
                page.get_by_role("button", name="Return Home").click()
                assert page.get_by_text("Home", exact=True).is_visible()
                page.close()
        finally:
            browser.close()
    assert positions[0] != positions[1]
