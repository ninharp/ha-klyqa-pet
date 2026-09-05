"""Tests for the sensor platform."""

from unittest.mock import MagicMock, patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .conftest import setup_integration


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
        await setup_integration(hass, mock_config_entry, entity_registry)
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
