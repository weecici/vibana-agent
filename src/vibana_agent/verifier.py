"""Conservative visual checks when a step has no explicit expectation."""

from io import BytesIO
from typing import Literal

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
            "The first image is BEFORE a single click. The second image is AFTER. "
            f"Instruction: {instruction}. Decide whether the visible result now "
            "proves this instruction is complete. Return status=met only with "
            "specific visual evidence from the AFTER image. For an instruction "
            "that asks only to click a named tab or control, mark it met when that "
            "target is visibly active, selected, or focused; do not require its "
            "contents to change as well. Return unmet if the goal is visibly "
            "unfinished, or uncertain if it cannot be proved. "
            "Never infer completion solely from a changed screen or the click."
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
