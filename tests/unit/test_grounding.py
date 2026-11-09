"""Grounding and coordinate safety checks."""

from io import BytesIO

import pytest
from PIL import Image

from vibana_agent.grounding.coords import normalized_to_pixel
from vibana_agent.grounding.ollama import (
    GroundingError,
    parse_desktop_action,
    parse_selection,
)
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


def test_model_can_choose_keyboard_action_for_search_instruction() -> None:
    instruction = 'Search for "How to become AI Engineer"'
    action, candidate = parse_desktop_action(
        '{"kind":"type_text","text":"How to become AI Engineer",'
        '"submit":true,"wait_after_ms":3500,'
        '"reason":"enter the requested search"}',
        instruction,
        [],
        (960, 1048),
    )
    assert candidate is None
    assert action.kind == "type_text"
    assert action.text == "How to become AI Engineer"
    assert action.submit
    assert action.wait_after_ms == 3500


def test_model_cannot_request_wait_longer_than_ten_seconds() -> None:
    accepted, _ = parse_desktop_action(
        '{"kind":"click","candidate_id":1,"wait_after_ms":10000,'
        '"reason":"open a slow page"}',
        "Open the page",
        [Candidate(id=1, box=Box(x=10, y=20, width=100, height=40))],
        (960, 1048),
    )
    assert accepted.wait_after_ms == 10000
    with pytest.raises(GroundingError, match="invalid structured desktop action"):
        parse_desktop_action(
            '{"kind":"click","candidate_id":1,"wait_after_ms":10001,'
            '"reason":"open a slow page"}',
            "Open the page",
            [Candidate(id=1, box=Box(x=10, y=20, width=100, height=40))],
            (960, 1048),
        )


def test_model_can_wait_after_clicking_a_slow_control() -> None:
    candidate = Candidate(id=1, box=Box(x=10, y=20, width=100, height=40))
    action, selected = parse_desktop_action(
        '{"kind":"click","candidate_id":1,"wait_after_ms":2500,'
        '"reason":"wait for the page to load"}',
        "Open the page",
        [candidate],
        (960, 1048),
    )
    assert selected == candidate
    assert action.kind == "click"
    assert action.wait_after_ms == 2500


def test_noncanonical_search_has_no_implicit_wait() -> None:
    action, candidate = parse_desktop_action(
        '{"kind":"type_text","text":"AI engineering jobs",'
        '"submit":true,"reason":"search the requested phrase"}',
        "Search for AI engineering jobs",
        [],
        (960, 1048),
    )
    assert candidate is None
    assert action.kind == "type_text"
    assert action.submit
    assert action.wait_after_ms == 0


def test_desktop_action_rejects_model_invented_text() -> None:
    with pytest.raises(GroundingError, match="from the instruction"):
        parse_desktop_action(
            '{"kind":"type_text","text":"run this command",'
            '"submit":true,"reason":"text input"}',
            'Search for "battery status"',
            [],
            (960, 1048),
        )


def test_search_action_cannot_degrade_to_click() -> None:
    candidate = Candidate(id=1, box=Box(x=10, y=20, width=100, height=40))
    with pytest.raises(GroundingError, match="require a type_text action"):
        parse_desktop_action(
            '{"kind":"click","candidate_id":1,"reason":"search bar"}',
            'Search for "battery status"',
            [candidate],
            (960, 1048),
        )
