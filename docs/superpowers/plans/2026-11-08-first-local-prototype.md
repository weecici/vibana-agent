# First Local Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a four-step automotive HMI scenario locally with screenshot-based decisions, bounded actions, visual verification, and a browsable report.

**Architecture:** A local, self-contained mock HMI is the only live action target. Playwright captures pixels and executes validated clicks; OCR and OpenCV propose visible elements, and a local Ollama vision model selects from numbered candidates. A controller verifies each step from a fresh screenshot and writes a report even when an action fails. The agent never reads the mock's DOM or internal state to decide what to do.

**Tech Stack:** Python 3.13, `uv`, Pydantic, Typer, PyYAML, Playwright Chromium, Pillow, OpenCV headless, `pytesseract` plus the system Tesseract binary, local Ollama `qwen3-vl:4b-instruct`, static HTML/CSS/JavaScript.

**Spec:** [`PROTOTYPE.md`](../../../PROTOTYPE.md). This plan implements its first working slice; the full evaluation harness, desktop control, and additional action types remain future work at the user's request.

## Global Constraints

- Reference hardware: about 8 GB free RAM and a 4 GB NVIDIA GPU; avoid `torch` and licensed detection weights.
- Default `VIBANA_MODEL=qwen3-vl:4b-instruct`; model choice remains configurable.
- Set `num_ctx=8192`, `temperature=0`, and a fixed seed on every Ollama call; resize image longest side to at most 1280 pixels.
- Ollama output uses a JSON schema and Pydantic validation; invalid output never causes a click.
- The candidate strategy clicks detected box centers in original screenshot pixels. The `[0, 1000]` model-coordinate conversion stays isolated in `grounding/coords.py` for calibration and any later direct strategy.
- Agent decisions use screenshots only; the mock DOM and state cannot be read for targeting or verification.
- Every scenario step has an explicit `expect`; run success requires every step to pass after an action and fresh screenshot.
- All actions are bounded by step and run budgets, viewport checks, and external-call timeouts.
- Use `uv add` for dependencies and commit `uv.lock`; use `pathlib.Path`, strict mypy, Ruff, Google-style public docstrings, and no suppression comments.
- `runs/` stays gitignored; never commit screenshots from internal tools.

## Review Focus

- An unknown or destructive instruction must be rejected before any action (`test_rejects_unapproved_instruction`, Task 4).
- A malformed or unknown candidate model response must produce `ACTION_ERROR` without clicking (`test_invalid_action_exhausts_to_error`, Task 5).
- A stale or covered target must fail verification after the click rather than pass from the earlier image (`test_requires_fresh_positive_evidence`, Task 5).
- A missing Tesseract, Ollama, or Chromium installation must become `INFRA_ERROR` with an actionable CLI message (`test_missing_service_is_infra_error`, Task 6).
- A shifted layout must still use current screenshot coordinates rather than fixed positions (`test_shifted_layout_smoke`, Task 6).

---

## File Map

| Path | Responsibility |
| --- | --- |
| `src/vibana_agent/schema.py` | Validated scenario, candidate, action, evidence, attempt, step, and report models. |
| `src/vibana_agent/config.py` | Environment settings and budgets. |
| `src/vibana_agent/perception.py` | Screenshot resize, OCR boxes, OpenCV region proposals, deduplication, numbered overlay. |
| `src/vibana_agent/grounding/coords.py` | Normalized-to-pixel conversion. |
| `src/vibana_agent/grounding/ollama.py` | Timeout-bound structured vision call and candidate selection. |
| `src/vibana_agent/executor.py` | Screenshot/action protocol, local Playwright target, read-only replay target. |
| `src/vibana_agent/controller.py` | Safety policy, action loop, budgets, verdicts, fresh-image verification. |
| `src/vibana_agent/report.py` | JSON, annotated PNGs, and self-contained HTML. |
| `src/vibana_agent/cli.py` | `vibana run` and preflight messages. |
| `hmi_mock/index.html`, `hmi_mock/app.js`, `hmi_mock/style.css` | Visual local HMI and seeded layout shift. |
| `scenarios/settings_brightness_70.yaml` | Standard four-step demonstration. |
| `tests/unit/`, `tests/e2e/` | Small safety and workflow checks; model tests are manual smoke checks. |
| `README.md`, `.gitignore`, `pyproject.toml`, `uv.lock` | Local setup, command, dependencies, ignored artifacts, entry point. |

