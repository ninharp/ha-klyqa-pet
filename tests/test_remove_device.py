"""Tests for removing devices via the device registry."""

from unittest.mock import MagicMock

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.klyqa_pet import async_remove_config_entry_device
from custom_components.klyqa_pet.const import CONF_DEVICES, CONF_MANUAL_DEVICES, DOMAIN

from .conftest import WELLY_ID, device_record, setup_integration

MANUAL_ID = "AABBCCDDEE01"


async def _remove(
    hass: HomeAssistant, ws: WebSocketGenerator, entry_id: str, device_id: str
) -> bool:
    # The installed pytest_homeassistant_custom_component version's `remove_device`
    # helper wraps the current `config/device_registry/remove` websocket command,
    # which takes only a device_id (no config_entry_id): a device now belongs to a
    # single config entry, so the extra id is unnecessary. `entry_id` is kept as a
    # parameter for readability at call sites and to mirror the brief's helper shape.
    del entry_id
    # The "config" component registers the device_registry websocket commands; it is
    # not auto-loaded by hass_ws_client, so it must be set up explicitly.
    await async_setup_component(hass, "config", {})
    client = await ws(hass)
    response = await client.remove_device(device_id)
    return bool(response["success"])


async def test_active_cloud_device_cannot_be_removed(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, WELLY_ID)}
    )
    assert await _remove(hass, hass_ws_client, mock_config_entry.entry_id, device.id) is False


async def test_hostless_cloud_device_cannot_be_removed(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A cloud device without a host yet (no coordinator) must still be non-removable."""
    mock_config_entry.add_to_hass(hass)
    data = mock_config_entry.data
    hostless_welly = {
        k: v for k, v in data[CONF_DEVICES][WELLY_ID].items() if k not in (CONF_HOST, CONF_PORT)
    }
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**data, CONF_DEVICES: {**data[CONF_DEVICES], WELLY_ID: hostless_welly}},
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    hub = mock_config_entry.runtime_data
    assert WELLY_ID not in hub.coordinators
    assert WELLY_ID in hub.cloud_devices

    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, WELLY_ID)}
    )
    assert await _remove(hass, hass_ws_client, mock_config_entry.entry_id, device.id) is False


async def test_orphaned_device_can_be_removed(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, "000000000000")}
    )
    assert await _remove(hass, hass_ws_client, mock_config_entry.entry_id, device.id) is True


async def test_manual_device_removal_drops_option(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_MANUAL_DEVICES: {
                MANUAL_ID: device_record(
                    "aabbccddeeff0011223344", "", "@klyqa.welly-dev", "192.168.2.99"
                )
            }
        },
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    hub = mock_config_entry.runtime_data
    assert MANUAL_ID in hub.coordinators

    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, MANUAL_ID)}
    )
    assert await _remove(hass, hass_ws_client, mock_config_entry.entry_id, device.id) is True
    assert MANUAL_ID not in hub.coordinators
    assert MANUAL_ID not in mock_config_entry.options.get(CONF_MANUAL_DEVICES, {})


async def test_manual_device_removal_without_loaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Removing a manual device must work from stored options alone, entry not loaded."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_MANUAL_DEVICES: {
                MANUAL_ID: device_record(
                    "aabbccddeeff0011223344", "", "@klyqa.welly-dev", "192.168.2.99"
                )
            }
        },
    )
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, MANUAL_ID)}
    )

    result = await async_remove_config_entry_device(hass, mock_config_entry, device)

    assert result is True
    assert MANUAL_ID not in mock_config_entry.options.get(CONF_MANUAL_DEVICES, {})
