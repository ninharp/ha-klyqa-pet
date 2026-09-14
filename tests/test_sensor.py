"""Tests for the sensor platform."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from pyklyqa_pet.foody_timers import FoodyTimers
from pyklyqa_pet.welly_timers import WellyTimers

from .conftest import load_json, setup_integration


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_sensor_values(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.kitchen_fountain_water_temperature").state == "23"
    assert hass.states.get("sensor.kitchen_fountain_pump_status").state == "low_water"
    assert hass.states.get("sensor.feeder_bowl_remaining").state == "120"
    assert hass.states.get("sensor.feeder_real_time_weight").state == "123.4"
    assert hass.states.get("sensor.feeder_feeding_state").state == "idle"
    assert hass.states.get("sensor.klyqa_airpurifier_e85dfc_pm2_5").state == "12"
    assert hass.states.get("sensor.klyqa_airpurifier_e85dfc_air_quality").state == "good"


async def test_strype_length_and_mode_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.living_room_strip_strip_length").state == "3"
    assert hass.states.get("sensor.living_room_strip_light_mode").state == "rgb"


async def test_schedule_sensor_counts_enabled_and_lists_all(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    state = hass.states.get("sensor.feeder_feeding_schedules")
    assert state.state == "1"
    assert state.attributes["schedules"] == [
        {
            "schedule_id": 0,
            "enabled": True,
            "skip_once": False,
            "time": "06:30",
            "weekdays": ["sun", "mon", "tue", "wed", "thu", "fri", "sat"],
            "portions": 2,
            "fresh_food_mode": False,
            "auto_play_voice": True,
        }
    ]


async def test_schedule_sensor_counts_only_enabled_and_orders_weekdays(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_foody: MagicMock,
) -> None:
    """A constructed multi-schedule fixture, not a device capture (see the file).

    A single, fully-enabled, every-day schedule (the real device capture used by
    other tests) cannot tell a correct implementation from a broken one: counting
    all schedules instead of only enabled ones still yields "1", and iterating a
    raw frozenset instead of sorting it still yields all seven weekdays in the
    same order. This fixture has one enabled schedule with a partial weekday mask
    and one disabled schedule, so both mistakes would fail these assertions.
    """
    mock_foody.get_timers = AsyncMock(
        return_value=FoodyTimers.from_dict(load_json("foody_timers_multi.json"))
    )
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    state = hass.states.get("sensor.feeder_feeding_schedules")
    # Only the enabled schedule counts, even though two are present.
    assert state.state == "1"
    assert state.attributes["schedules"] == [
        {
            "schedule_id": 0,
            "enabled": True,
            "skip_once": False,
            "time": "18:05",
            # week_cycle 42 = bits 1,3,5 = Mon, Wed, Fri; a raw set iteration would
            # not reliably reproduce this Sunday-first order.
            "weekdays": ["mon", "wed", "fri"],
            "portions": 3,
            "fresh_food_mode": False,
            "auto_play_voice": True,
        },
        {
            "schedule_id": 1,
            "enabled": False,
            "skip_once": False,
            "time": "00:00",
            # week_cycle 65 = bits 0,6 = Sun, Sat.
            "weekdays": ["sun", "sat"],
            "portions": 1,
            "fresh_food_mode": True,
            "auto_play_voice": False,
        },
    ]


async def test_schedule_sensor_with_no_schedules(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_foody: MagicMock,
) -> None:
    """The zero-schedules path: state "0" and an empty attribute list."""
    mock_foody.get_timers = AsyncMock(
        return_value=FoodyTimers.from_dict(load_json("foody_timers_empty.json"))
    )
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    state = hass.states.get("sensor.feeder_feeding_schedules")
    assert state.state == "0"
    assert state.attributes["schedules"] == []


async def test_descaling_sensors_unknown_when_never_descaled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    """The real capture's `last_descale_time` of 0 means "never" - both are unknown."""
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.kitchen_fountain_last_descaling").state == "unknown"
    assert hass.states.get("sensor.kitchen_fountain_next_descaling").state == "unknown"


async def test_next_descaling_from_last_descale_and_interval(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """With a recorded descaling, `next_descaling` is `last_descale + interval_days`."""
    mock_welly.get_timers = AsyncMock(
        return_value=WellyTimers.from_dict(
            {
                **load_json("welly_timers.json"),
                "dm_timer": {
                    "enabled": True,
                    "interval": 15,
                    "last_descale_time": 1788615614,
                },
            }
        )
    )
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SENSOR]):
        await setup_integration(hass, mock_config_entry)
    last_descaling = hass.states.get("sensor.kitchen_fountain_last_descaling")
    next_descaling = hass.states.get("sensor.kitchen_fountain_next_descaling")
    assert last_descaling.state != "unknown"
    expected = datetime.fromtimestamp(1788615614, tz=UTC) + timedelta(days=15)
    assert datetime.fromisoformat(next_descaling.state) == expected
