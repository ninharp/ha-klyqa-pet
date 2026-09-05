"""Tests for diagnostics."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.klyqa_pet.const import DOMAIN
from custom_components.klyqa_pet.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from .conftest import WELLY_ID, setup_integration


async def test_entry_diagnostics(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, mock_config_entry)
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result == snapshot
    assert "secret" not in str(result)
    assert "welly-token" not in str(result)


async def test_device_diagnostics(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, mock_config_entry)
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, WELLY_ID)}
    )
    result = await async_get_device_diagnostics(hass, mock_config_entry, device)
    assert result == snapshot
    assert result["local_device_id"] == WELLY_ID


async def test_diagnostics_without_loaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Both diagnostics functions must degrade gracefully without runtime_data."""
    mock_config_entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, WELLY_ID)}
    )

    entry_result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert entry_result["devices"] == []
    assert entry_result["entry_state"] == mock_config_entry.state.value
    assert entry_result["entry"]["data"]["password"] == "**REDACTED**"
    assert "secret" not in str(entry_result)

    device_result = await async_get_device_diagnostics(hass, mock_config_entry, device)
    assert device_result == {"error": "entry_not_loaded"}
