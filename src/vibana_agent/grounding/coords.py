"""Normalized model-coordinate conversion."""


def normalized_to_pixel(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    """Map coordinates in [0, 1000] to original screenshot pixels."""
    if not 0 <= x <= 1000 or not 0 <= y <= 1000:
        raise ValueError("normalized coordinates must be in [0, 1000]")
    if width <= 0 or height <= 0:
        raise ValueError("viewport dimensions must be positive")
    return min(round(x * width / 1000), width - 1), min(
        round(y * height / 1000), height - 1
    )
