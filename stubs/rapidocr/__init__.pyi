"""Narrow RapidOCR boundary used by this project."""

import numpy as np

class RapidOCROutput:
    def to_json(self) -> list[object] | None: ...

class RapidOCR:
    def __init__(
        self,
        config_path: str | None = ...,
        params: dict[str, str] | None = ...,
    ) -> None: ...
    def __call__(self, image: np.ndarray) -> RapidOCROutput: ...