### Task 1: Scenario contract and configuration

**Files:** Create `src/vibana_agent/schema.py`, `src/vibana_agent/config.py`, `scenarios/settings_brightness_70.yaml`, `tests/unit/test_schema.py`; modify `pyproject.toml`, `uv.lock` through `uv add pydantic pydantic-settings typer pyyaml`.

**Interfaces:** Produce `load_scenario(path: Path) -> Scenario`; `Scenario(name: str, target: Literal["hmi_mock", "replay"], steps: list[Step])`; `Step(instruction: str, expect: Expectation)`; `Expectation(text_visible: str)`; `Settings(model: str, num_ctx: int, seed: int, max_attempts: int, max_steps: int, model_timeout_s: float)` with `VIBANA_` environment prefix. Define Pydantic `Candidate(id: int, box: Box, text: str | None)`, `Box(x: int, y: int, width: int, height: int)`, `Action(kind: Literal["click"], x: int, y: int)`, `Evidence(matched: bool, observed_text: str)`, `Attempt(status: Literal["ACTION_ERROR", "EXECUTED"], candidate: Candidate | None, action: Action | None, strategy: Literal["candidate"] | None, evidence: Evidence | None, latency_ms: int, error: str | None)`, `StepResult(instruction: str, status: Literal["PASS", "FAIL", "ERROR", "SKIPPED"], attempts: list[Attempt])`, and `Report(scenario: str, status: Literal["PASS", "FAIL", "INFRA_ERROR"], steps: list[StepResult], error: str | None)`.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_schema.py`: `test_missing_expect_is_invalid` asserts validation fails; `test_four_step_scenario_loads` asserts four instructions, the final `Home` expectation, and default budgets (`max_attempts=3`, `max_steps=10`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_schema.py -q`; expect failure from missing models.
- [ ] **Step 3: Implement** models and `load_scenario(path: Path) -> Scenario`; parse YAML with `safe_load` directly into `Scenario.model_validate`, reject empty steps, blank text, and unsupported targets. Add the exact scenario from `PROTOTYPE.md`.
- [ ] **Step 4: Run** the test; expect pass. Commit schema, scenario, dependency changes, and lockfile.

### Task 2: Visual mock HMI

**Files:** Create `hmi_mock/index.html`, `hmi_mock/app.js`, `hmi_mock/style.css`, `tests/e2e/test_mock_hmi.py`; add `playwright` with `uv add playwright` and run `uv run playwright install chromium`.

**Interfaces:** The local page exposes Home → Settings → Display → Brightness; clicking the brightness control increases its visible value in 10% increments until `70%`, and a Home control returns to visible `Home`. Query parameter `?seed=1` shifts positions without changing behavior. All controls are large and labeled; no destructive controls or external requests exist.

- [ ] **Step 1: Write failing browser test** `test_mock_workflow_and_shift`: open local page for seeds 0 and 1, navigate through labels, reach `70%`, return Home, and assert each visible state.
- [ ] **Step 2: Run** `uv run pytest tests/e2e/test_mock_hmi.py -q`; expect failure because the fixture does not exist.
- [ ] **Step 3: Build** the fixture using semantic buttons and deterministic CSS layout shift. DOM access is allowed in this fixture test only.
- [ ] **Step 4: Run** the browser test; expect pass. Commit the fixture and test.

### Task 3: Perception and grounding

**Files:** Create `src/vibana_agent/perception.py`, `src/vibana_agent/grounding/__init__.py`, `src/vibana_agent/grounding/coords.py`, `src/vibana_agent/grounding/ollama.py`, `tests/unit/test_grounding.py`; add `pillow opencv-python-headless pytesseract ollama` via `uv add`.

