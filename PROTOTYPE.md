# Prototype Design Notes

## Decisions

The reference machine has **about 8 GB of free system RAM and a 4 GB NVIDIA GPU**. Design and test for that, not for a larger box.

> [!IMPORTANT]
>
> **Default VLM**: `qwen3-vl:4b-instruct`. The ~3.3 GB download plus KV cache and buffers exceeds 4 GB VRAM, so expect partial CPU offload and slower steps.

Rules for anything that calls the model:

1. **Set `num_ctx` explicitly** (default: 8192). Ollama allocates KV cache for the whole declared context up front.
2. **Downscale screenshots before inference.** Qwen3-VL turns each 32x32 px block into one visual token, so a 1920x1080 frame costs about 2,000 tokens. Cap the longest side at 1280 px (about 900 tokens). Keep the scale factor and convert coordinates back to the original resolution.
3. **Deterministic decoding**: `temperature=0`, fixed `seed`.
4. **Structured output only**: pass a JSON schema via Ollama's `format`; parse into a pydantic model; reject anything that fails validation (counts as a step `ERROR` attempt, never as a guess).
5. **One model loaded at a time.** Run perception (OCR/OpenCV) and the VLM sequentially, not concurrently. Use headless Chromium for the mock benchmark and a Linux virtual pointer for live navigation.
6. Recommended server env: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MAX_LOADED_MODELS=1`; optionally `OLLAMA_KV_CACHE_TYPE=q8_0` (requires flash attention). Document any change in the README, not in code.
7. Coordinate contract: the grounding model returns coordinates normalized to [0, 1000]. `grounding/coords.py` is the only place that converts to pixels, and `tests/model/test_coordinate_calibration.py` verifies the convention against a known target. If a different model is configured, that test must pass before anything else is trusted.

Model choice is a config value (`VIBANA_MODEL`), never hard-coded.

---

## Project Structure

```text
src/vibana_agent/
  cli.py            # Typer entry point: `uv run vibana run <scenario.yaml>`
  config.py         # pydantic-settings; env prefix VIBANA_
  schema/           # Scenario, Step, Action, Verdict, Report (pydantic models)
  perception/       # preprocessing, OCR, OpenCV region proposals, element registry, numbered overlay
  grounding/        # Ollama client, prompts, candidate selection, coordinate conversion
  planner/          # instruction -> typed Step (rule-based grammar first, LLM fallback)
  executor/         # Executor Protocol; Playwright, desktop, and replay backends
  verifier/         # visual postcondition checks (OCR text, region diff, VLM yes/no)
  controller/       # step loop, retries, budgets, verdicts
  report/           # report.json, report.html, annotated screenshots
  types/            # Protocols / wrappers for untyped third-party libs
hmi_mock/           # simulated automotive HMI (test fixture; layout-perturbation knobs)
scenarios/          # YAML workflows (the standardized input format)
eval/               # benchmark harness, perturbation suite, metrics
stubs/              # local .pyi stubs
tests/              # unit/ (no GPU), model/ (needs Ollama), e2e/
runs/               # gitignored output
```

### Pipeline per step

1. Capture screenshot through the `Executor` (never touch the browser DOM for decisions).
2. Perception produces candidate elements: OCR text boxes + OpenCV interactive-region proposals, merged and numbered.
3. Grounding, **default strategy `candidate`**: draw numbered boxes on the screenshot, ask the VLM which ID satisfies the step, click the box center. Fallback strategy `direct`: ask the VLM for a point. Log which strategy fired.
4. Executor performs the action.
5. Verifier checks the step's postcondition **from a fresh screenshot**.
6. Controller records the result and decides: advance, retry, or fail.

The **controller**, not the model, decides when to advance and when the task has succeeded. Multi-click steps (for example "set brightness to 70%") are closed loops: act, re-read the value, repeat until the postcondition holds or the budget runs out.

### Hard boundaries

- **The agent must not see ground truth.** Nothing under `src/vibana_agent/` may import from `hmi_mock/` or read the app's DOM/state to make decisions. Ground truth (element bounding boxes, internal state) is exported by `hmi_mock/` for `eval/` only. An architecture test in `tests/unit/` enforces this import boundary.
- **Two layers of verification.** (a) The _agent-side verifier_ is visual only and is what ships on any real UI. (b) The _harness-side oracle_ (app state in the mock HMI) is used only by `eval/` to grade the agent and to measure verifier agreement. Never feed the oracle back into the agent.
- **Never execute model output as code.** The model proposes an `Action` from a closed set: `click`, `double_click`, `long_press`, `scroll`, `swipe`, `type_text`, `wait`, `assert_visible`, `assert_text`. Anything else is invalid output.
- **Validate before acting**: clamp or reject coordinates outside the viewport; enforce `max_attempts` per step and `max_steps` per run; every external call has a timeout.
- Executors implement one `Protocol` (`capture()`, `perform(action)`, `viewport()`), so Playwright (web HMI), screenshot replay (offline, no clicks), and the Linux desktop backend are interchangeable. Desktop pointer input uses `python-evdev` and `/dev/uinput` on Wayland or X11. Wayland capture uses `grim`; X11 capture uses Pillow. Live actions run automatically inside an explicit screen region, and the desktop backend rejects changed target pixels before clicking.

---

## Standardized Workflow & Pass/Fail Criteria

### Scenario format

Scenarios are YAML files in `scenarios/`, validated by the pydantic `Scenario` model. Mock and replay benchmarks retain explicit, checkable `expect` values:

```yaml
name: settings_brightness_70
target: hmi_mock # or: replay, desktop
steps:
  - instruction: "Open Settings"
    expect: { text_visible: "Display" }
  - instruction: "Open Display"
    expect: { text_visible: "Brightness" }
  - instruction: "Set brightness to 70%"
    expect: { text_visible: "70%" }
  - instruction: "Return Home"
    expect: { text_visible: "Home" }
