"""Conservative visual checks when a step has no explicit expectation."""

import re
from io import BytesIO
from typing import Literal

import cv2
import numpy as np
from ollama import Client
from PIL import Image, ImageChops
from pydantic import BaseModel, ConfigDict, Field

from vibana_agent.config import Settings
from vibana_agent.perception import resize_for_model
from vibana_agent.schema import Evidence


class GoalAssessment(BaseModel):
    """Structured vision judgment about a completed UI instruction."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["met", "unmet", "uncertain"]
    evidence: str = Field(min_length=1)


def _scroll_direction(
    instruction: str,
) -> Literal["up", "down", "left", "right"] | None:
    """Return the requested scroll direction, when the instruction names one."""
    match = re.search(
        r"\bscroll\s+(up|down|left|right)\b", instruction, re.IGNORECASE
    )
    if match is None:
        return None
    directions: dict[str, Literal["up", "down", "left", "right"]] = {
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
    }
    return directions[match.group(1).casefold()]


def _scroll_evidence(
    before: bytes,
    after: bytes,
    direction: Literal["up", "down", "left", "right"],
) -> Evidence | None:
    """Verify scrolling from pixel movement in the scrollable screen region."""
    before_image = np.asarray(
        Image.open(BytesIO(before)).convert("L"), dtype=np.float32
    )
    after_image = np.asarray(
        Image.open(BytesIO(after)).convert("L"), dtype=np.float32
    )
    if before_image.shape != after_image.shape:
        return None

    height, width = before_image.shape
    x_start = round(width * 0.25)
    x_end = round(width * 0.98)
    y_start = round(height * 0.2)
    y_end = round(height * 0.9)
    before_region = before_image[y_start:y_end, x_start:x_end]
    after_region = after_image[y_start:y_end, x_start:x_end]
    (shift_x, shift_y), response = cv2.phaseCorrelate(
        before_region, after_region
    )

    horizontal = direction in {"left", "right"}
    extent = width if horizontal else height
    shift = shift_x if horizontal else shift_y
    expected_sign = 1 if direction in {"up", "left"} else -1
    minimum_shift = max(12.0, extent * 0.015)
    if response < 0.1:
        return None
    if abs(shift) < minimum_shift:
        return Evidence(
            matched=False,
            observed_text=(
                "screen content did not move far enough to confirm scrolling"
            ),
            source="vision",
        )
    if shift * expected_sign < minimum_shift:
        movement = "right" if horizontal and shift > 0 else "left"
        if not horizontal:
            movement = "down" if shift > 0 else "up"
        return Evidence(
            matched=False,
            observed_text=(
                f"screen content shifted {movement} by about "
                f"{abs(round(shift))} pixels, opposite the requested scroll"
            ),
            source="vision",
        )

    movements: dict[Literal["up", "down", "left", "right"], str] = {
        "up": "down",
        "down": "up",
        "left": "right",
        "right": "left",
    }
    movement = movements[direction]
    return Evidence(
        matched=True,
        observed_text=(
            f"screen content shifted {movement} by about "
            f"{abs(round(shift))} pixels after scrolling {direction}"
        ),
        source="vision",
    )


def parse_goal_assessment(content: str) -> GoalAssessment:
    """Parse a model answer and reject missing or ambiguous evidence."""
    assessment = GoalAssessment.model_validate_json(content)
    if not assessment.evidence.strip():
        raise ValueError("visual assessment has no evidence")
    return assessment


class OllamaGoalVerifier:
    """Compare fresh before and after screenshots with a vision model."""

    def verify(
        self, before: bytes, after: bytes, instruction: str, settings: Settings
    ) -> Evidence:
        """Return positive evidence only when a visible change proves the goal."""
        direction = _scroll_direction(instruction)
        if direction is not None:
            scroll_evidence = _scroll_evidence(before, after, direction)
            if scroll_evidence is not None:
                return scroll_evidence

        before_image = Image.open(BytesIO(before)).convert("RGB")
        after_image = Image.open(BytesIO(after)).convert("RGB")
        if before_image.size != after_image.size:
            return Evidence(
                matched=False,
                observed_text="screen size changed; goal uncertain",
                source="vision",
            )
        if ImageChops.difference(before_image, after_image).getbbox() is None:
            return Evidence(
                matched=False,
                observed_text="screen did not change",
                source="vision",
            )
        before_model, _ = resize_for_model(before)
        after_model, _ = resize_for_model(after)
        prompt = (
            "The first image is BEFORE one UI action. The second image is AFTER. "
            f"Instruction: {instruction}. Decide whether the visible result now "
            "proves this instruction is complete. Return status=met only with "
            "specific visual evidence from the AFTER image. For an instruction "
            "that asks only to click a named tab or control, mark it met when that "
            "target is visibly active, selected, or focused; do not require its "
            "contents to change as well. Return unmet if the goal is visibly "
            "unfinished, or uncertain if it cannot be proved. "
            "For scrolling, compare the same visible page text before and after: "
            "content moving up proves a downward scroll, and content moving down "
            "proves an upward scroll. Do not report unchanged content when text "
            "has visibly moved. Never infer completion solely from a changed "
            "screen or an input event."
        )
        response = Client(timeout=settings.model_timeout_s).chat(
            model=settings.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [before_model, after_model],
                }
            ],
            format=GoalAssessment.model_json_schema(),
            options={
                "num_ctx": settings.num_ctx,
                "temperature": 0,
                "seed": settings.seed,
            },
            stream=False,
        )
        assessment = parse_goal_assessment(response.message.content or "")
        return Evidence(
            matched=assessment.status == "met",
            observed_text=assessment.evidence,
            source="vision",
        )