**Interfaces:** `resize_for_model(image: bytes, max_side: int = 1280) -> tuple[bytes, float]` returns the resized PNG and original-to-model scale; `perceive(image: bytes) -> list[Candidate]` merges Tesseract word/line boxes with OpenCV rectangular proposals and removes near duplicates; `draw_candidates(image: bytes, candidates: list[Candidate]) -> bytes`; `select_candidate(image: bytes, instruction: str, candidates: list[Candidate], settings: Settings) -> Candidate` calls Ollama with schema `Selection(candidate_id: int | None, reason: str)`, rejects missing/unknown IDs; `normalized_to_pixel(x: int, y: int, width: int, height: int) -> tuple[int, int]` checks `[0, 1000]` and returns viewport pixels. Candidate boxes use original screenshot pixels throughout; scale them only while drawing the model overlay. Use numbered candidate selection only in this first slice; no direct point fallback.

- [ ] **Step 1: Write failing tests**: `test_image_resize_and_coordinate_calibration` asserts a known box survives a 1920×1080 to 1280×720 resize and the center maps back within 2 original pixels; `test_invalid_selection_is_rejected` asserts invalid JSON and unknown candidate ID raise a typed grounding error; `test_out_of_range_normalized_coordinate_is_rejected` checks values outside `[0, 1000]`; `test_candidate_overlay_has_numbered_box` checks an output PNG is produced.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_grounding.py -q`; expect failure from missing functions.
- [ ] **Step 3: Implement** screenshot-only detection and Ollama call. Pass `Selection.model_json_schema()` as `format`; set `stream=False`, `num_ctx`, `temperature=0`, `seed`, and a request timeout; validate model text with `Selection.model_validate_json`. Preserve the resize scale and never infer a target from an unvalidated response.
- [ ] **Step 4: Run** the tests; expect pass. Commit perception, grounding, tests, and lockfile.

### Task 4: Local executor and action safety

**Files:** Create `src/vibana_agent/executor.py`, `tests/unit/test_safety.py`; modify `src/vibana_agent/schema.py` only if the agreed `Action` model needs a validation field.

**Interfaces:** `Executor` protocol has `capture() -> bytes`, `perform(action: Action) -> None`, `viewport() -> tuple[int, int]`, `close() -> None`. `MockBrowserExecutor(path: Path, seed: int)` only opens `hmi_mock/index.html` under the repository, runs headless Chromium with screenshot scale `css`, and denies external navigation/requests. `ReplayExecutor(images: list[Path])` can capture but always rejects `perform`. `validate_action(action: Action, viewport: tuple[int, int], instruction: str, candidate: Candidate) -> None` allows click only when the instruction exactly matches one of the four scenario instructions; the click must be inside the current viewport and selected box. No keyboard input, arbitrary URL, desktop access, shell, or file write action is exposed to the model.

- [ ] **Step 1: Write failing tests**: `test_rejects_unapproved_instruction` checks “delete files” and “purchase” are rejected before `perform`; `test_click_outside_viewport_is_rejected` checks negative and boundary coordinates; `test_replay_never_clicks` checks replay rejects `perform`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_safety.py -q`; expect failure.
- [ ] **Step 3: Implement** protocol, backends, and guard. Use a fixed mapping of accepted instructions to action intent; do not evaluate or execute arbitrary model text. Set browser operation timeouts and close resources on errors.
- [ ] **Step 4: Run** tests; expect pass. Commit executor and safety tests.

### Task 5: Bounded controller and visual verifier

**Files:** Create `src/vibana_agent/controller.py`, `tests/unit/test_controller.py`; extend `src/vibana_agent/schema.py` only for report fields required here.

**Interfaces:** `verify_text(image: bytes, expected: str) -> Evidence` uses fresh-image OCR and returns `matched: bool` plus observed text; normalize whitespace/case, but require the complete expected token sequence. `RunObserver.record(step_number: int, attempt_number: int, before: bytes, action: bytes, after: bytes) -> None` stores images for Task 6. `run_scenario(scenario: Scenario, executor: Executor, settings: Settings, observer: RunObserver, selector: CandidateSelector) -> Report` owns the attempt loop; `CandidateSelector.select(image: bytes, instruction: str, candidates: list[Candidate], settings: Settings) -> Candidate` is implemented by Ollama in Task 3 and by a screenshot-driven stub in tests. Each attempt captures before, perceives, grounds, validates, clicks, captures after, verifies; a failed postcondition retries with a new screenshot. `70%` is closed loop: each click counts toward the step budget, and the controller stops at the first verified `70%`.

