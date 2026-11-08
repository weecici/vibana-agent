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
