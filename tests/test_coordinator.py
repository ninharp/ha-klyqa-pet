"""Tests for the coordinator: translated UpdateFailed messages and settings polling."""

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from datetime import time, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.switch import SERVICE_TURN_ON
from homeassistant.const import ATTR_ENTITY_ID, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.klyqa_pet.const import (
    DEFAULT_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from custom_components.klyqa_pet.coordinator import KlyqaDeviceCoordinator
from custom_components.klyqa_pet.entity import KlyqaPetEntity
from pyklyqa_pet import KlyqaConnectionError, KlyqaRateLimitError, StrypeState, WellySettings
from pyklyqa_pet.welly_timers import QuietTime, WellyTimers

from .conftest import FOODY_ID, PURIFIER_ID, STRYPE_ID, WELLY_ID, load_json, setup_integration


@pytest.mark.parametrize(
    ("stored_value", "expected_seconds"),
    [
        (0, MIN_SCAN_INTERVAL),
        (-5, MIN_SCAN_INTERVAL),
        ("not-a-number", int(DEFAULT_SCAN_INTERVAL.total_seconds())),
        (MAX_SCAN_INTERVAL + 100, MAX_SCAN_INTERVAL),
    ],
)
async def test_coordinator_hardens_bad_stored_scan_interval(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    stored_value: object,
    expected_seconds: int,
) -> None:
    """A bad stored scan interval must never yield a bad update_interval.

    Values out of the MIN_SCAN_INTERVAL/MAX_SCAN_INTERVAL bounds are clamped, and
    non-numeric values fall back to DEFAULT_SCAN_INTERVAL. The options flow itself
    cannot produce these values; this guards the read side against anything else that
    can (e.g. editing .storage directly, or a programmatic async_update_entry).
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_SCAN_INTERVAL: stored_value}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert coordinator.update_interval == timedelta(seconds=expected_seconds)


async def test_update_failed_message_is_rendered(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """The UpdateFailed raised for a plain connection error must render, not stay a bare key.

    Regression test for a startup race: on a real HA instance, the very first coordinator
    refresh (triggered synchronously while the config entry is being set up) could run
    before this integration's own "exceptions" translations were cached, so the log showed
    the literal translation key ("update_failed") instead of the rendered message. See
    custom_components/klyqa_pet/__init__.py:async_setup_entry, which now loads this
    integration's translations up front to close that race.
    """
    await setup_integration(hass, mock_config_entry)
    mock_welly.get_state.side_effect = KlyqaConnectionError("device answered HTTP 500")
    # A coordinator only polls while an entity listens to it.
    mock_config_entry.runtime_data.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert coordinator.last_update_success is False
    message = str(coordinator.last_exception)
    assert message != "update_failed"
    assert coordinator.device_name in message
    assert "device answered HTTP 500" in message


async def test_rate_limit_message_is_rendered(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """A persistent KlyqaRateLimitError renders the dedicated rate_limited message."""
    await setup_integration(hass, mock_config_entry)
    mock_welly.get_state.side_effect = KlyqaRateLimitError("rate limited")
    mock_config_entry.runtime_data.coordinators[WELLY_ID].async_add_listener(lambda: None)

    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert coordinator.last_update_success is False
    message = str(coordinator.last_exception)
    assert coordinator.device_name in message
    assert "rate limit" in message.lower()


async def test_settings_fetched_every_fourth_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """Settings are fetched at setup, cached for the next two polls, then reloaded."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    coordinator.async_add_listener(lambda: None)

    assert mock_welly.get_settings.call_count == 1

    for _ in range(2):
        freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert mock_welly.get_settings.call_count == 1

    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_welly.get_settings.call_count == 2


async def test_settings_write_reloads_on_next_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """A settings write forces the refresh it triggers to reload settings."""
    await setup_integration(hass, mock_config_entry)
    assert mock_welly.get_settings.call_count == 1

    mock_welly.update_settings.return_value = WellySettings.from_dict(
        load_json("welly_settings.json")
    )
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.kitchen_fountain_light"},
        blocking=True,
    )

    assert mock_welly.get_settings.call_count == 2


