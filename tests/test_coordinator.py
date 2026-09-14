"""Tests for the coordinator: translated UpdateFailed messages and settings polling."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.switch import SERVICE_TURN_ON
from homeassistant.const import ATTR_ENTITY_ID, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.klyqa_pet.const import DEFAULT_SCAN_INTERVAL
from custom_components.klyqa_pet.entity import KlyqaPetEntity
from pyklyqa_pet import KlyqaConnectionError, KlyqaRateLimitError, StrypeState, WellySettings

from .conftest import STRYPE_ID, WELLY_ID, load_json, setup_integration


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
