"""Screenshot-only OCR and region proposals in original screenshot pixels."""

import re
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field
from rapidocr import RapidOCR

from vibana_agent.schema import Box, Candidate


class OcrLine(BaseModel):
    """Validated RapidOCR line in original screenshot pixels."""

    box: list[tuple[int, int]] = Field(min_length=4, max_length=4)
    txt: str
    score: float


_ocr_engine: RapidOCR | None = None


def resize_for_model(image: bytes, max_side: int = 1280) -> tuple[bytes, float]:
    """Resize a PNG and return its original-to-model pixel scale."""
    source = Image.open(BytesIO(image)).convert("RGB")
    scale = min(1.0, max_side / max(source.size))
    if scale < 1:
        size = (round(source.width * scale), round(source.height * scale))
        source = source.resize(size, Image.Resampling.LANCZOS)
    output = BytesIO()
    source.save(output, format="PNG")
    return output.getvalue(), scale


def _ocr_boxes(image: Image.Image) -> list[tuple[Box, str]]:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR(params={"Global.log_level": "warning"})
    result = _ocr_engine(np.array(image.convert("RGB")))
    lines = result.to_json() or []
    found: list[tuple[Box, str]] = []
    for raw_line in lines:
        line = OcrLine.model_validate(raw_line)
        if line.score < 0.25 or not line.txt.strip():
            continue
        left = min(point[0] for point in line.box)
        top = min(point[1] for point in line.box)
        right = max(point[0] for point in line.box)
        bottom = max(point[1] for point in line.box)
        found.append(
            (
                Box(
                    x=left,
                    y=top,
                    width=max(1, right - left),
                    height=max(1, bottom - top),
                ),
                line.txt,
            )
        )
    return found


def _region_boxes(image: Image.Image) -> list[Box]:
    pixels = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 45, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[Box] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 40 <= width <= image.width * 0.8 and 20 <= height <= image.height * 0.4:
            boxes.append(Box(x=x, y=y, width=width, height=height))
    return boxes


def _overlap(first: Box, second: Box) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(0, right - left) * max(0, bottom - top)
    smaller = min(first.width * first.height, second.width * second.height)
    return intersection / smaller


def _instruction_terms(instruction: str | None) -> set[str]:
    if instruction is None:
        return set()
    ignored = {
        "at",
        "click",
        "for",
        "from",
        "in",
        "on",
        "open",
        "please",
        "select",
        "tap",
        "the",
        "to",
        "with",
    }
    return {
        term
        for term in re.findall(r"[a-z0-9]+", instruction.casefold())
        if len(term) > 1 and term not in ignored
    }


def perceive(image: bytes, instruction: str | None = None) -> list[Candidate]:
    """Find OCR lines and rectangular regions in screenshot pixels.

    Args:
        image: Screenshot bytes whose regions use screenshot pixel coordinates.
        instruction: Optional goal used to prioritize matching visible text.
    """
    screenshot = Image.open(BytesIO(image)).convert("RGB")
    proposals = _ocr_boxes(screenshot)
    proposals.extend((box, "") for box in _region_boxes(screenshot))
    terms = _instruction_terms(instruction)
    if terms:
        proposals.sort(
            key=lambda proposal: len(
                terms.intersection(re.findall(r"[a-z0-9]+", proposal[1].casefold()))
            ),
            reverse=True,
        )
    candidates: list[Candidate] = []
    for box, label in proposals:
        if any(_overlap(box, previous.box) > 0.85 for previous in candidates):
            continue
        candidates.append(
            Candidate(id=len(candidates) + 1, box=box, text=label or None)
        )
        if len(candidates) >= 40:
            break
    return candidates


def draw_candidates(image: bytes, candidates: list[Candidate]) -> bytes:
    """Draw numbered boxes over a screenshot at original pixel size."""
    screenshot = Image.open(BytesIO(image)).convert("RGB")
    canvas = ImageDraw.Draw(screenshot)
    font = ImageFont.load_default(size=22)
    for candidate in candidates:
        box = candidate.box
        canvas.rectangle(
            (box.x, box.y, box.x + box.width, box.y + box.height),
            outline="#ffbd3b",
            width=4,
        )
        canvas.text(
            (box.x + 3, box.y + 3),
            str(candidate.id),
            fill="#071321",
            stroke_width=3,
            stroke_fill="#ffbd3b",
            font=font,
        )
    output = BytesIO()
    screenshot.save(output, format="PNG")
    return output.getvalue()
