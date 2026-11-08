"""Validated inputs and outputs for the prototype."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown boundary fields."""

    model_config = ConfigDict(extra="forbid")


class Expectation(StrictModel):
    """Visible text required after an action."""

    text_visible: str = Field(min_length=1)


class Step(StrictModel):
    """A requested UI instruction with an optional visual postcondition."""

    instruction: str = Field(min_length=1)
    expect: Expectation | None = None


class Scenario(StrictModel):
    """A bounded local workflow."""

    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    target: Literal["hmi_mock", "replay", "desktop"]
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def require_benchmark_expectations(self) -> "Scenario":
        """Keep explicit pass criteria for mock and replay benchmarks."""
        if self.target != "desktop" and any(step.expect is None for step in self.steps):
            raise ValueError("mock and replay steps require expect")
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
    """A click point in original screenshot pixels."""

    kind: Literal["click"]
    x: int
    y: int
    instruction: str | None = None
    target_label: str | None = None


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
