# Vibana Agent

> Vibana - Vision-based UI Navigation Agent

Group: _Quantity_ **>>>>>** _Quality_

Members:

| Name              | Account    | GitLab |
| ----------------- | ---------- | ------ |
| Nguyen Chi Cuong  | CuongNC62  |        |
| Tran Le Duy       | DuyTL3     |        |
| Dang Truong Hung  | HungDT57   |        |
| Phan Thuy Phuong  | PhuongPT71 |        |
| Nguyen Hoang Quan | QuanNH111  |        |

## Architecture Overview

```mermaid
flowchart TD
    START([Start]) --> TASK["Load Instructions and Optional Success Criteria"]
    TASK --> OBS["Capture Screenshot"]

    subgraph AGENT["Vibana Agent"]
      OBS --> PERCEIVE["Perceive Screen and Ground UI Targets"]
      PERCEIVE --> TRACK["Retrieve Current Subgoal and History"]
      TRACK --> STATUS{"Evaluate Task State"}
      STATUS -->|All goals verified| PASS(["SUCCESS"])
      STATUS -->|Timeout / unrecoverable error| FAIL(["FAILURE"])
      STATUS -->|Continue| PLAN["Select Next Action"]
      PLAN --> VALID{"Action Valid and Safe?"}
      VALID -->|No| RECOVER["Replan / Retry / Fail"]
    end

    subgraph ENV["Execution Environment"]
      VALID -->|Yes| EXEC["Execute UI Action"]
      EXEC --> CAPTURE["Capture New Screenshot"]
    end

    CAPTURE --> VERIFY{"Expected Change Observed?"}
    VERIFY -->|Yes| UPDATE["Update Task Progress"]
    VERIFY -->|No| RECOVER
    UPDATE --> OBS
    RECOVER --> LIMIT{"Retry Budget Exceeded?"}
    LIMIT -->|No| OBS
    LIMIT -->|Yes| FAIL
    PASS --> REPORT["Generate Execution Report"]
    FAIL --> REPORT
    REPORT --> END([End])
```

## Run on your desktop (Wayland or X11)

The live agent captures an explicitly selected rectangle of the primary display,
selects a visible target from that screenshot, asks before each click, and checks
the result from a fresh screenshot. Instructions can be given directly, without
a YAML file or authored expectations:

```bash
uv run vibana desktop --region 100,100,900,650 "Open Settings" "Open Display"
```

`--region` is `x,y,width,height` in primary-screen pixels. Choose a rectangle
that contains only the application you want to control. Keep the terminal outside
that rectangle while approving clicks, and leave the UI still during each model
call. The agent refuses a click if the rectangle changes between capture and
execution. Declining a click stops the run. Press Ctrl+C to stop the agent.

On Linux, input uses an absolute virtual pointer through `python-evdev` and
`/dev/uinput`, with a real left-button press after moving onto the target. It
works independently of the X11 or Wayland display protocol.
The user running Vibana needs write access to `/dev/uinput`; no root process is
needed on systems that grant this through a group or ACL. On Wayland, install
`grim` for screenshots; the compositor must support its screencopy protocol.
Niri is supported and was exercised on this machine. On X11, Pillow captures
the screen. Use one display at 100% scale for coordinate-calibrated clicks;
multi-display mapping has not been verified. A live X11 run remains untested.

For repeatable workflows, desktop YAML can contain instructions alone:

```yaml
name: my_desktop_run
target: desktop
steps:
  - instruction: Open Settings
  - instruction: Open Display
```

Run it with `uv run vibana run path/to/workflow.yaml --region 100,100,900,650`.
An optional `expect: {text_visible: "..."}` makes a step use exact OCR text
verification. Without it, the vision model compares before and after screenshots
and returns `met`, `unmet`, or `uncertain` with visual evidence. Only `met`
advances the workflow. Model judgments can be wrong, so inspect `report.html`
before treating the result as validated. Reports contain screenshots of the
selected desktop region; keep them private when they show confidential data.

The action set remains click-only. The model cannot type, run shell commands,
or choose its own coordinates outside detected candidates. Each step has a
three-attempt budget. Live clicks run automatically inside the selected region
after the target stability check. Use a test application and a narrow region
for initial runs. The terminal streams the model's structured candidate
selection and logs its brief visual rationale and planned click before each
action.

## Run the bundled mock benchmark

The bundled automotive HMI remains a repeatable benchmark. It reads screenshots,
proposes visible text and regions with RapidOCR and OpenCV, asks local Ollama to
choose a numbered target, clicks through headless Chromium, and checks explicit
expectations from fresh screenshots. It saves annotated PNGs, validated JSON, and
a browsable HTML report.

### Setup

You need Python 3.13, `uv`, Ollama, and enough disk space for Chromium and the `qwen3-vl:4b-instruct` model. RapidOCR is installed by `uv`; no system Tesseract package is needed. On this project's reference 4 GB GPU, Ollama may offload part of the model to CPU, so steps can take time.

```bash
uv sync --frozen
uv run playwright install chromium
ollama pull qwen3-vl:4b-instruct
```

Start Ollama in another terminal if it is not already running:

```bash
OLLAMA_FLASH_ATTENTION=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

If you already started `ollama serve`, keep that instance running. The optional `OLLAMA_KV_CACHE_TYPE=q8_0` can reduce KV cache memory when flash attention is enabled. Set these on the server process, not the agent command.

### Run and inspect

```bash
uv run vibana run scenarios/settings_brightness_70.yaml
uv run vibana run scenarios/settings_brightness_70.yaml --seed 1
```

The CLI prints the verdict and a path to `report.html`. Open that file in a browser to see the before, chosen target, and after images for each step. `report.json` has the structured evidence and attempt statuses. Artifacts are under `runs/settings_brightness_70/<timestamp>/` and are ignored by Git.

`PASS` means each step had an action and its expected text was observed on a fresh screenshot. `FAIL` means a step exhausted its three attempts; `INFRA_ERROR` means a required service or browser failed. The CLI exits nonzero for either failure. The mock target permits only its four benchmark instructions. Unknown model answers or coordinates do not cause a click on either target.

To change the local model, set `VIBANA_MODEL` before the run. A replacement model should be calibrated against the known mock workflow before trusting its selections. The vision call uses an 8192-token context, zero temperature, a fixed seed, and a 1280-pixel maximum image side.

### Developer checks

```bash
uv run ruff check . --fix --exit-non-zero-on-fix
uv run ruff format .
uv run mypy .
uv run pytest
```
