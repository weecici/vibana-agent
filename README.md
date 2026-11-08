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
    START([Start]) --> TASK["Load Instructions and Success Criteria"]
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

## Run the first local prototype

The current prototype runs only against its bundled automotive HMI mock. It reads screenshots, proposes visible text and regions with RapidOCR and OpenCV, asks local Ollama to choose a numbered target, clicks through headless Chromium, and checks each result from a fresh screenshot. It saves annotated PNGs, validated JSON, and a browsable HTML report.

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

`PASS` means each step had an action and its expected text was observed on a fresh screenshot. `FAIL` means a step exhausted its three attempts; `INFRA_ERROR` means a required service or browser failed. The CLI exits nonzero for either failure. The only executable target is the bundled mock HMI, and only the four instructions in this scenario are allowed to click. Unknown model answers, instructions, or coordinates do not cause a click. No desktop or arbitrary website control is enabled.

To change the local model, set `VIBANA_MODEL` before the run. A replacement model should be calibrated against the known mock workflow before trusting its selections. The vision call uses an 8192-token context, zero temperature, a fixed seed, and a 1280-pixel maximum image side.

### Developer checks

```bash
uv run ruff check . --fix --exit-non-zero-on-fix
uv run ruff format .
uv run mypy .
uv run pytest
```
