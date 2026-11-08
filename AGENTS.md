# AGENTS.md

Vibana Agent is a vision-based UI navigation agent. Given a UI (screenshot or live view) and a list of action steps, it perceives the screen, maps each textual step to a UI action, executes it, verifies the result visually, and produces a standardized success/failure report. Target domain: automotive HMIs and internal engineering tools, where repetitive validation navigation is slow to do by hand.

Python package name: `vibana_agent` (under `src/vibana_agent/`). Python 3.13, managed with `uv`.

---

## Project Goals

The project is judged on three deliverables and three evaluation criteria. Every change should advance at least one of them.

| Deliverable                          | Evaluation criterion             |
| ------------------------------------ | -------------------------------- |
| Computer-vision UI element detection | Accuracy of UI element detection |
| Instruction-to-action mapping engine | Success rate of task completion  |
| Demo on a sample UI workflow         | Robustness to UI layout changes  |

The demo must be highly visual (annotated screenshots, HTML report) and the workflow and pass/fail rules must be standardized .

---

## Coding Standards & Static Analysis

### Strict PEP-8 & Formatting

- **PEP-8 Compliance**: All code must conform strictly to PEP-8.
- **Formatter & Linter**: `ruff` handles both linting and formatting. All config lives in `pyproject.toml`.
- **Type checking**: `mypy` in `strict` mode. Every function is fully annotated. Use modern syntax (`X | None`, `list[str]`, `type` aliases); no `typing.Any` in new code unless wrapping an untyped third-party boundary.
- **Data boundaries**: Anything that crosses a boundary (model output, YAML scenarios, config, reports) is parsed into a `pydantic.BaseModel`. Never pass raw `dict` around.
- **Paths**: `pathlib.Path` only. No `os.path`.
- **Output**: Library code uses `logging`, never `print`. Only `cli.py` writes to stdout.
- **Docstrings**: Google style on all public classes and functions. State units (pixels vs. normalized coordinates) in any docstring that touches coordinates.

### Zero-Tolerance for Bypassing Linting and Type Checking

> [!CAUTION]
> **NEVER** attempt to pass linting or static type checks by adding suppression comments, such as:
>
> - **FORBIDDEN**: `# type: ignore`
> - **FORBIDDEN**: `# noqa`
> - **FORBIDDEN**: `# pylint: disable`
> - **FORBIDDEN**: `# pyright: ignore`
> - **FORBIDDEN**: `# fmt: off`, `# fmt: skip`, `# isort: skip`
> - **FORBIDDEN**: `# pragma: no cover` added to dodge a coverage gap
> - ...
>
> **Config-level bypasses are equally forbidden.** Do not add or widen `ignore`, `per-file-ignores`, `ignore_missing_imports`, `[[tool.mypy.overrides]]`, `exclude`, or `ignore_errors` in `pyproject.toml`, and do not lower strictness. The existing config is the baseline. A change that loosens it needs explicit approval from the human maintainer.
>
> If `mypy` or `ruff` raises an error or warning, **you MUST fix the root cause**:
>
> - Fix the type definition.
> - Use proper type guards (`isinstance()`, `assert`, `TypeGuard`, `TypeIs`).
> - Use proper generic annotations, `TypedDict`, `pydantic.BaseModel`, `Annotated`, `Union`, `Literal`, or `Optional`.
> - If an external library lacks type stubs, write local `.pyi` stubs in `stubs/` (wired through `mypy_path`) or an explicit `Protocol`/typed wrapper in `src/vibana_agent/types/`. Do not add inline ignores. Do not use `cast()` to silence an error you have not understood.
> - ...

## Dependency Management with `uv`

> [!IMPORTANT]
> **Always use `uv add <dependency>`** to install new packages.
> **Never manually edit `dependencies = [...]` in `pyproject.toml`** and never run ad-hoc `pip install`.
> Let `uv` resolve and maintain lockfile consistency automatically. Commit `uv.lock`.
> (Editing other `pyproject.toml` sections, such as tool config, is fine, subject to section 1.2.)

- Add runtime dependency:

  ```bash
  uv add <package-name>
  ```

- Add development/testing dependency:

  ```bash
  uv add --dev <package-name>
  ```

- Reproduce the environment exactly (CI, fresh clone):

  ```bash
  uv sync --frozen
  ```

- Run tools in the project environment (never call bare `python` or `pytest`):

  ```bash
  uv run ruff check . --fix --exit-non-zero-on-fix
  uv run ruff format .
  uv run mypy .
  uv run pytest
  ```

Before adding a heavy dependency (anything pulling in `torch`, or a detection model with a restrictive licence such as OmniParser's icon-detection weights, which community write-ups describe as AGPL), stop and ask the human maintainer. Verify wheel availability for Python 3.13 with `uv add`; if one is missing, report it rather than silently downgrading Python.

---
