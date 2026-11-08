"""Structured Ollama candidate selection."""

from ollama import Client
from pydantic import BaseModel, ConfigDict, ValidationError

from vibana_agent.config import Settings
from vibana_agent.perception import draw_candidates, resize_for_model
from vibana_agent.schema import Candidate


class GroundingError(ValueError):
    """A model answer cannot safely select a visible candidate."""


class Selection(BaseModel):
    """Validated model choice of a numbered on-screen candidate."""

    model_config = ConfigDict(strict=True, extra="forbid")

    candidate_id: int | None
    reason: str


def parse_selection(content: str, candidates: list[Candidate]) -> Candidate:
    """Accept only a candidate ID present in the current screenshot."""
    try:
        selection = Selection.model_validate_json(content)
    except ValidationError as error:
        raise GroundingError("invalid structured selection") from error
    for candidate in candidates:
        if candidate.id == selection.candidate_id:
            return candidate
    raise GroundingError("model chose no visible candidate")


def select_candidate(
    image: bytes,
    instruction: str,
    candidates: list[Candidate],
    settings: Settings,
) -> Candidate:
    """Choose a visible region from numbered screenshot boxes."""
    if not candidates:
        raise GroundingError("no visible candidates")
    overlay = draw_candidates(image, candidates)
    model_image, _ = resize_for_model(overlay)
    labels = "; ".join(
        f"{candidate.id}: {candidate.text or 'unlabeled region'}"
        for candidate in candidates
    )
    prompt = (
        "Choose the one visible numbered region to click for this instruction: "
        f"{instruction}. Candidate OCR: {labels}. "
        "Return candidate_id=null if uncertain. Do not invent an ID."
    )
    response = Client(timeout=settings.model_timeout_s).chat(
        model=settings.model,
        messages=[{"role": "user", "content": prompt, "images": [model_image]}],
        format=Selection.model_json_schema(),
        options={"num_ctx": settings.num_ctx, "temperature": 0, "seed": settings.seed},
        stream=False,
    )
    return parse_selection(response.message.content or "", candidates)


class OllamaSelector:
    """Candidate-selector adapter for the local Ollama vision model."""

    def select(
        self,
        image: bytes,
        instruction: str,
        candidates: list[Candidate],
        settings: Settings,
    ) -> Candidate:
        """Return a validated candidate from the current screenshot."""
        return select_candidate(image, instruction, candidates, settings)
