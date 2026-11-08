"""Candidate budgets include OCR text and visual regions."""

from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from vibana_agent import perception
from vibana_agent.config import Settings
from vibana_agent.schema import Box


def test_candidate_limit_can_exceed_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured budget preserves candidates beyond the old 40 item cap."""
    boxes = [
        (Box(x=index * 10, y=0, width=5, height=5), str(index)) for index in range(55)
    ]
    monkeypatch.setattr(perception, "_ocr_boxes", lambda image: boxes)
    monkeypatch.setattr(perception, "_region_boxes", lambda image: [])
    buffer = BytesIO()
    Image.new("RGB", (600, 20)).save(buffer, format="PNG")

    assert len(perception.perceive(buffer.getvalue())) == 40
    assert len(perception.perceive(buffer.getvalue(), max_candidates=50)) == 50
    assert len(perception.perceive(buffer.getvalue(), max_candidates=60)) == 55


def test_candidate_limit_setting_requires_positive_value() -> None:
    with pytest.raises(ValidationError):
        Settings(max_candidates=0)
    assert Settings(max_candidates=60).max_candidates == 60