```

Desktop scenarios may omit `expect`. In that case a vision model compares fresh before and after screenshots and must return positive, specific evidence; `unmet` and `uncertain` do not pass. This is a weaker pass criterion than explicit OCR and requires report review before the result is trusted.

### Statuses and verdicts

| Level   | Status       | Rule                                                                                                                           |
| ------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Attempt | ACTION_ERROR | Invalid target/output or rejected action; no action performed.                                                                 |
| Attempt | EXECUTED     | Executor performed an action; verification may still fail or be unknown.                                                       |
| Step    | PASS         | An action was performed and a fresh screenshot positively verifies the expectation.                                            |
| Step    | FAIL         | An action was performed but the expectation stayed false or unknown through the attempt budget.                                |
| Step    | ERROR        | No valid action could be performed within the attempt budget.                                                                  |
| Step    | SKIPPED      | An earlier step stopped the run.                                                                                               |
| Run     | PASS         | Every step passed.                                                                                                             |
| Run     | FAIL         | Any step failed or errored; later steps are skipped.                                                                           |
| Run     | INFRA_ERROR  | Required service or executor unavailable, timed out, or crashed. Count separately and exclude from agent-success denominators. |

### Report artifacts (every run, same layout)

`runs/<scenario>/<timestamp>/` containing `report.json` (schema-validated), `report.html`, and per step `NN_before.png`, `NN_action.png` (click point and chosen box drawn on the frame), `NN_after.png`, plus `final.png`. `report.json` records per step: instruction, chosen candidate/coordinates, strategy used, attempts, verifier evidence, status, latency.

Do not commit anything from `runs/`, and never commit screenshots from confidential internal tools.

---

## Evaluation (maps to the grading criteria)

All metrics come from `uv run vibana eval ...` and are written to `eval/results/`.

| Criterion                   | Metric                                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Element detection accuracy  | Precision/recall at IoU 0.5 against mock-HMI ground-truth boxes; click-hit rate (predicted point lies inside the target's ground-truth box) |
| Task completion             | Run success rate over N seeds per scenario; step success rate; mean attempts per step                                                       |
| Robustness to layout change | Success rate per perturbation and its drop relative to the baseline layout                                                                  |
| Verifier trustworthiness    | Agreement with the oracle; **false-PASS rate must be 0** (a wrong PASS is worse than a wrong FAIL)                                          |
| Fit for the hardware        | Latency per step, peak VRAM and RAM                                                                                                         |

**Perturbation suite** (parametrized in `hmi_mock/`, always seeded): control positions shifted, dark/light theme, different resolution and aspect ratio, font scale, label rename, icon-only vs. labeled controls, added distractor elements, transient popups/overlays. Report each perturbation separately; never average them away.

Test tiers:

- `tests/unit/`: pure logic, no GPU, no browser. Must be fast and always runnable.
- `tests/e2e/`: Playwright against `hmi_mock/` with a stubbed model client.
- `tests/model/`: needs a running Ollama; marked `@pytest.mark.model` and skipped by default.

---

## Definition of Done

Before declaring any task complete, run all four and report their real output:

```bash
uv run ruff check . --fix --exit-non-zero-on-fix
uv run ruff format .
uv run mypy .
uv run pytest # if tests are available
```

Also required:

- New behavior has a test; a bug fix has a regression test.
- Anything that changes grounding, perception, or verification is re-evaluated on the perturbation suite, and the numbers are reported honestly (including regressions).
- If something could not be run (no Ollama, no GPU), say so explicitly. Never claim "works" for code that was only syntax-checked.
- Commands above assume a POSIX shell. On Windows use the PowerShell equivalents.
