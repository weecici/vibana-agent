"""JSON and browsable screenshot reports for prototype runs."""

from datetime import UTC, datetime
from html import escape
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel

from vibana_agent.schema import Attempt, Report, StepResult


class Frame(BaseModel):
    """Before, annotated action, and after images in screenshot pixels."""

    step_number: int
    attempt_number: int
    before: bytes
    action: bytes
    after: bytes


class FrameCollector:
    """Collect screenshots from the controller for report writing."""

    def __init__(self) -> None:
        self.frames: list[Frame] = []

    def record(
        self,
        step_number: int,
        attempt_number: int,
        before: bytes,
        action: bytes,
        after: bytes,
    ) -> None:
        """Keep one executed attempt's screenshot evidence."""
        self.frames.append(
            Frame(
                step_number=step_number,
                attempt_number=attempt_number,
                before=before,
                action=action,
                after=after,
            )
        )


def _placeholder() -> bytes:
    image = Image.new("RGB", (1280, 720), "#112334")
    ImageDraw.Draw(image).text((70, 80), "No screenshot available", fill="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _attempt_html(attempt: Attempt, number: int) -> str:
    candidate = attempt.candidate
    target = (
        f"#{candidate.id} {escape(candidate.text or 'region')}"
        if candidate is not None
        else "none"
    )
    point = (
        f"({attempt.action.x}, {attempt.action.y})"
        if attempt.action is not None
        else "none"
    )
    evidence = (
        escape(attempt.evidence.observed_text)
        if attempt.evidence is not None
        else "none"
    )
    error = escape(attempt.error or "")
    return (
        "<tr>"
        f"<td>{number}</td><td>{attempt.status}</td><td>{target}</td>"
        f"<td>{point}</td><td>{escape(attempt.strategy or 'none')}</td>"
        f"<td>{evidence}</td><td>{attempt.latency_ms} ms</td><td>{error}</td>"
        "</tr>"
    )


def _step_html(step: StepResult, number: int) -> str:
    prefix = f"{number:02d}"
    attempts = "".join(
        _attempt_html(attempt, index)
        for index, attempt in enumerate(step.attempts, start=1)
    )
    return (
        f'<section class="step"><div class="step-head"><span class="index">{prefix}</span>'
        f"<div><h2>{escape(step.instruction)}</h2><p>{escape(step.status)} · "
        f"{len(step.attempts)} attempt(s)</p></div></div>"
        '<div class="images">'
        f'<figure><img src="{prefix}_before.png" alt="Before step {number}"><figcaption>Before</figcaption></figure>'
        f'<figure><img src="{prefix}_action.png" alt="Chosen target step {number}"><figcaption>Chosen target</figcaption></figure>'
        f'<figure><img src="{prefix}_after.png" alt="After step {number}"><figcaption>After</figcaption></figure>'
        "</div>"
        "<table><thead><tr><th>#</th><th>Action</th><th>Candidate</th><th>Click</th>"
        "<th>Strategy</th><th>OCR evidence</th><th>Latency</th><th>Error</th>"
        f"</tr></thead><tbody>{attempts}</tbody></table></section>"
    )


def write_report(report: Report, frames: list[Frame], root: Path) -> Path:
    """Write validated JSON, annotated PNGs, and a local HTML report."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    folder = root / report.scenario / stamp
    folder.mkdir(parents=True, exist_ok=False)
    json_text = report.model_dump_json(indent=2)
    Report.model_validate_json(json_text)
    (folder / "report.json").write_text(json_text, encoding="utf-8")
    placeholder = _placeholder()
    for number, _ in enumerate(report.steps, start=1):
        step_frames = [frame for frame in frames if frame.step_number == number]
        final = (
            max(step_frames, key=lambda frame: frame.attempt_number)
            if step_frames
            else None
        )
        prefix = f"{number:02d}"
        (folder / f"{prefix}_before.png").write_bytes(
            final.before if final else placeholder
        )
        (folder / f"{prefix}_action.png").write_bytes(
            final.action if final else placeholder
        )
        (folder / f"{prefix}_after.png").write_bytes(
            final.after if final else placeholder
        )
    (folder / "final.png").write_bytes(frames[-1].after if frames else placeholder)
    sections = "".join(
        _step_html(step, number) for number, step in enumerate(report.steps, start=1)
    )
    error = f"<p class='error'>{escape(report.error)}</p>" if report.error else ""
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Vibana · {escape(report.scenario)}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#091522;color:#edf8ff;font:16px Arial,sans-serif}}
main{{max-width:1540px;margin:auto;padding:44px}}h1{{font-size:46px;margin:8px 0}}
.kicker{{letter-spacing:4px;color:#6ad4f1;font-weight:bold}}.verdict{{font-size:24px;color:#78e5bd}}
.error{{color:#ffb5a9}}.step{{margin:42px 0;padding:28px;border:1px solid #31546a;border-radius:22px;background:#122b3d}}
.step-head{{display:flex;align-items:center;gap:20px}}.index{{font-size:38px;color:#69d5fa}}
h2{{margin:0 0 7px;font-size:29px}}p{{margin:0 0 20px}}.images{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
figure{{margin:0}}img{{width:100%;border:1px solid #4d748a;border-radius:10px}}figcaption{{padding:9px;color:#b6cfdd}}
table{{width:100%;border-collapse:collapse;margin-top:22px;font-size:14px}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #31546a;vertical-align:top}}
</style></head><body><main><div class="kicker">VIBANA / LOCAL PROTOTYPE</div>
<h1>{escape(report.scenario)}</h1><p class="verdict">Run verdict: {escape(report.status)}</p>
{error}{sections}<p><a href="report.json">Validated JSON</a> · <a href="final.png">Final screenshot</a></p>
</main></body></html>"""
    (folder / "report.html").write_text(html, encoding="utf-8")
    return folder
