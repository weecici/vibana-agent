"""Desktop scroll and keyboard actions remain bounded and observable."""

from collections.abc import Sequence
from io import BytesIO

import pytest
from evdev import AbsInfo, ecodes
from PIL import Image
from pydantic import ValidationError

from vibana_agent import controller, desktop
from vibana_agent.config import Settings
from vibana_agent.desktop import VirtualPointerBackend
from vibana_agent.schema import Action, Candidate, Evidence, Scenario


def frame(color: str) -> bytes:
    """Return a small screenshot for a controlled desktop workflow."""
    output = BytesIO()
    Image.new("RGB", (320, 200), color).save(output, format="PNG")
    return output.getvalue()


class RecordingExecutor:
    """Record input actions while returning before and after frames."""

    def __init__(self) -> None:
        self.actions: list[Action] = []
        self.frames = iter([frame("red"), frame("green")] * 3)

    def capture(self) -> bytes:
        return next(self.frames)

    def perform(self, action: Action) -> None:
        self.actions.append(action)

    def viewport(self) -> tuple[int, int]:
        return 320, 200

    def close(self) -> None:
        pass


class RecordingObserver:
    """Collect annotated action screenshots."""

    def __init__(self) -> None:
        self.actions: list[bytes | None] = []

    def record(
        self,
        step_number: int,
        attempt_number: int,
        before: bytes,
        action: bytes | None,
        after: bytes | None,
    ) -> None:
        self.actions.append(action)


class AlwaysMetVerifier:
    """Accept fresh screenshots for input routing tests."""

    def verify(
        self, before: bytes, after: bytes, instruction: str, settings: Settings
    ) -> Evidence:
        assert before != after
        return Evidence(matched=True, observed_text="changed", source="vision")


class UnmetVerifier:
    """Leave a keyboard action without positive visual proof."""

    def verify(
        self, before: bytes, after: bytes, instruction: str, settings: Settings
    ) -> Evidence:
        return Evidence(matched=False, observed_text="uncertain", source="vision")


@pytest.mark.parametrize(
    ("spec", "kind"),
    [
        ({"kind": "scroll", "direction": "down", "ticks": 3}, "scroll"),
        ({"kind": "type_text", "text": "hello"}, "type_text"),
        ({"kind": "key_press", "key": "Ctrl+A"}, "key_press"),
    ],
)
def test_desktop_explicit_actions_skip_candidate_selection(
    spec: dict[str, object], kind: str
) -> None:
    scenario = Scenario.model_validate(
        {
            "name": "inputs",
            "target": "desktop",
            "steps": [{"instruction": "perform input", "action": spec}],
        }
    )

    class UnexpectedSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            raise AssertionError("explicit input must not select a click target")

    executor = RecordingExecutor()
    observer = RecordingObserver()
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(),
        observer,
        UnexpectedSelector(),
        verifier=AlwaysMetVerifier(),
    )
    assert report.status == "PASS"
    assert executor.actions[0].kind == kind
    assert observer.actions[0] is not None


@pytest.mark.parametrize("kind", ["type_text", "key_press"])
def test_unverified_keyboard_action_is_not_repeated(kind: str) -> None:
    spec = (
        {"kind": "type_text", "text": "hello"}
        if kind == "type_text"
        else {"kind": "key_press", "key": "Enter"}
    )
    scenario = Scenario.model_validate(
        {
            "name": "uncertain_keyboard",
            "target": "desktop",
            "steps": [{"instruction": "input", "action": spec}],
        }
    )

    class UnexpectedSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            raise AssertionError("keyboard input must not select a candidate")

    executor = RecordingExecutor()
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(max_attempts=3),
        RecordingObserver(),
        UnexpectedSelector(),
        verifier=UnmetVerifier(),
    )
    assert report.status == "FAIL"
    assert len(executor.actions) == 1


@pytest.mark.parametrize(
    ("instruction", "kind"),
    [
        ("scroll down 3 ticks", "scroll"),
        ("type: battery status", "type_text"),
        ("press Ctrl+A", "key_press"),
    ],
)
def test_plain_desktop_input_instructions_route_without_click_selection(
    instruction: str, kind: str
) -> None:
    scenario = Scenario.model_validate(
        {
            "name": "plain_input",
            "target": "desktop",
            "steps": [{"instruction": instruction}],
        }
    )

    class UnexpectedSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            raise AssertionError("input instruction must not select a click target")

    executor = RecordingExecutor()
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(),
        RecordingObserver(),
        UnexpectedSelector(),
        verifier=AlwaysMetVerifier(),
    )
    assert report.status == "PASS"
    assert executor.actions[0].kind == kind


def test_search_instruction_types_query_and_submits_it() -> None:
    query = "How to become AI Engineer"
    scenario = Scenario.model_validate(
        {
            "name": "search",
            "target": "desktop",
            "steps": [{"instruction": f'Search for "{query}"'}],
        }
    )

    class UnexpectedSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            raise AssertionError("search instruction must route to keyboard input")

    executor = RecordingExecutor()
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(),
        RecordingObserver(),
        UnexpectedSelector(),
        verifier=AlwaysMetVerifier(),
    )
    assert report.status == "PASS"
    assert executor.actions[0].kind == "type_text"
    assert executor.actions[0].text == query
    assert executor.actions[0].submit


