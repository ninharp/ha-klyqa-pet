"""Tests for the number platform."""

from unittest.mock import MagicMock, patch

from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from .conftest import FOODY_ID, setup_integration


@pytest.fixture
async def numbers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_cloud: MagicMock,
    mock_devices: dict,
) -> None:
    with patch("custom_components.klyqa_pet.PLATFORMS", [Platform.NUMBER]):
        await setup_integration(hass, mock_config_entry)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "numbers")
async def test_numbers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("numbers")
async def test_number_commands(
    hass: HomeAssistant, mock_welly: MagicMock, mock_foody: MagicMock
) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.kitchen_fountain_heating_temperature", ATTR_VALUE: 30},
        blocking=True,
    )
    mock_welly.set_heating.assert_awaited_with(True, 30)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.kitchen_fountain_daily_drinking_goal", ATTR_VALUE: 750},
        blocking=True,
    )
    mock_welly.set_daily_goal.assert_awaited_with(750)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.kitchen_fountain_circulation_pump_speed", ATTR_VALUE: 55},
        blocking=True,
    )
    mock_welly.update_settings.assert_awaited_with(circulation_pump_speed=55)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.feeder_feed_audio_volume", ATTR_VALUE: 70},
        blocking=True,
    )
    mock_foody.update_settings.assert_awaited_with(feed_audio_volume=70)


@pytest.mark.usefixtures("numbers")
async def test_portions_number_is_local(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_foody: MagicMock
) -> None:
    assert hass.states.get("number.feeder_portions").state == "1"
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.feeder_portions", ATTR_VALUE: 3},
        blocking=True,
    )
    assert hass.states.get("number.feeder_portions").state == "3"
    assert mock_config_entry.runtime_data.coordinators[FOODY_ID].dispense_portions == 3
    mock_foody.update_settings.assert_not_awaited()
