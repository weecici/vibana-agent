"""Delivery pacing, validation and cleanup at the uinput boundary."""

import pytest
from evdev import ecodes
from PIL import Image

from vibana_agent import desktop
from vibana_agent.desktop import VirtualPointerBackend


class Capture:
    """Provide a fixed screen without accessing the host desktop."""

    def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
        return Image.new("RGB", (region[2], region[3]))

    def size(self) -> tuple[int, int]:
        return 320, 200


class Device:
    """Record event timestamps using a controllable clock in seconds."""

    def __init__(self) -> None:
        self.time = 0.0
        self.events: list[tuple[int, int, int, float]] = []

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value, self.time))

    def syn(self) -> None:
        pass

    def close(self) -> None:
        pass

    def advance(self, seconds: float) -> None:
        self.time += seconds


def test_keyboard_paces_presses_releases_and_modifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The desktop must get time to consume each transition, including Enter."""
    device = Device()
    monkeypatch.setattr(desktop, "sleep", device.advance)
    backend = VirtualPointerBackend(Capture(), device=device, keyboard_device=device)
    backend.type_text("Aa!!\n\t")
    backend.key_press("Ctrl+Shift+A")
    backend.key_press("Enter")
    assert device.events
    for previous, current in zip(device.events, device.events[1:], strict=False):
        assert current[3] - previous[3] >= 0.01
    assert device.time - device.events[-1][3] >= 0.01
    assert device.events[-1][:3] == (ecodes.EV_KEY, ecodes.KEY_ENTER, 0)


def test_unsupported_text_is_rejected_without_partial_typing() -> None:
    """Validation must finish before sending the supported prefix."""
    device = Device()
    backend = VirtualPointerBackend(Capture(), device=device, keyboard_device=device)
    with pytest.raises(ValueError, match="ASCII"):
        backend.type_text("valid prefix\u00e9")
    assert device.events == []


@pytest.mark.parametrize("interrupt_at", [1, 2, 3])
def test_interrupted_typing_releases_shift_and_character(
    monkeypatch: pytest.MonkeyPatch, interrupt_at: int
) -> None:
    """Ctrl+C during any paced transition must not leave a key held down."""
    device = Device()
    waits = 0

    def interrupt(seconds: float) -> None:
        nonlocal waits
        waits += 1
        if waits == interrupt_at:
            raise KeyboardInterrupt
        device.advance(seconds)

    monkeypatch.setattr(desktop, "sleep", interrupt)
    backend = VirtualPointerBackend(Capture(), device=device, keyboard_device=device)
    with pytest.raises(KeyboardInterrupt):
        backend.type_text("A")
    held: set[int] = set()
    for event_type, code, value, _ in device.events:
        assert event_type == ecodes.EV_KEY
        if value:
            held.add(code)
        else:
            held.discard(code)
    assert not held


def test_modifier_cleanup_continues_after_a_release_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Shift release failure must not prevent attempting to release Ctrl."""

    class FailingDevice(Device):
        def write(self, event_type: int, code: int, value: int) -> None:
            super().write(event_type, code, value)
            if code == ecodes.KEY_LEFTSHIFT and value == 0:
                raise OSError("shift release failed")

    device = FailingDevice()
    monkeypatch.setattr(desktop, "sleep", device.advance)
    backend = VirtualPointerBackend(Capture(), device=device, keyboard_device=device)
    with pytest.raises(OSError, match="shift release failed"):
        backend.key_press("Ctrl+Shift+A")
    assert device.events[-1][:3] == (ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)


@pytest.mark.parametrize("chord", ["F01", "Ctrl+F01"])
def test_function_keys_with_leading_zero_are_normalized(
    monkeypatch: pytest.MonkeyPatch, chord: str
) -> None:
    """A numerically valid function key must resolve to its actual key code."""
    device = Device()
    monkeypatch.setattr(desktop, "sleep", device.advance)
    backend = VirtualPointerBackend(Capture(), device=device, keyboard_device=device)
    backend.key_press(chord)
    assert any(
        (event_type, code, value) == (ecodes.EV_KEY, ecodes.KEY_F1, 1)
        for event_type, code, value, _ in device.events
    )
