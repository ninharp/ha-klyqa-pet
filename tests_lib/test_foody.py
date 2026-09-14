from datetime import time
import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pyklyqa_pet.exceptions import KlyqaDeviceError
from pyklyqa_pet.foody import FoodyDevice, FoodySettings, FoodyState
from pyklyqa_pet.foody_timers import FeedingSchedule, SleepMode

from .conftest import FakeApi

FIXTURES = Path(__file__).parent / "fixtures"
STATE = "/api/v1/device/state"
SETTINGS = "/api/v1/device/settings"
CONTROL = "/api/v1/device/control"
TIMER = "/api/v1/device/timer"


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


async def test_get_timers_reads_the_timer_endpoint(device: FoodyDevice, api: FakeApi) -> None:
    api.add("GET", TIMER, 200, load_fixture("foody_timers.json"))
    timers = await device.get_timers()
    assert timers.schedules[0].execution_time == time(6, 30)
    assert api.last_call().json is None


async def test_delete_schedule_sends_the_del_action(device: FoodyDevice, api: FakeApi) -> None:
    api.add("POST", TIMER, 200, load_fixture("foody_timers.json"))
    await device.delete_schedule(3)
    assert api.last_call().json == {"action": "del", "data": {"schedule_id": 3}}


async def test_set_schedule_uses_add_or_mod(device: FoodyDevice, api: FakeApi) -> None:
    api.add("POST", TIMER, 200, load_fixture("foody_timers.json"))
    schedule = FeedingSchedule(
        schedule_id=1,
        enabled=True,
        skip_once=False,
        execution_time=time(7, 0),
        weekdays=frozenset(range(7)),
        portions=2,
        total_duration_sec=0,
        fresh_food_mode=False,
        auto_play_voice=True,
    )
    await device.set_schedule(schedule, create=True)
    assert api.last_call().json["action"] == "add"
    assert api.last_call().json["data"]["execution_time"] == 700
    await device.set_schedule(schedule, create=False)
    assert api.last_call().json["action"] == "mod"


async def test_set_sleep_mode_sends_the_sleep_mode_action(
    device: FoodyDevice, api: FakeApi
) -> None:
    api.add("POST", TIMER, 200, load_fixture("foody_timers.json"))
    sleep_mode = SleepMode(
        enabled=True, weekdays=frozenset(range(7)), start=time(22, 0), end=time(6, 0)
    )
    await device.set_sleep_mode(sleep_mode)
    assert api.last_call().json == {"action": "sleep_mode", "data": sleep_mode.to_dict()}


async def test_a_rejected_write_raises_despite_http_200(device: FoodyDevice, api: FakeApi) -> None:
    """The firmware answers 200 with type "timer" and a filled error array."""
    api.add(
        "POST",
        TIMER,
        200,
        {
            "error": ["Schedule ID not found"],
            "type": "timer",
            "schedules": [
                {
                    "schedule_id": 0,
                    "enable": True,
                    "skip_once": False,
                    "execution_time": 630,
                    "week_cycle": 127,
                    "portions": 2,
                    "total_duration_sec": 0,
                    "fresh_food_mode": False,
                    "auto_play_voice": True,
                }
            ],
            "sleep_mode": {"enable": False, "weekly_cycle": 0, "start_time": 0, "end_time": 0},
        },
    )
    with pytest.raises(KlyqaDeviceError) as excinfo:
        await device.delete_schedule(19)
    assert "Schedule ID not found" in str(excinfo.value)


async def test_an_empty_error_array_is_not_an_error(device: FoodyDevice, api: FakeApi) -> None:
    payload = load_fixture("foody_timers.json") | {"error": []}
    api.add("POST", TIMER, 200, payload)
    result = await device.delete_schedule(0)
    assert result.schedules[0].schedule_id == 0


async def test_a_non_list_numeric_error_still_raises(device: FoodyDevice, api: FakeApi) -> None:
    payload = load_fixture("foody_timers.json") | {"error": 42}
    api.add("POST", TIMER, 200, payload)
    with pytest.raises(KlyqaDeviceError) as excinfo:
        await device.delete_schedule(19)
    assert excinfo.value.errors == ["42"]


async def test_a_bare_string_error_is_not_iterated_per_character(
    device: FoodyDevice, api: FakeApi
) -> None:
    payload = load_fixture("foody_timers.json") | {"error": "boom"}
    api.add("POST", TIMER, 200, payload)
    with pytest.raises(KlyqaDeviceError) as excinfo:
        await device.delete_schedule(19)
    assert excinfo.value.errors == ["boom"]
