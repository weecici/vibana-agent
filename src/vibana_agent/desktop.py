"""Linux desktop capture and virtual pointer input backends."""

import os
import subprocess
from collections.abc import Callable, Sequence
from io import BytesIO
from time import sleep
from typing import Protocol

from evdev import AbsInfo, UInput, ecodes
from PIL import Image, ImageGrab


class ScreenCapture(Protocol):
    """Capture a desktop rectangle in physical screen pixels."""

    def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
        """Capture x, y, width, height in screen pixels."""
        ...

    def size(self) -> tuple[int, int]:
        """Return desktop width and height in screen pixels."""
        ...


class DesktopGui(ScreenCapture, Protocol):
    """Capture and inject one safe action in screen pixels."""

    def click(self, x: int, y: int) -> None:
        """Activate one screen pixel."""
        ...

    def scroll(self, x: int, y: int, direction: str, ticks: int) -> None:
        """Scroll wheel ticks at a screen pixel."""
        ...

    def type_text(self, value: str) -> None:
        """Type supported text into the focused control."""
        ...

    def key_press(self, key: str) -> None:
        """Press a named key or modifier chord."""
        ...

    def close(self) -> None:
        """Release virtual input resources."""
        ...


class PointerDevice(Protocol):
    """The small evdev UInput surface used for one pointer click."""

    def write(self, event_type: int, code: int, value: int) -> None:
        """Queue one kernel input event."""
        ...

    def syn(self) -> None:
        """Flush queued input events to the compositor."""
        ...

    def close(self) -> None:
        """Release the virtual input device."""
        ...


def _run_grim(command: list[str]) -> bytes:
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=10)
    except FileNotFoundError as error:
        raise RuntimeError("grim is required for Wayland screenshots") from error
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("grim could not capture the Wayland screen") from error
    return result.stdout


class GrimCapture:
    """Wayland screenshots through the compositor's screencopy protocol."""

    def __init__(self, runner: Callable[[list[str]], bytes] = _run_grim) -> None:
        self._runner = runner

    def _image(self, command: list[str]) -> Image.Image:
        with Image.open(BytesIO(self._runner(command))) as image:
            return image.convert("RGB")

    def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
        """Capture the requested Wayland rectangle in screen pixels."""
        x, y, width, height = region
        return self._image(["grim", "-g", f"{x},{y} {width}x{height}", "-"])

    def size(self) -> tuple[int, int]:
        """Return the full Wayland screenshot dimensions in pixels."""
        return self._image(["grim", "-"]).size


class X11Capture:
    """Capture X11 pixels with Pillow's X display backend."""

    def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
        """Capture the requested X11 rectangle in screen pixels."""
        x, y, width, height = region
        return ImageGrab.grab(
            bbox=(x, y, x + width, y + height),
            xdisplay=os.environ.get("DISPLAY"),
        ).convert("RGB")

    def size(self) -> tuple[int, int]:
        """Return the X11 primary screen dimensions in pixels."""
        return ImageGrab.grab(xdisplay=os.environ.get("DISPLAY")).size