- [ ] **Step 1: Write failing tests**: `test_requires_fresh_positive_evidence` uses fake screenshots with `70%` only before the click and asserts no PASS; `test_invalid_action_exhausts_to_error` uses an unknown candidate ID, asserts zero executor clicks, three `ACTION_ERROR` attempts, step `ERROR`, and later steps `SKIPPED`; `test_failed_verification_exhausts_to_fail` asserts three executed attempts end in step `FAIL`; `test_all_steps_pass_only_after_action` asserts run PASS only when every step has a verified post-action image.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_controller.py -q`; expect failure.
- [ ] **Step 3: Implement** the loop and status rules from `PROTOTYPE.md`. Preserve separate `INFRA_ERROR` for missing tools, model timeout, or browser failure; never turn unknown OCR into PASS. For brightness, the default three-attempt budget requires the mock to start at `40%`.
- [ ] **Step 4: Run** tests; expect pass. Commit controller and tests.

### Task 6: Report, CLI, local guide, and real smoke run

**Files:** Create `src/vibana_agent/report.py`, `src/vibana_agent/cli.py`, `tests/unit/test_report.py`, `tests/e2e/test_prototype.py`; modify `src/vibana_agent/__init__.py`, `pyproject.toml` script entry, `README.md`, `.gitignore`.

**Interfaces:** CLI command `uv run vibana run scenarios/settings_brightness_70.yaml [--seed 1]` invokes `run_scenario`. `Frame(step_number: int, attempt_number: int, before: bytes, action: bytes, after: bytes)` is a Pydantic model. `write_report(report: Report, frames: list[Frame], root: Path) -> Path` creates `runs/<scenario>/<timestamp>/report.json`, `report.html`, `NN_before.png`, `NN_action.png`, `NN_after.png`, and `final.png`; per-step PNGs show the final attempt, while JSON and HTML show every attempt. HTML shows step status, instruction, chosen candidate, annotated action, before/after images, OCR evidence, attempt count, latency, and overall verdict; escape all scenario/model text. CLI prints artifact path and verdict, then exits nonzero for FAIL or INFRA_ERROR.

- [ ] **Step 1: Write failing tests**: `test_report_contains_required_artifacts` validates JSON against `Report` and checks linked PNGs/escaped HTML; `test_missing_service_is_infra_error` checks a missing Tesseract/Ollama/Chromium dependency yields an actionable `INFRA_ERROR` rather than a traceback; `test_shifted_layout_smoke` runs seed 1 with a deterministic selector that reads only screenshot-derived candidates and confirms four PASS steps.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_report.py tests/e2e/test_prototype.py -q`; expect failure.
- [ ] **Step 3: Implement** report, CLI, entry point, and `.gitignore` for `runs/`. Document exact local setup: `uv sync --frozen`; install system Tesseract and Chromium with `uv run playwright install chromium`; start Ollama, pull `qwen3-vl:4b-instruct`, set recommended server environment variables, run the scenario, open `report.html`, and use `--seed 1` to see layout variation. Explain that only the mock target can receive clicks and that model calls may be slow on 4 GB VRAM.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_report.py tests/e2e/test_prototype.py -q`; expect pass. Commit report, CLI, guide, tests, and lockfile.
- [ ] **Step 5: Run required gates**: `uv run ruff check . --fix --exit-non-zero-on-fix`, `uv run ruff format .`, `uv run mypy .`, `uv run pytest`. Fix root causes, rerun until all pass, and report their actual outputs.
- [ ] **Step 6: Run the actual local command** with Ollama and Chromium available, inspect `report.html` and screenshots, and record the verdict and artifact path. If the sandbox or missing local services prevent this, state that plainly and give the user the exact smoke command; do not claim the live model path works until it has run.

## Local Use After Implementation

The README is the source of truth for platform-specific installation. The expected POSIX flow is:

```bash
uv sync --frozen
uv run playwright install chromium
ollama pull qwen3-vl:4b-instruct
ollama serve
uv run vibana run scenarios/settings_brightness_70.yaml
```

Install the system Tesseract executable before the run, then open the printed `report.html` path in a browser. Run `uv run vibana run scenarios/settings_brightness_70.yaml --seed 1` to exercise a shifted layout. `ollama serve` may already be running as a service; do not start a second instance in that case.
