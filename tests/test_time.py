"""Tests for the time platform."""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.time import DOMAIN as TIME_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from custom_components.klyqa_pet.coordinator import KlyqaDeviceCoordinator
from pyklyqa_pet import FoodyTimers, KlyqaDeviceError, SleepMode

from .conftest import load_json, setup_integration


@pytest.fixture
async def times(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.TIME]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "times")
async def test_times(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("times")
async def test_setting_the_sleep_start_preserves_the_end(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """Setting sleep_start must not disturb end, weekdays or the enabled flag."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.feeder_sleep_start", "time": "21:30:00"},
        blocking=True,
    )
    sent = mock_foody.set_sleep_mode.await_args.args[0]
    assert sent.start == time(21, 30)
    assert sent.end == time(6, 0)
    assert sent.enabled is False
    assert sent.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("times")
async def test_setting_the_sleep_end_preserves_the_start(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """Setting sleep_end must not disturb start, weekdays or the enabled flag."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.feeder_sleep_end", "time": "07:15:00"},
        blocking=True,
    )
    sent = mock_foody.set_sleep_mode.await_args.args[0]
    assert sent.end == time(7, 15)
    assert sent.start == time(22, 0)
    assert sent.enabled is False
    assert sent.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("times")
async def test_setting_the_quiet_time_start_preserves_the_rest(
    hass: HomeAssistant, mock_welly: MagicMock
) -> None:
    """Setting quiet_time_start must not disturb end, water or the weekday mask."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.kitchen_fountain_quiet_time_start", "time": "21:30:00"},
        blocking=True,
    )
    sent = mock_welly.set_quiet_time.await_args.args[0]
    assert sent.start == time(21, 30)
    assert sent.end == time(7, 0)
    assert sent.enabled is False
    assert sent.water_enabled is False
    assert sent.weekdays == frozenset(range(7))


@pytest.mark.usefixtures("times")
async def test_setting_the_quiet_time_end_preserves_the_rest(
    hass: HomeAssistant, mock_welly: MagicMock
) -> None:
    """Setting quiet_time_end must not disturb start, water or the weekday mask."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.kitchen_fountain_quiet_time_end", "time": "06:15:00"},
        blocking=True,
    )
    sent = mock_welly.set_quiet_time.await_args.args[0]
    assert sent.end == time(6, 15)
    assert sent.start == time(22, 0)
    assert sent.enabled is False
    assert sent.water_enabled is False
    assert sent.weekdays == frozenset(range(7))


@pytest.fixture
async def sleep_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    """Load both platforms that write the sleep window, as a script would touch them."""
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.SWITCH, Platform.TIME]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("sleep_entities")
async def test_back_to_back_sleep_writes_build_on_the_device_answer(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """A burst of sleep-window writes must not revert one another.

    Each of these entities builds its write from the coordinator's copy of the sleep
    window, and `async_request_refresh` is debounced, so a cache that is only refreshed
    would still hold the pre-burst document for the second and third write. The write's
    own answer - the complete document, as the firmware returns it - is published
    instead, so every write starts from the one before it. The mock's answer carries a
    weekday mask the cache never held, which only a published answer can pick up.
    """
    document = load_json("foody_timers.json")
    workdays = 0b0111110

    def _answer(sleep_mode: SleepMode) -> FoodyTimers:
        return FoodyTimers.from_dict(
            {
                **document,
                "sleep_mode": {**sleep_mode.to_dict(), "weekly_cycle": workdays},
            }
        )

    mock_foody.set_sleep_mode.side_effect = _answer

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.feeder_sleep_mode"},
        blocking=True,
    )
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.feeder_sleep_start", "time": "22:45:00"},
        blocking=True,
    )
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.feeder_sleep_end", "time": "05:15:00"},
        blocking=True,
    )

    third = mock_foody.set_sleep_mode.await_args.args[0]
    assert third.end == time(5, 15)
    # Both would fall back to the document the cache held before the burst - 22:00,
    # disabled, every day - if the writes were not building on each other's answer.
    assert third.start == time(22, 45)
    assert third.enabled is True
    assert third.weekdays == frozenset({1, 2, 3, 4, 5})
    # Nothing was re-read: the answers alone kept the cache current.
    mock_foody.get_timers.assert_awaited_once()


@pytest.mark.usefixtures("times")
async def test_a_failed_sleep_write_marks_the_cache_stale(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """The firmware stores the new window before it tells the MCU, so a rejected write
    may already have moved the device. The published document can no longer be trusted."""
    mock_foody.set_sleep_mode.side_effect = KlyqaDeviceError(["nope"])
    with (
        patch.object(KlyqaDeviceCoordinator, "mark_timers_stale") as mark_stale,
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            TIME_DOMAIN,
            "set_value",
            {ATTR_ENTITY_ID: "time.feeder_sleep_start", "time": "21:30:00"},
            blocking=True,
        )
    assert mark_stale.call_count == 1


@pytest.mark.usefixtures("times")
async def test_a_failed_sleep_write_does_not_force_a_refresh(
    hass: HomeAssistant, mock_foody: MagicMock
) -> None:
    """Re-reading is left to the next scheduled poll; the device just refused a request."""
    mock_foody.set_sleep_mode.side_effect = KlyqaDeviceError(["nope"])
    with (
        patch.object(
            KlyqaDeviceCoordinator, "async_request_refresh", new_callable=AsyncMock
        ) as refresh,
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            TIME_DOMAIN,
            "set_value",
            {ATTR_ENTITY_ID: "time.feeder_sleep_end", "time": "07:15:00"},
            blocking=True,
        )
    refresh.assert_not_awaited()
