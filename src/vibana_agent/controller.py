"""Bounded screenshot-driven workflow controller."""

import logging
import re
from io import BytesIO
from time import monotonic
from typing import Literal, Protocol

from PIL import Image, ImageDraw
from pydantic import ValidationError

from vibana_agent.config import Settings
from vibana_agent.executor import Executor, SafetyError, validate_action
from vibana_agent.grounding.ollama import GroundingError
from vibana_agent.perception import draw_candidates, perceive
from vibana_agent.schema import (
    Action,
    Attempt,
    Candidate,
    KeyPressSpec,
    Evidence,
    Report,
    Scenario,
    ScrollSpec,
    StepResult,
    TypeTextSpec,
)

logger = logging.getLogger(__name__)


def _infer_desktop_action(
    instruction: str,
) -> ScrollSpec | TypeTextSpec | KeyPressSpec | None:
    text = instruction.strip()
    lowered = text.casefold()
    try:
        if lowered.startswith("scroll "):
            match = re.fullmatch(
                r"scroll\s+(up|down|left|right)(?:\s+(\d+)(?:\s+ticks?)?)?",
                text,
                flags=re.IGNORECASE,
            )
            if match is None:
                raise SafetyError("use 'scroll down 3 ticks' syntax")
            directions: dict[str, Literal["up", "down", "left", "right"]] = {
                "up": "up",
                "down": "down",
                "left": "left",
                "right": "right",
            }
            return ScrollSpec(
                kind="scroll",
                direction=directions[match.group(1).casefold()],
                ticks=int(match.group(2) or "1"),
            )
        if lowered.startswith("type:"):
            return TypeTextSpec(kind="type_text", text=text.partition(":")[2].strip())
        if lowered.startswith("press "):
            return KeyPressSpec(kind="key_press", key=text[6:].strip())
    except ValidationError as error:
        raise SafetyError(f"invalid desktop input instruction: {error}") from error
    return None


class CandidateSelector(Protocol):
    """Select one candidate from current screenshot pixels."""

    def select(
        self,
        image: bytes,
        instruction: str,
        candidates: list[Candidate],
        settings: Settings,
    ) -> Candidate:
        """Return a candidate from the supplied current image."""
        ...


class RunObserver(Protocol):
    """Receive image evidence from each executed attempt."""

    def record(
        self,
        step_number: int,
        attempt_number: int,
        before: bytes,
        action: bytes | None,
        after: bytes | None,
    ) -> None:
        """Store every available screenshot, including failed attempts."""
        ...


class GoalVerifier(Protocol):
    """Verify an instruction from fresh before and after screenshots."""

    def verify(
        self, before: bytes, after: bytes, instruction: str, settings: Settings
    ) -> Evidence:
        """Return visual evidence about the requested goal."""
        ...


def verify_text(image: bytes, expected: str, max_candidates: int = 40) -> Evidence:
    """Check an exact OCR line on a fresh screenshot, in screenshot pixels."""
    candidates = perceive(image, max_candidates=max_candidates)
    observed = [candidate.text for candidate in candidates if candidate.text]

    def normalize(value: str) -> str:
        return " ".join(value.casefold().split())

    matched = any(normalize(value) == normalize(expected) for value in observed)
    return Evidence(matched=matched, observed_text=" | ".join(observed))


def _annotate_action(
    image: bytes, candidates: list[Candidate], action: Action
) -> bytes:
    overlay = Image.open(BytesIO(image)).convert("RGB")
    if candidates:
        overlay = Image.open(BytesIO(draw_candidates(image, candidates))).convert("RGB")
    canvas = ImageDraw.Draw(overlay)
    if action.x is not None and action.y is not None:
        x, y = action.x, action.y
        canvas.ellipse((x - 10, y - 10, x + 10, y + 10), outline="#ff3030", width=5)
    else:
        label = action.kind
        if action.kind == "key_press":
            label = f"key_press: {action.key}"
        elif action.kind == "type_text":
            label = f"type_text: {len(action.text or '')} characters"
        canvas.rectangle((0, 0, min(overlay.width, 400), 35), fill="#ffbd3b")
        canvas.text((8, 8), label, fill="#071321")
    output = BytesIO()
    overlay.save(output, format="PNG")
    return output.getvalue()


