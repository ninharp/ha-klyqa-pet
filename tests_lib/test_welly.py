import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pyklyqa_pet.welly import WellyDevice, WellyMode, WellySettings, WellyState

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"
STATE = "/api/v1/device/state"
SETTINGS = "/api/v1/device/settings"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


@pytest.fixture
def device(session: aiohttp.ClientSession, api: FakeApi) -> WellyDevice:
    return WellyDevice(session, api.host, "tok", api.port)


def test_state_from_dict() -> None:
    state = WellyState.from_dict(load_fixture("welly_state.json"))
    assert state.mode == WellyMode.FRESH_WATER_24H
    assert state.battery_level == 95
    assert state.charging is True
    assert state.heating_enabled is True
    assert state.heating_temperature == 28
    assert state.water_temperature == 23
    assert state.tank_clean == 499
    assert state.tank_sewage == 983
    assert state.drinking_volume == 40
    assert state.total_consumption == 1234
    assert state.daily_goal == 500
    assert state.last_drinking_time == 1756990000
    assert state.filter_life_remaining == 77
    assert state.light_id == 2
    assert state.wifi_rssi == -70
    assert state.error_log[0]["error"] == 260


def test_state_from_minimal_dict() -> None:
    state = WellyState.from_dict({"type": "status"})
    assert state.mode == 0
    assert state.battery_level is None
    assert state.filter_life_remaining is None
    assert state.wifi_rssi is None
    assert state.error_log == []


def test_settings_from_dict_accepts_both_telemetry_keys() -> None:
    settings = WellySettings.from_dict(load_fixture("welly_settings.json"))
    assert settings.telemetry is True
    assert settings.circulation_pump_speed == 80
    other = WellySettings.from_dict({"telemetry": False})
    assert other.telemetry is False


async def test_get_state_and_settings(device: WellyDevice, api: FakeApi) -> None:
    api.add("GET", STATE, 200, load_fixture("welly_state.json"))
    api.add("GET", SETTINGS, 200, load_fixture("welly_settings.json"))
    state = await device.get_state()
    settings = await device.get_settings()
    assert state.water_temperature == 23
    assert settings.radar_sensitivity == 1


@pytest.mark.parametrize(
    ("call", "expected_body"),
    [
        (lambda d: d.set_mode(2), {"mode": 2}),
        (lambda d: d.set_heating(True, 24), {"heating": {"enabled": True, "temperature": 24}}),
        (lambda d: d.set_heating(False), {"heating": {"enabled": False}}),
        (lambda d: d.set_daily_goal(750), {"drinking": {"daily_goal": 750}}),
        (lambda d: d.set_light(3), {"light_id": 3}),
        (lambda d: d.set_descaling(True), {"descaling": 0}),
        (lambda d: d.set_descaling(False), {"descaling": 1}),
    ],
)
async def test_state_commands(
    device: WellyDevice, api: FakeApi, call: Any, expected_body: dict[str, Any]
) -> None:
    api.add("POST", STATE, 200, {"type": "success"})
    await call(device)
    assert api.last_call().json == expected_body


async def test_update_settings(device: WellyDevice, api: FakeApi) -> None:
    payload = load_fixture("welly_settings.json") | {"light_switch": False}
    api.add("POST", SETTINGS, 200, payload)
    settings = await device.update_settings(light_switch=False)
    assert api.last_call().json == {"light_switch": False}
    assert settings.light_switch is False
