"""Visual verification for steps without authored expectations."""

from io import BytesIO

import pytest
from PIL import Image

from vibana_agent.config import Settings
from vibana_agent.verifier import OllamaGoalVerifier, parse_goal_assessment


def png(color: str) -> bytes:
    """Create a small screenshot in PNG bytes."""
    output = BytesIO()
    Image.new("RGB", (20, 20), color).save(output, format="PNG")
    return output.getvalue()


def test_unchanged_screen_cannot_verify_goal() -> None:
    verifier = OllamaGoalVerifier()
    evidence = verifier.verify(png("red"), png("red"), "Open Settings", Settings())
    assert evidence.matched is False
    assert evidence.source == "vision"


def test_visual_assessment_rejects_malformed_answer() -> None:
    with pytest.raises(ValueError):
        parse_goal_assessment('{"status": "met", "evidence": ""}')
    with pytest.raises(ValueError):
        parse_goal_assessment('{"status": "maybe", "evidence": "Settings"}')
