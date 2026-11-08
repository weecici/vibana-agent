"""Validated inputs and outputs for the prototype."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model that rejects unknown boundary fields."""

    model_config = ConfigDict(extra="forbid")


class Expectation(StrictModel):
    """Visible text required after an action."""

    text_visible: str = Field(min_length=1)


class Step(StrictModel):
    """A requested UI instruction and its visual postcondition."""

    instruction: str = Field(min_length=1)
    expect: Expectation


class Scenario(StrictModel):
    """A bounded local workflow."""

    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    target: Literal["hmi_mock", "replay"]
    steps: list[Step] = Field(min_length=1)


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
    """A click point in original screenshot pixels."""

    kind: Literal["click"]
    x: int
    y: int


class Evidence(StrictModel):
    """Text read from a post-action screenshot."""

    matched: bool
    observed_text: str


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
