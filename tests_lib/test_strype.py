import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pyklyqa_pet.strype import StrypeDevice, StrypeState

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"
COMMAND = "/api/v1/system/command"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


@pytest.fixture
def device(session: aiohttp.ClientSession, api: FakeApi) -> StrypeDevice:
    return StrypeDevice(session, api.host, "tok", api.port)


def make_state(**overrides: Any) -> StrypeState:
    """Build a fully known state to merge responses onto."""
    base: dict[str, Any] = {
        "power_on": True,
        "mode": "rgb",
        "rgb": (1, 2, 3),
        "temperature_kelvin": 2700,
        "brightness_percent": 50,
        "length_metres": 4,
        "wifi_rssi": -60,
        "raw": {},
    }
    return StrypeState(**(base | overrides))


def test_state_from_dict_of_a_real_cmd_mode_capture() -> None:
    """The fixture is a verbatim bare-read response from a real Strype (cmd mode)."""
    state = StrypeState.from_dict(load_fixture("strype_state.json"))
    assert state.power_on is True
    assert state.mode == "cmd"
    assert state.brightness_percent == 100
    assert state.length_metres == 2
    assert state.wifi_rssi == -48
    # Neither colour field is reported in cmd mode and nothing was known before, so
    # both fall back to neutral values.
    assert state.rgb == (0, 0, 0)
    assert state.temperature_kelvin == 0


def test_power_comes_from_status_not_from_the_power_on_key() -> None:
    """`power_on` in the payload is the power-on *behaviour*, not the current state.

    A real device reports `power_on: 0` while lit; only `status` tracks the strip.
    Keying on `power_on` would report every strip as off.
    """
    payload = load_fixture("strype_state.json")
    assert payload["power_on"] == 0
    assert payload["status"] == "on"
    assert StrypeState.from_dict(payload).power_on is True

    assert StrypeState.from_dict(payload | {"status": "off"}).power_on is False


def test_state_from_dict_keeps_the_raw_payload_and_ignores_unmodelled_keys() -> None:
    """`external`, `active_scene`, `reset_reason` etc. are not modelled but not lost."""
    payload = load_fixture("strype_state.json")
    state = StrypeState.from_dict(payload)
    assert state.raw == payload
    assert state.raw["external"]["mode"] == "EXT_UDP"
    assert state.raw["active_command"] == 103


def test_state_from_dict_tolerates_missing_keys() -> None:
    state = StrypeState.from_dict({})
    assert state.power_on is False
    assert state.mode == "rgb"
    assert state.rgb == (0, 0, 0)
    assert state.temperature_kelvin == 0
    assert state.length_metres is None
    assert state.wifi_rssi is None


def test_state_from_dict_of_a_real_rgb_mode_capture() -> None:
    state = StrypeState.from_dict(load_fixture("strype_state_rgb.json"))
    assert state.mode == "rgb"
    assert state.rgb == (255, 0, 0)
    assert "temperature" not in state.raw


def test_state_from_dict_of_a_real_cct_mode_capture() -> None:
    state = StrypeState.from_dict(load_fixture("strype_state_cct.json"))
    assert state.mode == "cct"
    assert state.temperature_kelvin == 4000
    assert "color" not in state.raw


def test_state_from_dict_carries_the_inactive_mode_forward() -> None:
    """In rgb mode the firmware omits `temperature`; the last known value survives."""
    state = StrypeState.from_dict(
        {"status": "on", "mode": "rgb", "color": {"red": 9, "green": 8, "blue": 7}},
        make_state(temperature_kelvin=3300),
    )
    assert state.rgb == (9, 8, 7)
    assert state.temperature_kelvin == 3300


def test_state_from_dict_carries_the_rgb_colour_forward_in_cct_mode() -> None:
    state = StrypeState.from_dict(
        {"status": "on", "mode": "cct", "temperature": 5000},
        make_state(rgb=(11, 22, 33)),
    )
    assert state.mode == "cct"
    assert state.temperature_kelvin == 5000
    assert state.rgb == (11, 22, 33)


def test_state_from_dict_in_cmd_mode_carries_both_colour_fields_forward() -> None:
    """`cmd` mode (an app effect is running) reports neither colour field.

    Both are therefore taken from the previous state; everything the response does
    carry - power, mode, brightness, length - is authoritative.
    """
    state = StrypeState.from_dict(
        {
            "status": "on",
            "mode": "cmd",
            "brightness": {"percentage": 70},
            "length_ret": 6,
        },
        make_state(rgb=(200, 100, 50), temperature_kelvin=4200),
    )
    assert state.rgb == (200, 100, 50)
    assert state.temperature_kelvin == 4200
    assert state.mode == "cmd"
    assert state.brightness_percent == 70
    assert state.length_metres == 6


