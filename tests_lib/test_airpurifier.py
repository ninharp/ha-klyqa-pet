import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pyklyqa_pet.airpurifier import AirPurifierDevice, AirPurifierRunMode, AirPurifierState

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"
STATE = "/api/v1/device/state"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


@pytest.fixture
def device(session: aiohttp.ClientSession, api: FakeApi) -> AirPurifierDevice:
    return AirPurifierDevice(session, api.host, "tok", api.port)


def test_state_from_dict() -> None:
    state = AirPurifierState.from_dict(load_fixture("airpurifier_state.json"))
    assert state.power is True
    assert state.child_lock is False
    assert state.key_tone is True
    assert state.aqi_grade == 1
    assert state.aqi_value == 12
    assert state.fan_level == 2
    assert state.run_mode == AirPurifierRunMode.AUTO
    assert state.total_run_time == 7200
    assert state.air_volume == 500
    assert state.filter_id == "F123"
    assert state.filter_remaining_time == 200000
    assert state.led_custom is True
    assert (state.led_red, state.led_green, state.led_blue) == (160, 40, 240)
    assert state.led_brightness == 80
    assert state.ionizer_switch is True
    assert state.ionizer_active is True
    assert state.tilted is False
    assert state.filter_removed is False
    assert state.wifi_rssi == -55


def test_state_from_minimal_dict() -> None:
    state = AirPurifierState.from_dict({"type": "status", "status": "off"})
    assert state.power is False
    assert state.led_custom is False
    assert state.wifi_rssi is None


@pytest.mark.parametrize(
    ("call", "expected_body"),
    [
        (lambda d: d.set_power(True), {"type": "request", "status": "on"}),
        (lambda d: d.set_power(False), {"type": "request", "status": "off"}),
        (lambda d: d.set_fan_level(3), {"type": "request", "p_level": 3}),
        (lambda d: d.set_run_mode(2), {"type": "request", "run_mode": 2}),
        (lambda d: d.set_led(False), {"type": "request", "les": "off"}),
        (
            lambda d: d.set_led(True, (1, 2, 3)),
            {"type": "request", "les": "on", "color": {"red": 1, "green": 2, "blue": 3}},
        ),
        (
            lambda d: d.set_led(True, None, 42),
            {"type": "request", "les": "on", "brightness": {"percentage": 42}},
        ),
        (
            lambda d: d.set_led(True, (1, 2, 3), 42),
            {
                "type": "request",
                "les": "on",
                "color": {"red": 1, "green": 2, "blue": 3},
                "brightness": {"percentage": 42},
            },
        ),
        (lambda d: d.set_ionizer(True), {"type": "request", "anion_switch": 1}),
        (lambda d: d.set_child_lock(True), {"type": "request", "child_lock": 1}),
        (lambda d: d.set_key_tone(False), {"type": "request", "key_tone": 0}),
    ],
)
async def test_state_commands(
    device: AirPurifierDevice, api: FakeApi, call: Any, expected_body: dict[str, Any]
) -> None:
    api.add("POST", STATE, 200, {"type": "success"})
    await call(device)
    assert api.last_call().json == expected_body


@pytest.mark.parametrize("level", [0, 4])
async def test_fan_level_out_of_range(device: AirPurifierDevice, level: int) -> None:
    with pytest.raises(ValueError):
        await device.set_fan_level(level)


@pytest.mark.parametrize("brightness", [-1, 101])
async def test_led_brightness_out_of_range(device: AirPurifierDevice, brightness: int) -> None:
    with pytest.raises(ValueError):
        await device.set_led(True, brightness=brightness)


async def test_get_state(device: AirPurifierDevice, api: FakeApi) -> None:
    api.add("GET", STATE, 200, load_fixture("airpurifier_state.json"))
    assert (await device.get_state()).fan_level == 2
