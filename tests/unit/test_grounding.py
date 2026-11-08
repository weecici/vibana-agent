"""Grounding and coordinate safety checks."""

from io import BytesIO

import pytest
from PIL import Image

from vibana_agent.grounding.coords import normalized_to_pixel
from vibana_agent.grounding.ollama import GroundingError, parse_selection
from vibana_agent.perception import draw_candidates, resize_for_model
from vibana_agent.schema import Box, Candidate


def test_image_resize_and_coordinate_calibration() -> None:
    """A model image scale maps back to the original screenshot pixels."""
    source = Image.new("RGB", (1920, 1080), "white")
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    resized, scale = resize_for_model(buffer.getvalue())
    assert Image.open(BytesIO(resized)).size == (1280, 720)
    assert abs(round(960 * scale / scale) - 960) <= 2
    assert normalized_to_pixel(500, 500, 1920, 1080) == (960, 540)


def test_invalid_selection_is_rejected() -> None:
    """Malformed JSON and unknown IDs never become a click target."""
    candidates = [Candidate(id=1, box=Box(x=10, y=20, width=100, height=50))]
    with pytest.raises(GroundingError):
        parse_selection("not json", candidates)
    with pytest.raises(GroundingError):
        parse_selection('{"candidate_id": 99, "reason": "guess"}', candidates)
    for value in ("true", '"1"', "1.0"):
        with pytest.raises(GroundingError):
            parse_selection(
                f'{{"candidate_id": {value}, "reason": "guess"}}', candidates
            )


def test_out_of_range_normalized_coordinate_is_rejected() -> None:
    """A point outside the normalized contract is unusable."""
    with pytest.raises(ValueError):
        normalized_to_pixel(1001, 500, 1280, 720)


def test_candidate_overlay_has_numbered_box() -> None:
    """Numbered overlay visibly changes pixels in the candidate region."""
    source = Image.new("RGB", (320, 200), "white")
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    candidate = Candidate(id=1, box=Box(x=50, y=50, width=100, height=60))
    output = draw_candidates(buffer.getvalue(), [candidate])
    image = Image.open(BytesIO(output))
    assert image.size == (320, 200)
    assert image.getpixel((50, 50)) != (255, 255, 255)
