import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pyklyqa_pet.foody import FoodyDevice, FoodySettings, FoodyState

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"
STATE = "/api/v1/device/state"
SETTINGS = "/api/v1/device/settings"
CONTROL = "/api/v1/device/control"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


@pytest.fixture
def device(session: aiohttp.ClientSession, api: FakeApi) -> FoodyDevice:
    return FoodyDevice(session, api.host, "tok", api.port)


def test_state_from_dict() -> None:
    state = FoodyState.from_dict(load_fixture("foody_state.json"))
    assert state.power_state is True
    assert state.adapter_state is True
    assert state.battery_level == -1
    assert state.food_bin_state == 1
    assert state.bowl_remaining == 120
    assert state.last_manual_report == 1
    assert state.last_manual_portions == 2
    assert state.last_scheduled_portions == 3
    assert state.next_feed_time == 245
    assert state.last_realtime_weight == 1234
    assert state.mcu_sw_version == 56
    assert state.mcu_hw_version == 2
    assert state.wifi_rssi == -59
    assert state.timestamp == 1755500000


def test_state_without_mcu_version() -> None:
    state = FoodyState.from_dict({"type": "status"})
    assert state.mcu_sw_version is None
    assert state.mcu_hw_version is None
    assert state.error_log == []


def test_settings_from_dict() -> None:
    settings = FoodySettings.from_dict(load_fixture("foody_settings.json"))
    assert settings.feed_audio_volume == 50
    assert settings.charging_protection == 1


async def test_get_state_and_settings(device: FoodyDevice, api: FakeApi) -> None:
    api.add("GET", STATE, 200, load_fixture("foody_state.json"))
    api.add("GET", SETTINGS, 200, load_fixture("foody_settings.json"))
    assert (await device.get_state()).bowl_remaining == 120
    assert (await device.get_settings()).app_led is True


async def test_dispense(device: FoodyDevice, api: FakeApi) -> None:
    api.add("POST", CONTROL, 200, {"type": "success"})
    await device.dispense(3)
    assert api.last_call().json == {"action": "dispense", "control": 1, "portions": 3}


@pytest.mark.parametrize("portions", [0, 41])
async def test_dispense_rejects_out_of_range(device: FoodyDevice, portions: int) -> None:
    with pytest.raises(ValueError):
        await device.dispense(portions)


@pytest.mark.parametrize(
    ("call", "expected_body"),
    [
        (lambda d: d.play_voice_recording(), {"action": "play_voice_rec"}),
        (lambda d: d.query_realtime_weight(), {"action": "query_realtime_weight"}),
    ],
)
async def test_control_actions(
    device: FoodyDevice, api: FakeApi, call: Any, expected_body: dict[str, Any]
) -> None:
    api.add("POST", CONTROL, 200, {"type": "success"})
    await call(device)
    assert api.last_call().json == expected_body


async def test_update_settings(device: FoodyDevice, api: FakeApi) -> None:
    payload = load_fixture("foody_settings.json") | {"feed_audio_volume": 75}
    api.add("POST", SETTINGS, 200, payload)
    settings = await device.update_settings(feed_audio_volume=75)
    assert api.last_call().json == {"feed_audio_volume": 75}
    assert settings.feed_audio_volume == 75
