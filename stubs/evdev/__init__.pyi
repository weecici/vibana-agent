"""Typed UInput surface including absolute-axis tuples accepted at runtime."""

from collections.abc import Sequence
from typing import NamedTuple

from . import ecodes as ecodes

class AbsInfo(NamedTuple):
    value: int
    min: int
    max: int
    fuzz: int
    flat: int
    resolution: int

class UInput:
    def __init__(
        self,
        events: dict[int, Sequence[int | tuple[int, AbsInfo]]] | None = ...,
        name: str = ...,
        bustype: int = ...,
        input_props: Sequence[int] | None = ...,
    ) -> None: ...
    def write(self, event_type: int, code: int, value: int) -> None: ...
    def syn(self) -> None: ...
    def close(self) -> None: ...