def test_state_from_dict_prefers_the_response_over_the_previous_state() -> None:
    """A key that is present always wins, including a neutral-looking one."""
    state = StrypeState.from_dict(
        {
            "status": "off",
            "mode": "rgb",
            "color": {"red": 0, "green": 0, "blue": 0},
            "brightness": {"percentage": 0},
        },
        make_state(power_on=True, rgb=(255, 255, 255), brightness_percent=100),
    )
    assert state.power_on is False
    assert state.rgb == (0, 0, 0)
    assert state.brightness_percent == 0


async def test_get_state_uses_the_system_command_endpoint(
    device: StrypeDevice, api: FakeApi
) -> None:
    """There is no `device/state` route on this firmware; reads are bare commands.

    This pins both halves of the transport: the method and path, and the `command`
    envelope the SDK handler requires before it will look at the message at all.
    """
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    state = await device.get_state()
    call = api.last_call()
    assert call.method == "PUT"
    assert call.path == COMMAND
    assert call.json == {"command": {"type": "request"}}
    assert state.brightness_percent == 70


async def test_get_state_merges_onto_the_previous_state(device: StrypeDevice, api: FakeApi) -> None:
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    state = await device.get_state(previous=make_state(temperature_kelvin=3300))
    assert state.rgb == (255, 0, 0)
    assert state.temperature_kelvin == 3300


async def test_set_state_sends_only_given_fields(device: StrypeDevice, api: FakeApi) -> None:
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    state = await device.set_state(power_on=True, rgb=(10, 20, 30), transition_ms=800)
    assert api.last_call().json == {
        "command": {
            "type": "request",
            "status": "on",
            "color": {"red": 10, "green": 20, "blue": 30},
            "transitionTime": 800,
            "temp_fade": {"in": 800},
        }
    }
    assert state.length_metres == 2


async def test_set_state_temperature_and_brightness(device: StrypeDevice, api: FakeApi) -> None:
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    await device.set_state(temperature_kelvin=3000, brightness_percent=42)
    assert api.last_call().json == {
        "command": {
            "type": "request",
            "temperature": 3000,
            "brightness": {"percentage": 42},
        }
    }


async def test_set_state_merges_its_response_onto_the_previous_state(
    device: StrypeDevice, api: FakeApi
) -> None:
    """A write returns the same mode-dependent status message a read does."""
    response = {"type": "status", "status": "on", "mode": "cct", "temperature": 5000}
    api.add("PUT", COMMAND, 200, response)
    state = await device.set_state(temperature_kelvin=5000, previous=make_state(rgb=(7, 7, 7)))
    assert state.temperature_kelvin == 5000
    assert state.rgb == (7, 7, 7)


async def test_set_state_turn_off_transition_sends_the_out_fade(
    device: StrypeDevice, api: FakeApi
) -> None:
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    await device.set_state(power_on=False, transition_ms=2000)
    assert api.last_call().json == {
        "command": {
            "type": "request",
            "status": "off",
            "transitionTime": 2000,
            "temp_fade": {"out": 2000},
        }
    }


async def test_set_state_without_power_change_sends_no_temp_fade(
    device: StrypeDevice, api: FakeApi
) -> None:
    """Colour/brightness-only transitions are honoured via `transitionTime` alone."""
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    await device.set_state(rgb=(1, 2, 3), transition_ms=500)
    command = api.last_call().json["command"]
    assert "temp_fade" not in command
    assert command["transitionTime"] == 500


async def test_set_state_clamps_the_temp_fade_to_the_firmware_minimum(
    device: StrypeDevice, api: FakeApi
) -> None:
    """A 0 in `temp_fade` reads as "not given" to the firmware, so it is raised."""
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json"))
    await device.set_state(power_on=True, transition_ms=0)
    assert api.last_call().json["command"]["temp_fade"] == {"in": 100}


async def test_detect_length(device: StrypeDevice, api: FakeApi) -> None:
    api.add("PUT", COMMAND, 200, load_fixture("strype_state_rgb.json") | {"length_ret": 5})
    state = await device.detect_length()
    assert api.last_call().json == {"command": {"type": "request", "length_detection": 1}}
    assert state.length_metres == 5
