"""Structured Ollama candidate selection."""

import logging
import re
from typing import Literal

from ollama import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vibana_agent.config import Settings
from vibana_agent.perception import draw_candidates, resize_for_model
from vibana_agent.schema import (
    Action,
    Candidate,
    KeyPressSpec,
    ScrollSpec,
    TypeTextSpec,
)

logger = logging.getLogger(__name__)


class GroundingError(ValueError):
    """A model answer cannot safely select a visible candidate."""


class Selection(BaseModel):
    """Validated model choice of a numbered on-screen candidate."""

    model_config = ConfigDict(strict=True, extra="forbid")

    candidate_id: int | None
    reason: str


class DesktopActionSelection(BaseModel):
    """Validated model proposal for one desktop input action."""

    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal["click", "scroll", "type_text", "key_press"]
    candidate_id: int | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    ticks: int | None = Field(default=None, ge=1, le=20)
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    text: str | None = None
    submit: bool = False
    wait_after_ms: int = Field(default=0, ge=0, le=10_000)
    key: str | None = None
    reason: str


def parse_selection(content: str, candidates: list[Candidate]) -> Candidate:
    """Accept only a candidate ID present in the current screenshot."""
    candidate, _ = _parse_selection(content, candidates)
    return candidate


def parse_desktop_action(
    content: str,
    instruction: str,
    candidates: list[Candidate],
    viewport: tuple[int, int],
) -> tuple[Action, Candidate | None]:
    """Validate one model-selected desktop action against its instruction."""
    try:
        selection = DesktopActionSelection.model_validate_json(content)
    except ValidationError as error:
        raise GroundingError("invalid structured desktop action") from error

    search = re.fullmatch(
        r"search\s+for\s+(['\"])(.+?)\1", instruction.strip(), re.IGNORECASE
    )
    if search is not None and selection.kind != "type_text":
        raise GroundingError("search instructions require a type_text action")

    if selection.kind == "click":
        candidate = next(
            (item for item in candidates if item.id == selection.candidate_id), None
        )
        if candidate is None:
            raise GroundingError("model chose no visible click candidate")
        return (
            Action(
                kind="click",
                x=candidate.box.x + candidate.box.width // 2,
                y=candidate.box.y + candidate.box.height // 2,
                instruction=instruction,
                target_label=candidate.text,
                wait_after_ms=selection.wait_after_ms,
            ),
            candidate,
        )

    if selection.candidate_id is not None:
        raise GroundingError("non-click desktop actions cannot select a candidate")
    if selection.kind == "scroll":
        if selection.direction is None:
            raise GroundingError("scroll action requires a direction")
        if (selection.x is None) != (selection.y is None):
            raise GroundingError("scroll position requires both x and y")
        width, height = viewport
        try:
            scroll = ScrollSpec(
                kind="scroll",
                direction=selection.direction,
                ticks=selection.ticks or 1,
                x=selection.x,
                y=selection.y,
            )
        except ValidationError as error:
            raise GroundingError("invalid scroll action") from error
        return (
            Action(
                kind="scroll",
                x=scroll.x if scroll.x is not None else width // 2,
                y=scroll.y if scroll.y is not None else height // 2,
                direction=scroll.direction,
                ticks=scroll.ticks,
                wait_after_ms=selection.wait_after_ms,
                instruction=instruction,
            ),
            None,
        )
    if selection.kind == "type_text":
        if (
            selection.text is None
            or selection.text.casefold() not in instruction.casefold()
        ):
            raise GroundingError("typed text must come from the instruction")
        if search is not None and (
            selection.text != search.group(2) or not selection.submit
        ):
            raise GroundingError("search action must type and submit the quoted query")
        try:
            typed = TypeTextSpec(
                kind="type_text", text=selection.text, submit=selection.submit
            )
        except ValidationError as error:
            raise GroundingError("invalid typed text") from error
        return (
            Action(
                kind="type_text",
                text=typed.text,
                submit=typed.submit,
                wait_after_ms=selection.wait_after_ms,
                instruction=instruction,
            ),
            None,
        )
    if selection.key is None:
        raise GroundingError("key_press action requires a key")
    try:
        key_press = KeyPressSpec(kind="key_press", key=selection.key)
    except ValidationError as error:
        raise GroundingError("invalid key_press action") from error
    return (
        Action(
            kind="key_press",
            key=key_press.key,
            wait_after_ms=selection.wait_after_ms,
            instruction=instruction,
        ),
        None,
    )


