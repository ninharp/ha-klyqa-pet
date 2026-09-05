"""Tests for the binary sensor platform."""

from unittest.mock import MagicMock, patch

from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .conftest import setup_integration


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.BINARY_SENSOR]):
        await setup_integration(hass, mock_config_entry)
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_binary_sensor_values(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.BINARY_SENSOR]):
        await setup_integration(hass, mock_config_entry)
    assert hass.states.get("binary_sensor.kitchen_fountain_water_tray_low").state == STATE_OFF
    assert hass.states.get("binary_sensor.kitchen_fountain_pump_problem").state == STATE_ON
    assert hass.states.get("binary_sensor.kitchen_fountain_charging").state == STATE_ON
    assert hass.states.get("binary_sensor.feeder_power_adapter").state == STATE_ON
    assert hass.states.get("binary_sensor.feeder_food_low").state == STATE_OFF
    assert (
        hass.states.get("binary_sensor.klyqa_airpurifier_e85dfc_ionizer_active").state == STATE_ON
    )
