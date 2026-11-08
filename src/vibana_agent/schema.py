"""Validated inputs and outputs for the prototype."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vibana_agent.config import Settings


class StrictModel(BaseModel):
    """Base model that rejects unknown boundary fields."""

    model_config = ConfigDict(extra="forbid")


class Expectation(StrictModel):
    """Visible text required after an action."""

    text_visible: str = Field(min_length=1)


class ClickSpec(StrictModel):
    """Select and click a visible candidate."""

    kind: Literal["click"]


class ScrollSpec(StrictModel):
    """Scroll at a local screenshot point, defaulting to the region center."""

    kind: Literal["scroll"]
    direction: Literal["up", "down", "left", "right"]
    ticks: int = Field(default=1, ge=1, le=20)
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> "ScrollSpec":
        """Keep the optional local pixel position unambiguous."""
        if (self.x is None) != (self.y is None):
            raise ValueError("scroll x and y must be provided together")
        return self


class TypeTextSpec(StrictModel):
    """Type printable ASCII into the currently focused desktop control."""

    kind: Literal["type_text"]
    text: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_supported_text(self) -> "TypeTextSpec":
        """Reject characters unavailable through the virtual US keyboard."""
        if not self.text.isascii() or any(
            not (character.isprintable() or character in "\n\t")
            for character in self.text
        ):
            raise ValueError("type_text supports printable ASCII, newline and tab")
        return self


class KeyPressSpec(StrictModel):
    """Press one key or a modifier chord on the desktop."""

    kind: Literal["key_press"]
    key: str = Field(min_length=1, max_length=50)


StepAction = Annotated[
    ClickSpec | ScrollSpec | TypeTextSpec | KeyPressSpec, Field(discriminator="kind")
]


class Step(StrictModel):
    """A requested UI instruction with an optional visual postcondition."""

    instruction: str = Field(min_length=1)
    expect: Expectation | None = None
    action: StepAction | None = None


class Scenario(StrictModel):
    """A bounded local workflow."""

    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    target: Literal["hmi_mock", "replay", "desktop"]
    steps: list[Step] = Field(min_length=1)
    region: "Box | None" = None
    settings: Settings | None = None

    @model_validator(mode="after")
    def require_benchmark_expectations(self) -> "Scenario":
        """Keep explicit pass criteria for mock and replay benchmarks."""
        if self.target != "desktop" and any(step.expect is None for step in self.steps):
            raise ValueError("mock and replay steps require expect")
        if self.target != "desktop" and any(
            step.action is not None and step.action.kind != "click"
            for step in self.steps
        ):
            raise ValueError("non-click actions require a desktop target")
        return self


class Box(StrictModel):
    """Element rectangle in original screenshot pixels."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Candidate(StrictModel):
    """A visible UI region in original screenshot pixels."""

    id: int = Field(ge=1)
    box: Box
    text: str | None = None


class Action(StrictModel):
    """A bounded desktop or browser input in local screenshot pixels."""

    kind: Literal["click", "scroll", "type_text", "key_press"]
    x: int | None = None
    y: int | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    ticks: int | None = Field(default=None, ge=1, le=20)
    text: str | None = None
    key: str | None = None
    instruction: str | None = None
    target_label: str | None = None

    @model_validator(mode="after")
    def require_action_fields(self) -> "Action":
        """Require the arguments belonging to the chosen input kind."""
        if self.kind in {"click", "scroll"} and (self.x is None or self.y is None):
            raise ValueError("pointer action requires x and y")
        if self.kind == "scroll" and (self.direction is None or self.ticks is None):
            raise ValueError("scroll requires direction and ticks")
        if self.kind == "type_text" and not self.text:
            raise ValueError("type_text requires text")
        if self.kind == "type_text" and self.text is not None:
            TypeTextSpec(kind="type_text", text=self.text)
        if self.kind == "key_press" and not self.key:
            raise ValueError("key_press requires key")
        return self


class Evidence(StrictModel):
    """Post-action OCR or vision evidence from screenshot pixels."""

    matched: bool
    observed_text: str
    source: Literal["ocr", "vision"] = "ocr"


class Attempt(StrictModel):
    """One bounded action attempt and its visual evidence."""

    status: Literal["ACTION_ERROR", "EXECUTED"]
    candidate: Candidate | None = None
    action: Action | None = None
    strategy: Literal["candidate"] | None = None
    evidence: Evidence | None = None
    latency_ms: int = Field(ge=0)
    error: str | None = None


class StepResult(StrictModel):
    """Verdict and attempts for one scenario step."""

    instruction: str
    status: Literal["PASS", "FAIL", "ERROR", "SKIPPED"]
    attempts: list[Attempt]


class Report(StrictModel):
    """Validated run result."""

    scenario: str
    status: Literal["PASS", "FAIL", "INFRA_ERROR"]
    steps: list[StepResult]
    error: str | None = None


def load_scenario(path: Path) -> Scenario:
    """Read and validate a YAML scenario from ``path``."""
    data: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario.model_validate(data)
