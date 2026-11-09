# Desktop Action Wait Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let desktop actions wait briefly for asynchronous UI changes before verification captures the screen.

**Architecture:** Add a validated `wait_after_ms` duration to action data and the model's structured action response. The controller performs the action, waits once, then captures the after-image. Canonical quoted searches default to 2,000 ms; the upper bound is 10,000 ms.

**Tech Stack:** Python 3.13, Pydantic, Ollama structured output, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-09-desktop-action-wait-design.md`

## Global Constraints

- Keep waits bounded to 0–10,000 milliseconds.
- Keep the delay before the post-action screenshot and visual verification.
- Do not repeat input actions or change retry behavior.
- Keep all new boundary data in Pydantic models.
- Use `uv run` for project tools and preserve strict Ruff and mypy settings.

## Review Focus

- A zero delay should not add a sleep or affect existing action latency.
- A duration above 10,000 ms should fail validation before execution.
- The search default should apply only to the recognized quoted-search syntax.
- Model-selected waits must pass through the same duration bound as YAML actions.
- Waiting must occur after input and before the after-image is captured.

---

### Task 1: Add bounded action wait and verify ordering

**Files:**
- Modify: `src/vibana_agent/schema.py`
- Modify: `src/vibana_agent/grounding/ollama.py`
- Modify: `src/vibana_agent/controller.py`
- Modify: `README.md`
- Test: `tests/unit/test_grounding.py`
- Test: `tests/unit/test_input_actions.py`

**Interfaces:**
- `Action.wait_after_ms: int` is an integer duration in milliseconds, default `0`, bounded to `0..10_000`.
- Every explicit desktop action spec accepts `wait_after_ms` with the same bound.
- `DesktopActionSelection.wait_after_ms: int` exposes that value to the model.
- The controller waits once after `executor.perform(action)` and before `executor.capture()`.
- `_infer_desktop_action()` returns quoted searches with `wait_after_ms=2_000`.

- [ ] **Step 1: Write failing tests** for model-selected delay validation, the 2,000 ms quoted-search default, the 10,000 ms upper bound, and wait-before-capture ordering.
- [ ] **Step 2: Run the focused tests** with `uv run pytest tests/unit/test_grounding.py tests/unit/test_input_actions.py -q` and confirm they fail for the missing behavior.
- [ ] **Step 3: Implement bounded fields and planner support** in the Pydantic models and structured Ollama response; prompt the planner to request a delay only when a UI update may be asynchronous.
- [ ] **Step 4: Implement controller timing** by sleeping for `wait_after_ms / 1000` after the action and before the after-image capture. Preserve zero-delay behavior and keyboard one-shot handling.
- [ ] **Step 5: Run focused and full tests** with `uv run pytest tests/unit/test_grounding.py tests/unit/test_input_actions.py -q` and `uv run pytest -q`.
- [ ] **Step 6: Commit the feature** as `feat: wait for desktop UI updates`.

After the feature commit, run Ruff, formatting, and mypy as requested. If formatting or linting modifies files, commit only those changes in a separate conventional style commit.