def run_scenario(
    scenario: Scenario,
    executor: Executor,
    settings: Settings,
    observer: RunObserver,
    selector: CandidateSelector,
    verifier: GoalVerifier | None = None,
) -> Report:
    """Act only on validated candidates and advance on fresh visual proof."""
    if len(scenario.steps) > settings.max_steps:
        return Report(
            scenario=scenario.name,
            status="FAIL",
            steps=[
                StepResult(instruction=step.instruction, status="SKIPPED", attempts=[])
                for step in scenario.steps
            ],
            error="scenario exceeds max_steps",
        )
    results: list[StepResult] = []
    stopped = False
    for step_number, step in enumerate(scenario.steps, start=1):
        if stopped:
            results.append(
                StepResult(instruction=step.instruction, status="SKIPPED", attempts=[])
            )
            continue
        attempts: list[Attempt] = []
        passed = False
        performed = False
        for attempt_number in range(1, settings.max_attempts + 1):
            start = monotonic()
            before: bytes | None = None
            action_image: bytes | None = None
            after: bytes | None = None
            selected_candidate: Candidate | None = None
            selected_action: Action | None = None
            try:
                before = executor.capture()
                candidates: list[Candidate] = []
                candidate: Candidate | None = None
                action_spec = step.action
                if action_spec is None and scenario.target == "desktop":
                    action_spec = _infer_desktop_action(step.instruction)
                if isinstance(action_spec, ScrollSpec):
                    width, height = executor.viewport()
                    action = Action(
                        kind="scroll",
                        x=action_spec.x if action_spec.x is not None else width // 2,
                        y=action_spec.y if action_spec.y is not None else height // 2,
                        direction=action_spec.direction,
                        ticks=action_spec.ticks,
                        instruction=step.instruction,
                    )
                elif isinstance(action_spec, TypeTextSpec):
                    action = Action(
                        kind="type_text",
                        text=action_spec.text,
                        instruction=step.instruction,
                    )
                elif isinstance(action_spec, KeyPressSpec):
                    action = Action(
                        kind="key_press",
                        key=action_spec.key,
                        instruction=step.instruction,
                    )
                else:
                    candidates = perceive(
                        before, step.instruction, max_candidates=settings.max_candidates
                    )
                    candidate = selector.select(
                        before, step.instruction, candidates, settings
                    )
                    selected_candidate = candidate
                    if candidate not in candidates:
                        raise GroundingError("selected candidate is not current")
                    box = candidate.box
                    action = Action(
                        kind="click",
                        x=box.x + box.width // 2,
                        y=box.y + box.height // 2,
                        instruction=(
                            step.instruction if scenario.target == "desktop" else None
                        ),
                        target_label=candidate.text,
                    )
                selected_action = action
                validate_action(
                    action,
                    executor.viewport(),
                    step.instruction,
                    candidate,
                    allow_unlisted=scenario.target == "desktop",
                )
                logger.info("Planned %s for step %d (%s)", action.kind, step_number, step.instruction)
                logger.info("-" * 80)
                action_image = _annotate_action(before, candidates, action)
                executor.perform(action)
                performed = True
                after = executor.capture()
                if step.expect is not None:
                    evidence = verify_text(
                        after, step.expect.text_visible, settings.max_candidates
                    )
                elif verifier is not None:
                    evidence = verifier.verify(
                        before, after, step.instruction, settings
                    )
                else:
                    raise RuntimeError("visual verifier is required for this step")
                attempts.append(
                    Attempt(
                        status="EXECUTED",
                        candidate=candidate,
                        action=action,
                        strategy="candidate" if candidate is not None else None,
                        evidence=evidence,
                        latency_ms=round((monotonic() - start) * 1000),
                    )
                )
                if evidence.matched:
                    passed = True
                    break
            except SafetyError as error:
                attempts.append(
                    Attempt(
                        status="ACTION_ERROR",
                        candidate=selected_candidate,
                        action=selected_action,
                        strategy=(
                            "candidate" if selected_candidate is not None else None
                        ),
                        error=str(error),
                        latency_ms=round((monotonic() - start) * 1000),
                    )
                )
                break
            except GroundingError as error:
                attempts.append(
                    Attempt(
                        status="ACTION_ERROR",
                        error=str(error),
                        latency_ms=round((monotonic() - start) * 1000),
                    )
                )
            except Exception as error:
                results.append(
                    StepResult(
                        instruction=step.instruction,
                        status="FAIL" if performed else "ERROR",
                        attempts=attempts,
                    )
                )
                results.extend(
                    StepResult(
                        instruction=later.instruction, status="SKIPPED", attempts=[]
                    )
                    for later in scenario.steps[step_number:]
                )
                return Report(
                    scenario=scenario.name,
                    status="INFRA_ERROR",
                    steps=results,
                    error=str(error),
                )
            finally:
                if before is not None:
                    observer.record(
                        step_number, attempt_number, before, action_image, after
                    )
        status: Literal["PASS", "FAIL", "ERROR"] = (
            "PASS" if passed else "FAIL" if performed else "ERROR"
        )
        results.append(
            StepResult(instruction=step.instruction, status=status, attempts=attempts)
        )
        if not passed:
            stopped = True
    return Report(
        scenario=scenario.name, status="FAIL" if stopped else "PASS", steps=results
    )