async def test_strype_poll_merges_onto_the_previous_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_strype: MagicMock,
) -> None:
    """Each poll hands the last known state to the library to merge the response onto."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[STRYPE_ID]
    assert coordinator.data.strype.length_metres == 3
    # The first read has nothing to merge onto.
    assert mock_strype.get_state.await_args.kwargs["previous"] is None

    await coordinator.async_refresh()
    assert mock_strype.get_state.await_count == 2
    assert mock_strype.get_state.await_args.kwargs["previous"] is not None


async def test_strype_write_is_published_without_another_poll(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_strype: MagicMock,
) -> None:
    """A write's response is already merged, so entity.py publishes it directly.

    There is no state GET on this firmware, so refreshing after a write would only
    repeat the same request; the merged result the write returned is complete.
    """
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[STRYPE_ID]
    entity = KlyqaPetEntity(coordinator, EntityDescription(key="test"))

    polled = coordinator.data.strype
    assert polled.rgb == (255, 128, 0)
    get_state_calls = mock_strype.get_state.await_count

    # What a cmd-mode response to a power flip looks like once merged: neither colour
    # field was reported, so both were carried forward from `polled`.
    result = StrypeState.from_dict(
        {"status": "off", "mode": "cmd", "brightness": {"percentage": 70}, "length_ret": 7},
        polled,
    )

    async def _command() -> StrypeState:
        return result

    await entity._async_send(_command())
    await hass.async_block_till_done()

    assert mock_strype.get_state.await_count == get_state_calls
    published = coordinator.data.strype
    assert published.power_on is False
    assert published.mode == "cmd"
    assert published.rgb == (255, 128, 0)
    assert published.temperature_kelvin == polled.temperature_kelvin
    assert published.length_metres == 7
    # The published state also becomes the base for the next poll's merge.
    assert coordinator.strype_state == published


async def test_coordinator_uses_default_scan_interval_without_option(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """An entry with no stored scan_interval option polls at the 30 s default."""
    assert CONF_SCAN_INTERVAL not in mock_config_entry.options
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL


async def test_coordinator_uses_configured_scan_interval(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """An entry with a stored scan_interval option polls at that interval instead."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_SCAN_INTERVAL: 120}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert coordinator.update_interval == timedelta(seconds=120)


async def test_foody_timers_fetched_every_fourth_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_foody: MagicMock,
) -> None:
    """Timers ride the settings cadence: fetched at setup, then every fourth poll."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[FOODY_ID]
    coordinator.async_add_listener(lambda: None)

    assert mock_foody.get_timers.call_count == 1

    for _ in range(2):
        freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert mock_foody.get_timers.call_count == 1

    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_foody.get_timers.call_count == 2


async def test_marking_timers_stale_reloads_on_the_next_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_foody: MagicMock,
) -> None:
    """mark_timers_stale() forces the refresh it triggers to re-read device/timer."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[FOODY_ID]
    assert mock_foody.get_timers.call_count == 1

    coordinator.mark_timers_stale()
    await coordinator.async_refresh()

    assert mock_foody.get_timers.call_count == 2