class VirtualPointerBackend:
    """Inject pointer, wheel and keyboard input through Linux uinput."""

    def __init__(
        self,
        capture: ScreenCapture,
        device: PointerDevice | None = None,
        press_delay_s: float = 0.08,
    ) -> None:
        self._capture = capture
        self._press_delay_s = press_delay_s
        width, height = capture.size()
        if width <= 0 or height <= 0:
            raise ValueError("desktop screen has invalid dimensions")
        self._size = (width, height)
        if device is None:
            capabilities: dict[int, Sequence[int | tuple[int, AbsInfo]]] = {
                ecodes.EV_KEY: [
                    ecodes.BTN_LEFT,
                    *[
                        int(getattr(ecodes, f"KEY_{letter}"))
                        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    ],
                    *[int(getattr(ecodes, f"KEY_{digit}")) for digit in "0123456789"],
                    *[
                        int(getattr(ecodes, f"KEY_{name}"))
                        for name in (
                            "SPACE",
                            "ENTER",
                            "TAB",
                            "ESC",
                            "BACKSPACE",
                            "DELETE",
                            "UP",
                            "DOWN",
                            "LEFT",
                            "RIGHT",
                            "HOME",
                            "END",
                            "PAGEUP",
                            "PAGEDOWN",
                            "LEFTCTRL",
                            "LEFTALT",
                            "LEFTSHIFT",
                            "LEFTMETA",
                            "MINUS",
                            "EQUAL",
                            "LEFTBRACE",
                            "RIGHTBRACE",
                            "BACKSLASH",
                            "SEMICOLON",
                            "APOSTROPHE",
                            "GRAVE",
                            "COMMA",
                            "DOT",
                            "SLASH",
                        )
                    ],
                    *[
                        int(getattr(ecodes, f"KEY_F{number}"))
                        for number in range(1, 13)
                    ],
                ],
                ecodes.EV_ABS: [
                    (ecodes.ABS_X, AbsInfo(0, 0, width - 1, 0, 0, 1)),
                    (ecodes.ABS_Y, AbsInfo(0, 0, height - 1, 0, 0, 1)),
                ],
                ecodes.EV_REL: [ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
            }
            try:
                device = UInput(
                    capabilities,
                    name="Vibana virtual pointer",
                    bustype=ecodes.BUS_USB,
                    input_props=[ecodes.INPUT_PROP_POINTER],
                )
            except OSError as error:
                raise RuntimeError(
                    "cannot open /dev/uinput for virtual pointer input"
                ) from error
            sleep(1)
        self._device = device

    def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
        """Capture a desktop rectangle in screen pixels."""
        return self._capture.screenshot(region)

    def size(self) -> tuple[int, int]:
        """Return the dimensions used to calibrate absolute pointer coordinates."""
        return self._size

    def click(self, x: int, y: int) -> None:
        """Move the pointer to a screen pixel and click the left button."""
        width, height = self._size
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("virtual pointer is outside the desktop screen")
        offset_x = x + 6 if x + 6 < width else max(0, x - 6)
        offset_y = y + 6 if y + 6 < height else max(0, y - 6)
        self._device.write(ecodes.EV_ABS, ecodes.ABS_X, offset_x)
        self._device.write(ecodes.EV_ABS, ecodes.ABS_Y, offset_y)
        self._device.syn()
        sleep(0.05)
        self._device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        self._device.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
        self._device.syn()
        sleep(0.06)
        self._device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
        try:
            self._device.syn()
            sleep(self._press_delay_s)
        finally:
            self._device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
            self._device.syn()

    def scroll(self, x: int, y: int, direction: str, ticks: int) -> None:
        """Move to a screen pixel and send bounded wheel ticks."""
        width, height = self._size
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("virtual pointer is outside the desktop screen")
        if direction not in {"up", "down", "left", "right"} or not 1 <= ticks <= 20:
            raise ValueError("invalid scroll direction or tick count")
        self._device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        self._device.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
        self._device.syn()
        code = ecodes.REL_WHEEL if direction in {"up", "down"} else ecodes.REL_HWHEEL
        value = ticks if direction in {"up", "right"} else -ticks
        self._device.write(ecodes.EV_REL, code, value)
        self._device.syn()

    def _tap(self, code: int, shift: bool = False) -> None:
        if shift:
            self._device.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
            self._device.syn()
        try:
            self._device.write(ecodes.EV_KEY, code, 1)
            try:
                self._device.syn()
            finally:
                self._device.write(ecodes.EV_KEY, code, 0)
                self._device.syn()
        finally:
            if shift:
                self._device.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
                self._device.syn()

    def type_text(self, value: str) -> None:
        """Type printable US-layout ASCII plus newline and tab."""
        punctuation = {
            "-": ("MINUS", False),
            "_": ("MINUS", True),
            "=": ("EQUAL", False),
            "+": ("EQUAL", True),
            "[": ("LEFTBRACE", False),
            "{": ("LEFTBRACE", True),
            "]": ("RIGHTBRACE", False),
            "}": ("RIGHTBRACE", True),
            "\\": ("BACKSLASH", False),
            "|": ("BACKSLASH", True),
            ";": ("SEMICOLON", False),
            ":": ("SEMICOLON", True),
            "'": ("APOSTROPHE", False),
            '"': ("APOSTROPHE", True),
            "`": ("GRAVE", False),
            "~": ("GRAVE", True),
            ",": ("COMMA", False),
            "<": ("COMMA", True),
            ".": ("DOT", False),
            ">": ("DOT", True),
            "/": ("SLASH", False),
            "?": ("SLASH", True),
            "!": ("1", True),
            "@": ("2", True),
            "#": ("3", True),
            "$": ("4", True),
            "%": ("5", True),
            "^": ("6", True),
            "&": ("7", True),
            "*": ("8", True),
            "(": ("9", True),
            ")": ("0", True),
            " ": ("SPACE", False),
            "\n": ("ENTER", False),
            "\t": ("TAB", False),
        }
        for character in value:
            if character.isascii() and character.isalpha():
                name, shift = character.upper(), character.isupper()
            elif character.isascii() and character.isdigit():
                name, shift = character, False
            elif character in punctuation:
                name, shift = punctuation[character]
            else:
                raise ValueError("type_text supports printable US-layout ASCII")
            self._tap(int(getattr(ecodes, f"KEY_{name}")), shift)

    def key_press(self, key: str) -> None:
        """Press one named key with optional Ctrl, Alt, Shift or Super modifiers."""
        modifiers = {
            "CTRL": ecodes.KEY_LEFTCTRL,
            "ALT": ecodes.KEY_LEFTALT,
            "SHIFT": ecodes.KEY_LEFTSHIFT,
            "SUPER": ecodes.KEY_LEFTMETA,
        }
        named = {
            "ENTER": "ENTER",
            "RETURN": "ENTER",
            "TAB": "TAB",
            "ESC": "ESC",
            "ESCAPE": "ESC",
            "BACKSPACE": "BACKSPACE",
            "DELETE": "DELETE",
            "UP": "UP",
            "DOWN": "DOWN",
            "LEFT": "LEFT",
            "RIGHT": "RIGHT",
            "HOME": "HOME",
            "END": "END",
            "PAGEUP": "PAGEUP",
            "PAGEDOWN": "PAGEDOWN",
            "SPACE": "SPACE",
        }
        parts = [part.strip().upper() for part in key.split("+")]
        if not parts or not parts[-1]:
            raise ValueError("unsupported key chord")
        prefix = parts[:-1]
        if len(prefix) != len(set(prefix)) or any(
            part not in modifiers for part in prefix
        ):
            raise ValueError("unsupported key modifier")
        final = parts[-1]
        if len(final) == 1 and final.isascii() and final.isalnum():
            name = final
        elif final in named:
            name = named[final]
        elif (
            final.startswith("F") and final[1:].isdigit() and 1 <= int(final[1:]) <= 12
        ):
            name = final
        else:
            raise ValueError("unsupported key")
        pressed: list[int] = []
        try:
            for part in prefix:
                code = modifiers[part]
                self._device.write(ecodes.EV_KEY, code, 1)
                pressed.append(code)
                self._device.syn()
            self._tap(int(getattr(ecodes, f"KEY_{name}")))
        finally:
            for code in reversed(pressed):
                self._device.write(ecodes.EV_KEY, code, 0)
                self._device.syn()

    def close(self) -> None:
        """Close the virtual pointer device."""
        self._device.close()