def test_search_instruction_uses_explicit_mapping_before_model_planner() -> None:
    query = "How to become AI Engineer"
    scenario = Scenario.model_validate(
        {
            "name": "planned_search",
            "target": "desktop",
            "steps": [{"instruction": f'Search for "{query}"'}],
        }
    )

    class UnexpectedSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            raise AssertionError("search instruction must route to keyboard input")

    class UnexpectedPlanner:
        def plan(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
            viewport: tuple[int, int],
        ) -> tuple[Action, Candidate | None]:
            raise AssertionError("known search syntax must not reach the model")

    executor = RecordingExecutor()
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(),
        RecordingObserver(),
        UnexpectedSelector(),
        verifier=AlwaysMetVerifier(),
        planner=UnexpectedPlanner(),
    )
    assert report.status == "PASS"
    assert executor.actions[0].kind == "type_text"
    assert executor.actions[0].text == query
    assert executor.actions[0].submit


def test_desktop_action_planner_handles_unstructured_text_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = Scenario.model_validate(
        {
            "name": "planner_input",
            "target": "desktop",
            "steps": [{"instruction": "Enter the VIN 123 into the focused field"}],
        }
    )
    monkeypatch.setattr(controller, "perceive", lambda *args, **kwargs: [])

    class UnexpectedSelector:
        def select(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
        ) -> Candidate:
            raise AssertionError("planner should handle this desktop instruction")

    class FakePlanner:
        def plan(
            self,
            image: bytes,
            instruction: str,
            candidates: list[Candidate],
            settings: Settings,
            viewport: tuple[int, int],
        ) -> tuple[Action, Candidate | None]:
            assert instruction == "Enter the VIN 123 into the focused field"
            return Action(kind="type_text", text="123", instruction=instruction), None

    executor = RecordingExecutor()
    report = controller.run_scenario(
        scenario,
        executor,
        Settings(),
        RecordingObserver(),
        UnexpectedSelector(),
        verifier=AlwaysMetVerifier(),
        planner=FakePlanner(),
    )
    assert report.status == "PASS"
    assert executor.actions[0].kind == "type_text"
    assert executor.actions[0].text == "123"


def test_non_click_actions_are_desktop_only() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(
            {
                "name": "bad",
                "target": "hmi_mock",
                "steps": [
                    {
                        "instruction": "scroll",
                        "action": {"kind": "scroll", "direction": "down", "ticks": 1},
                        "expect": {"text_visible": "More"},
                    }
                ],
            }
        )


def test_text_action_rejects_unsupported_characters_before_input() -> None:
    with pytest.raises(ValidationError, match="printable ASCII"):
        Action(kind="type_text", text="aé")


def test_scroll_coordinates_must_be_paired_and_bounded() -> None:
    for spec in (
        {"kind": "scroll", "direction": "down", "ticks": 1, "x": 10},
        {"kind": "scroll", "direction": "down", "ticks": 21},
    ):
        with pytest.raises(ValidationError):
            Scenario.model_validate(
                {
                    "name": "bad_scroll",
                    "target": "desktop",
                    "steps": [{"instruction": "scroll", "action": spec}],
                }
            )


def test_virtual_input_scroll_and_keyboard_events() -> None:
    class Capture:
        def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
            return Image.new("RGB", (region[2], region[3]))

        def size(self) -> tuple[int, int]:
            return 320, 200

    class Device:
        def __init__(self) -> None:
            self.events: list[tuple[int, int, int]] = []

        def write(self, event_type: int, code: int, value: int) -> None:
            self.events.append((event_type, code, value))

        def syn(self) -> None:
            pass

        def close(self) -> None:
            pass

    device = Device()
    backend = VirtualPointerBackend(
        Capture(), device=device, press_delay_s=0, keyboard_device=device
    )
    backend.scroll(100, 120, "down", 3)
    backend.type_text("Hi!")
    backend.key_press("Ctrl+A")
    assert (ecodes.EV_REL, ecodes.REL_WHEEL, -3) in device.events
    assert (ecodes.EV_KEY, ecodes.KEY_H, 1) in device.events
    assert (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1) in device.events
    assert (ecodes.EV_KEY, ecodes.KEY_A, 1) in device.events
    assert (ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1) in device.events
    assert device.events[-1] == (ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)


def test_pointer_and_keyboard_use_separate_device_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A keyboard capability must not change the working pointer profile."""

    class Capture:
        def screenshot(self, region: tuple[int, int, int, int]) -> Image.Image:
            return Image.new("RGB", (region[2], region[3]))

        def size(self) -> tuple[int, int]:
            return 320, 200

    class Device:
        def write(self, event_type: int, code: int, value: int) -> None:
            pass

        def syn(self) -> None:
            pass

        def close(self) -> None:
            pass

    capabilities_seen: list[dict[int, Sequence[int | tuple[int, AbsInfo]]]] = []

    def fake_uinput(
        capabilities: dict[int, Sequence[int | tuple[int, AbsInfo]]],
        name: str,
        bustype: int,
        input_props: list[int] | None = None,
    ) -> Device:
        capabilities_seen.append(capabilities)
        return Device()

    monkeypatch.setattr(desktop, "UInput", fake_uinput)
    monkeypatch.setattr(desktop, "sleep", lambda seconds: None)
    backend = VirtualPointerBackend(Capture())
    try:
        assert capabilities_seen[0][ecodes.EV_KEY] == [ecodes.BTN_LEFT]
        backend.type_text("a")
        assert len(capabilities_seen) == 2
        assert ecodes.EV_ABS not in capabilities_seen[1]
    finally:
        backend.close()