def _parse_selection(
    content: str, candidates: list[Candidate]
) -> tuple[Candidate, str]:
    """Validate the candidate and retain its short visible-evidence rationale."""
    try:
        selection = Selection.model_validate_json(content)
    except ValidationError as error:
        raise GroundingError("invalid structured selection") from error
    for candidate in candidates:
        if candidate.id == selection.candidate_id:
            return candidate, selection.reason
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
        "Return candidate_id=null if uncertain. Do not invent an ID. "
        "Give a brief rationale based only on visible screenshot evidence."
    )
    response = Client(timeout=settings.model_timeout_s).chat(
        model=settings.model,
        messages=[{"role": "user", "content": prompt, "images": [model_image]}],
        format=Selection.model_json_schema(),
        options={"num_ctx": settings.num_ctx, "temperature": 0, "seed": settings.seed},
        stream=True,
    )
    response_parts: list[str] = []
    for chunk in response:
        content = chunk.message.content or ""
        if content:
            response_parts.append(content)
    candidate, reason = _parse_selection("".join(response_parts), candidates)
    logger.info(
        "Model chose candidate %s (%s): %s",
        candidate.id,
        candidate.text or "unlabeled region",
        reason,
    )
    return candidate


def plan_desktop_action(
    image: bytes,
    instruction: str,
    candidates: list[Candidate],
    settings: Settings,
    viewport: tuple[int, int],
) -> tuple[Action, Candidate | None]:
    """Ask the vision model to choose and validate a desktop input action."""
    overlay = draw_candidates(image, candidates)
    model_image, _ = resize_for_model(overlay)
    labels = "; ".join(
        f"{candidate.id}: {candidate.text or 'unlabeled region'}"
        for candidate in candidates
    )
    prompt = (
        "Choose one action for this desktop instruction: "
        f"{instruction}. Available visible click candidates: {labels}. "
        "Return kind=click and its current candidate_id for visible controls. "
        "Return kind=scroll with direction and ticks for scrolling. "
        "Return kind=type_text only when the instruction asks to search or type; "
        "copy the requested text exactly from the instruction and set submit=true "
        "when it asks to search. Return kind=key_press only for a requested key. "
        "Set wait_after_ms between 0 and 10000 when the action may trigger delayed "
        "UI updates; use 0 otherwise. Request a delay for searches only when needed. "
        "Do not invent text, candidate IDs, or actions. For scroll, omit x and y "
        "to use the viewport center. Give a brief rationale."
    )
    response = Client(timeout=settings.model_timeout_s).chat(
        model=settings.model,
        messages=[{"role": "user", "content": prompt, "images": [model_image]}],
        format=DesktopActionSelection.model_json_schema(),
        options={"num_ctx": settings.num_ctx, "temperature": 0, "seed": settings.seed},
        stream=True,
    )
    response_parts: list[str] = []
    for chunk in response:
        content = chunk.message.content or ""
        if content:
            response_parts.append(content)
    action, candidate = parse_desktop_action(
        "".join(response_parts), instruction, candidates, viewport
    )
    logger.info("Model chose desktop action %s: %s", action.kind, action.instruction)
    return action, candidate


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

    def plan(
        self,
        image: bytes,
        instruction: str,
        candidates: list[Candidate],
        settings: Settings,
        viewport: tuple[int, int],
    ) -> tuple[Action, Candidate | None]:
        """Select a validated click, scroll, text or key action for desktop."""
        return plan_desktop_action(image, instruction, candidates, settings, viewport)