async def test_other_device_types_have_no_timers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_purifier: MagicMock,
) -> None:
    """An air purifier coordinator exposes timers as None, not an empty document."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[PURIFIER_ID]

    assert coordinator.data.timers is None
    assert not hasattr(mock_purifier, "get_timers") or mock_purifier.get_timers.call_count == 0


async def test_welly_timers_fetched_every_fourth_poll(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """Timers ride the settings cadence: fetched at setup, then every fourth poll."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    coordinator.async_add_listener(lambda: None)

    assert mock_welly.get_timers.call_count == 1

    for _ in range(2):
        freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert mock_welly.get_timers.call_count == 1

    freezer.tick(DEFAULT_SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_welly.get_timers.call_count == 2


async def test_marking_welly_timers_stale_reloads_on_the_next_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """mark_timers_stale() forces the refresh it triggers to re-read device/timer."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    assert mock_welly.get_timers.call_count == 1

    coordinator.mark_timers_stale()
    await coordinator.async_refresh()

    assert mock_welly.get_timers.call_count == 2


async def test_a_welly_timer_write_publishes_without_refetching(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """The library already re-read; the entity path must not poll a third time.

    `WellyDevice`'s five timer-write methods each perform their own follow-up
    GET and return the fresh `WellyTimers`, exactly like the Foody's timer
    writes. entity.py's `_async_send` must publish that result directly
    instead of asking the coordinator to refresh - a refresh is debounced and
    would silently swallow a later write in a burst.

    A timer write is handed in as a factory rather than a started coroutine, so
    the read it builds from happens inside the coordinator's write lock.
    """
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    entity = KlyqaPetEntity(coordinator, EntityDescription(key="test"))

    get_timers_calls = mock_welly.get_timers.call_count

    result = WellyTimers.from_dict(load_json("welly_timers.json"))

    async def _command() -> WellyTimers:
        return result

    await entity._async_send(_command, writes_timers=True)
    await hass.async_block_till_done()

    assert mock_welly.get_timers.call_count == get_timers_calls
    assert coordinator.data.timers is result
    assert coordinator.data.welly_timers is result


async def test_two_timer_entity_writes_serialise(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """A second timer write must build on the first one's answer, not on the snapshot.

    Every timer entity builds its write from the coordinator's cached document with
    `replace`, changing one field. `PARALLEL_UPDATES = 1` serialises that only within
    one platform, so a script touching the quiet-time switch and the quiet-time start
    in the same tick runs both read-modify-writes concurrently. Taking the coordinator's
    write lock around build, write and publish is what stops the second write from
    reverting the first one's field.
    """
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    entity = KlyqaPetEntity(coordinator, EntityDescription(key="test"))
    document = load_json("welly_timers.json")
    assert coordinator.data.welly_timers.quiet_time.start == time(22, 0)
    assert coordinator.data.welly_timers.quiet_time.enabled is False

    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def _answer(quiet_time: QuietTime) -> WellyTimers:
        """Stand in for the device: answer with the document that write would produce."""
        return WellyTimers.from_dict({**document, "ndt_timer": quiet_time.to_dict()})

    async def _slow_answer(quiet_time: QuietTime) -> WellyTimers:
        first_started.set()
        await release_first.wait()
        return await _answer(quiet_time)

    def _set_start() -> Coroutine[Any, Any, WellyTimers]:
        return _slow_answer(replace(coordinator.data.welly_timers.quiet_time, start=time(21, 30)))

    def _turn_on() -> Coroutine[Any, Any, WellyTimers]:
        return _answer(replace(coordinator.data.welly_timers.quiet_time, enabled=True))

    first = asyncio.create_task(entity._async_send(_set_start, writes_timers=True))
    await first_started.wait()
    second = asyncio.create_task(entity._async_send(_turn_on, writes_timers=True))
    await asyncio.sleep(0)
    # The first write still holds the lock, so the second has not read anything yet.
    assert not second.done()
    release_first.set()
    await first
    await second
    await hass.async_block_till_done()

    quiet_time = coordinator.data.welly_timers.quiet_time
    assert quiet_time.enabled is True
    # Built from the pre-first snapshot, the second write would have sent 22:00 back.
    assert quiet_time.start == time(21, 30)


async def test_a_non_timer_entity_write_takes_no_lock(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    mock_welly: MagicMock,
) -> None:
    """Only timer writes go through the write lock; the rest are unchanged.

    A settings write is still handed in as a started coroutine and still marks the
    settings cache stale and asks for a refresh. Running it while the lock is held -
    as a service would hold it - proves it does not wait for the lock.
    """
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinators[WELLY_ID]
    entity = KlyqaPetEntity(coordinator, EntityDescription(key="test"))
    settings = coordinator.data.welly_settings

    async def _command() -> WellySettings:
        return settings

    with patch.object(KlyqaDeviceCoordinator, "mark_settings_stale") as mark_stale:
        async with coordinator.write_lock:
            await entity._async_send(_command())
    await hass.async_block_till_done()

    assert mark_stale.call_count == 1
